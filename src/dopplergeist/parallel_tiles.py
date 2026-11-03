"""Isolated coarse-tile workers with private retention ledgers."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import tempfile
from threading import Lock

import pandas as pd

from .data_access import CachedTerrain, DataUnavailable, FlightIndex
from .finite_search import RetentionLedger
from .parallel_retention import EmptyRetentionStage
from .tiled_search import (_expanded_bounds, _sample_tile_terrain, _score, _tile_anchor_window,
                           _tile_coordinates, _tracks_for_points)


class TileFailure(DataUnavailable):
    """Recoverable tile failure carrying the terrain provenance it observed."""

    def __init__(self, message, provenance):
        self.provenance = provenance
        super().__init__(message, provenance)

    def __str__(self):
        return str(self.args[0])


class WorkerAffinePool:
    """Keep tile work on the worker whose DEM cache best matches its area."""

    def __init__(self, pools, tile_dem_keys, cache_keys, chunk_size=4):
        if not pools:
            raise ValueError("At least one tile worker is required")
        if type(chunk_size) is not int or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        self.pools = tuple(pools)
        self.tile_dem_keys = tile_dem_keys
        self.cache_keys = cache_keys
        self.chunk_size = chunk_size
        self.lookahead = len(pools) * chunk_size
        self._resident = [frozenset() for _ in pools]
        self._pending = [[] for _ in pools]
        self._used = [False for _ in pools]
        self._next_lane = 0
        self._chunk_lane = None
        self._chunk_remaining = 0
        self._lock = Lock()

    def submit(self, function, stage, cells, score_floor):
        predicted = frozenset(self.tile_dem_keys(cells))
        with self._lock:
            if not self._chunk_remaining:
                eligible = [i for i, used in enumerate(self._used) if not used]
                if not eligible:
                    eligible = list(range(len(self.pools)))
                loads = [len(self._pending[i]) for i in eligible]
                least_loaded = min(loads)
                candidates = [i for i in eligible if len(self._pending[i]) == least_loaded]

                def affinity(worker):
                    nearby = self._resident[worker].union(*self._pending[worker])
                    return (-len(predicted.intersection(nearby)),
                            (worker - self._next_lane) % len(self.pools))

                self._chunk_lane = min(candidates, key=affinity)
                self._chunk_remaining = self.chunk_size
                self._used[self._chunk_lane] = True
            lane = self._chunk_lane
            self._chunk_remaining -= 1
            self._pending[lane].append(predicted)
            self._next_lane = (lane + 1) % len(self.pools)
        try:
            future = self.pools[lane].submit(function, stage, cells, score_floor)
        except BaseException:
            with self._lock:
                self._pending[lane].pop()
            raise
        future.add_done_callback(lambda completed, worker=lane: self._completed(worker, completed))
        return future

    def finish_wave(self):
        """Keep a short final chunk from leaking into the next search wave."""
        with self._lock:
            self._chunk_lane = None
            self._chunk_remaining = 0
            self._used = [False for _ in self.pools]

    def _completed(self, lane, future):
        try:
            resident = frozenset(self.cache_keys(future.result()))
        except BaseException:
            resident = frozenset()
        with self._lock:
            if self._pending[lane]:
                self._pending[lane].pop(0)
            self._resident[lane] = resident


@contextmanager
def tile_worker_lanes(workers, initializer, initargs, tile_dem_keys, chunk_size=4):
    """Create pinned worker processes so spatial cache affinity is real."""
    from .data_access import _index_pool

    with ExitStack() as stack:
        pools = [stack.enter_context(_index_pool(1, initializer, initargs)) for _ in range(workers)]
        yield WorkerAffinePool(pools, tile_dem_keys, lambda result: result[2], chunk_size=chunk_size)


_worker = None


def initialize_tile_worker(index_paths, terrain_root, terrain_options, events, measurements,
                           bounds, time_range, budget, parameters, filters, start_window,
                           crs, ledger_directory, run_hash, score_kind):
    """Initialize read-only indexes and reusable terrain state inside one worker."""
    global _worker
    _worker = {
        "indexes": [FlightIndex(path) for path in index_paths],
        "terrain": CachedTerrain(terrain_root, **terrain_options),
        "events": events, "measurements": measurements, "bounds": bounds,
        "time_range": time_range, "budget": budget, "parameters": parameters,
        "filters": filters, "start_window": start_window, "crs": crs,
        "ledger_directory": Path(ledger_directory), "run_hash": run_hash,
        "score_kind": score_kind,
    }
    _worker["ledger_directory"].mkdir(parents=True, exist_ok=True)


def score_tile(stage, cells, score_floor=None):
    """Return a tile payload and either its private ledger or empty descriptor."""
    if _worker is None:
        raise RuntimeError("Tile worker was not initialized")
    state = _worker
    budget = state["budget"]
    terrain = state["terrain"]
    terrain.last_sample_files = set()
    terrain.last_sample_ocean_tiles = set()
    failures_before = len(terrain.failures)
    path = None

    def observed_terrain():
        names = getattr(terrain, "last_sample_files", set())
        return {"terrain_files": [terrain.files[name] for name in sorted(names) if name in terrain.files],
                "terrain_ocean_tiles": sorted(getattr(terrain, "last_sample_ocean_tiles", set())),
                "terrain_failures": terrain.failures[failures_before:]}

    try:
        radius = max(event["slant_range_m"][1] for event in state["events"])
        points = _tile_coordinates(cells, budget.spacing_m, state["bounds"], state["crs"])
        tracks = []
        if len(points):
            tracks, points = _tracks_for_points(
                state["indexes"], _expanded_bounds(cells, budget.spacing_m, radius, state["crs"]),
                state["time_range"], budget, points, terrain, radius, state["parameters"].get("c", 343.0))
        if tracks and "elev_m" not in points:
            points = _sample_tile_terrain(points, terrain)
        sampled = "elev_m" in points
        if not tracks:
            points = pd.DataFrame()
        if len(points):
            with tempfile.NamedTemporaryFile(prefix="retention-", suffix=".sqlite",
                                             dir=state["ledger_directory"], delete=False) as handle:
                path = Path(handle.name)
            ledger = RetentionLedger(path, state["run_hash"], state["score_kind"])
            kwargs = {"ledger": ledger, "stage": stage}
            anchor = _tile_anchor_window(stage.removeprefix("coarse:"), state["start_window"],
                                         state["parameters"], state["filters"], state["events"])
            if anchor is not None:
                kwargs["anchor_window"] = anchor
            if score_floor is not None:
                kwargs["score_floor"] = score_floor
            rows, counts = _score(points, tracks, state["events"], state["measurements"], budget,
                                  state["parameters"], state["filters"], state["start_window"], **kwargs)
            checksum = ledger.checksum(stage)
            retention = str(path)
        else:
            rows, counts = [], {}
            retention = EmptyRetentionStage.for_stage(state["run_hash"], state["score_kind"], stage)
            checksum = retention.checksum
        provenance = observed_terrain() if sampled else {
            "terrain_files": [], "terrain_ocean_tiles": [], "terrain_failures": []}
        payload = {"ranked": rows, "counts": counts, "grid_points": len(points), "tracks": len(tracks),
                   "cells": list(cells), **provenance, "retention_checksum": checksum}
        return payload, retention
    except (DataUnavailable, ValueError, OSError) as error:
        if path is not None:
            path.unlink(missing_ok=True)
        raise TileFailure(str(error), observed_terrain()) from error
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def score_tile_with_cache_state(stage, cells, score_floor=None):
    """Return the worker's resident DEM keys for scheduling; never persist them."""
    payload, retention = score_tile(stage, cells, score_floor)
    cache_keys = tuple(path.stem for path in _worker["terrain"]._tile_cache)
    return payload, retention, cache_keys


