"""Isolated coarse-tile workers with private retention ledgers."""
from collections import deque
from pathlib import Path
import tempfile

import pandas as pd

from .data_access import CachedTerrain, DataUnavailable, FlightIndex
from .finite_search import RetentionLedger
from .tiled_search import _expanded_bounds, _score, _tracks, tile_points


class TileFailure(DataUnavailable):
    """Recoverable tile failure carrying the terrain provenance it observed."""

    def __init__(self, message, provenance):
        self.provenance = provenance
        super().__init__(message, provenance)

    def __str__(self):
        return str(self.args[0])


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
    """Evaluate one tile and return its payload and completed private ledger."""
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
        tracks = _tracks(state["indexes"], _expanded_bounds(cells, budget.spacing_m, radius, state["crs"]),
                         state["time_range"], budget)
        points = (tile_points(cells, budget.spacing_m, state["bounds"], terrain, state["crs"])
                  if tracks else pd.DataFrame())
        with tempfile.NamedTemporaryFile(prefix="retention-", suffix=".sqlite",
                                         dir=state["ledger_directory"], delete=False) as handle:
            path = Path(handle.name)
        ledger = RetentionLedger(path, state["run_hash"], state["score_kind"])
        if len(points):
            kwargs = {"ledger": ledger, "stage": stage}
            if score_floor is not None:
                kwargs["score_floor"] = score_floor
            rows, counts = _score(points, tracks, state["events"], state["measurements"], budget,
                                  state["parameters"], state["filters"], state["start_window"], **kwargs)
        else:
            rows, counts = [], {}
            ledger.record(stage, [], [], 0)
        provenance = observed_terrain() if len(points) else {
            "terrain_files": [], "terrain_ocean_tiles": [], "terrain_failures": []}
        payload = {"ranked": rows, "counts": counts, "grid_points": len(points), "tracks": len(tracks),
                   "cells": list(cells), **provenance, "retention_checksum": ledger.checksum(stage)}
        return payload, str(path)
    except (DataUnavailable, ValueError, OSError) as error:
        if path is not None:
            path.unlink(missing_ok=True)
        raise TileFailure(str(error), observed_terrain()) from error
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def ordered_tile_futures(pool, jobs, workers):
    """Prefetch at most two tiles per worker, yielding in search order.

    Each job is ``(stage, cells, cached_payload, score_floor)``. Cached
    payloads require no worker. For other jobs the caller receives a future,
    imports its verified ledger, and checkpoints it before advancing.
    """
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    pending = deque()

    def enqueue(job):
        stage, cells, cached, floor = job
        future = None if cached is not None else pool.submit(score_tile, stage, cells, floor)
        pending.append((stage, cells, cached, future))

    for job in jobs:
        enqueue(job)
        if len(pending) >= 2 * workers:
            yield pending.popleft()
    while pending:
        yield pending.popleft()