def ordered_tile_results(pool, jobs, workers, finish):
    """Persist promptly, bound out-of-order results, and yield in input order."""
    from concurrent.futures import FIRST_COMPLETED, wait

    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    source = iter(jobs)
    pending, ready = {}, {}
    assigned = next_result = 0
    exhausted = False
    lookahead = getattr(pool, "lookahead", 2 * workers)
    while not exhausted or pending or ready:
        while (not exhausted and len(pending) + len(ready) < lookahead
               and next_result not in ready):
            try:
                stage, cells, cached, floor = next(source)
            except StopIteration:
                exhausted = True
                break
            index = assigned
            assigned += 1
            if cached is None:
                scorer = score_tile_with_cache_state if isinstance(pool, WorkerAffinePool) else score_tile
                future = pool.submit(scorer, stage, cells, floor)
                pending[future] = (index, stage, cells)
            else:
                ready[index] = (stage, cells, cached, True)
        if next_result in ready:
            yield ready.pop(next_result)
            next_result += 1
            continue
        if pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                index, stage, cells = pending.pop(future)
                ready[index] = (stage, cells, finish(stage, cells, future), False)
        elif exhausted and ready:
            raise RuntimeError("Tile result ordering is inconsistent")
    if isinstance(pool, WorkerAffinePool):
        pool.finish_wave()
