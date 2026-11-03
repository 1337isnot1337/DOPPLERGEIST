"""Compare shared-pool and worker-affine DEM access on saved real tiles."""
import argparse
from collections import Counter
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np

from dopplergeist import parallel_tiles
from dopplergeist.data_access import CachedTerrain, _index_pool
from dopplergeist.parallel_tiles import ordered_tile_results, tile_worker_lanes
from dopplergeist.tiled_search import _tile_coordinates, _tile_dem_keys


_terrain = None
_points = None
_counters = None
_ready_barrier = None


def _initialize_worker(terrain_root, points, ready_barrier):
    global _terrain, _points, _counters, _ready_barrier
    _terrain = CachedTerrain(terrain_root, offline=True)
    _points = points
    _counters = {"opens": 0, "hits": 0, "misses": 0}
    _ready_barrier = ready_barrier

    import rasterio

    original_open = rasterio.open

    def counted_open(path, *args, **kwargs):
        if Path(path).name.startswith("Copernicus_DSM_COG_30_"):
            _counters["opens"] += 1
        return original_open(path, *args, **kwargs)

    rasterio.open = counted_open
    original_sample = CachedTerrain._raster_sample

    def counted_sample(terrain, path, lat, lon):
        if Path(path).name.startswith("Copernicus_DSM_COG_30_"):
            _counters["hits" if Path(path) in terrain._tile_cache else "misses"] += 1
        return original_sample(terrain, path, lat, lon)

    CachedTerrain._raster_sample = counted_sample


def _warmup_worker():
    _ready_barrier.wait(timeout=120)
    return os.getpid()


def _sample_tile(stage, cells, score_floor=None):
    lat, lon = _points[tuple(cells)]
    before = dict(_counters)
    cpu_started = time.process_time()
    elevations = _terrain.sample(lat, lon)
    cpu_s = time.process_time() - cpu_started
    delta = {key: _counters[key] - before[key] for key in _counters}
    cache_keys = tuple(path.stem for path in _terrain._tile_cache)
    digest = hashlib.sha256(np.asarray(elevations, dtype="<f8").tobytes()).hexdigest()
    return digest, delta, cache_keys, os.getpid(), cpu_s


def _eligible_tiles(job, count):
    rows = []
    for path in (job / "search").glob("tile-*.json"):
        try:
            payload = json.loads(path.read_text())["payload"]
            cells = tuple(payload["cells"])
            if payload.get("grid_points", 0) < 500 or len(payload.get("terrain_files", [])) < 3:
                continue
            dem_names = {Path(source["path"]).name for source in payload["terrain_files"]
                         if Path(source["path"]).name.startswith("Copernicus_DSM_COG_30_")}
            if dem_names:
                rows.append((cells[1], cells[0], path.name, cells, dem_names))
        except (KeyError, OSError, ValueError, TypeError):
            continue
    rows.sort()
    if len(rows) < count:
        raise ValueError(f"Need at least {count} saved terrain tiles; found {len(rows)}")

    best_start, best_score = 0, -1
    for start in range(len(rows) - count + 1):
        frequencies = Counter(name for row in rows[start:start + count] for name in row[4])
        score = sum(amount * (amount - 1) for amount in frequencies.values())
        if score > best_score:
            best_start, best_score = start, score
    selected = rows[best_start:best_start + count]
    return [(name.removeprefix("tile-").removesuffix(".json"), cells)
            for _, _, name, cells, _ in selected]


def _run(pool_context, jobs, workers, lookahead=None):
    results = []
    with pool_context as pool:
        if isinstance(pool, parallel_tiles.WorkerAffinePool):
            warmups = [lane.submit(_warmup_worker) for lane in pool.pools]
        else:
            warmups = [pool.submit(_warmup_worker) for _ in range(workers)]
        warmup_pids = [future.result(timeout=120) for future in warmups]
        if len(set(warmup_pids)) != workers:
            raise RuntimeError(f"Expected {workers} workers, started {len(set(warmup_pids))}")
        if lookahead is not None and not hasattr(pool, "lookahead"):
            pool.lookahead = lookahead
        results.extend(ordered_tile_results(
            pool, jobs, workers, lambda stage, cells, future: future.result()))
    by_worker = {}
    for _, _, result, _ in results:
        digest, delta, cache_keys, pid, cpu_s = result
        record = by_worker.setdefault(pid, {"dem_raster_opens": 0, "cache_hits": 0,
                                            "cache_misses": 0, "cpu_s": 0.0,
                                            "resident_dem_tiles": 0})
        record["dem_raster_opens"] += delta["opens"]
        record["cache_hits"] += delta["hits"]
        record["cache_misses"] += delta["misses"]
        record["cpu_s"] += cpu_s
        record["resident_dem_tiles"] = sum(
            name.startswith("Copernicus_DSM_COG_30_") for name in cache_keys)
    hashes = [prepared[0] for _, _, prepared, _ in results]
    return {"ordered_hashes": hashes, "worker_count": len(warmup_pids),
            "workers": [record for _, record in sorted(by_worker.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True, help="saved real job with a search manifest")
    parser.add_argument("--cache", type=Path, required=True, help="populated real cache containing terrain/")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--tiles", type=int, default=12)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=4)
    args = parser.parse_args()
    if min(args.workers, args.tiles, args.repetitions, args.chunk_size) < 1:
        parser.error("workers, tiles, repetitions, and chunk-size must be positive")

    config = json.loads((args.job / "search/manifest.json").read_text())["configuration"]
    selected = _eligible_tiles(args.job, args.tiles)
    points = {}
    for _, cells in selected:
        frame = _tile_coordinates(cells, config["budget"]["spacing_m"], config["bounds"], config["crs"])
        points[cells] = (frame.lat.to_numpy(), frame.lon.to_numpy())
    jobs = [(f"coarse:{name}:pass-{rep}", cells, None, None)
            for rep in range(args.repetitions) for name, cells in selected]
    terrain_root = args.cache / "terrain"
    catalog_path = args.cache / "terrain/tileList.txt"
    catalog = {line.rstrip("/") for line in catalog_path.read_text().splitlines()}
    affinity_keys = lambda cells: _tile_dem_keys(
        cells, config["budget"]["spacing_m"], config["bounds"], config["crs"], catalog)
    original_score_tile = parallel_tiles.score_tile
    original_affine_score = parallel_tiles.score_tile_with_cache_state
    parallel_tiles.score_tile = _sample_tile
    parallel_tiles.score_tile_with_cache_state = _sample_tile
    try:
        began = time.perf_counter()
        barrier = multiprocessing.get_context("spawn").Barrier(args.workers)
        shared_context = _index_pool(args.workers, _initialize_worker,
                                     (terrain_root, points, barrier))
        lookahead = args.workers * args.chunk_size
        shared = _run(shared_context, jobs, args.workers, lookahead=lookahead)
        shared_elapsed = time.perf_counter() - began

        began = time.perf_counter()
        barrier = multiprocessing.get_context("spawn").Barrier(args.workers)
        affinity_context = tile_worker_lanes(
            args.workers, _initialize_worker, (terrain_root, points, barrier), affinity_keys,
            chunk_size=args.chunk_size)
        affinity = _run(affinity_context, jobs, args.workers, lookahead=lookahead)
        affinity_elapsed = time.perf_counter() - began
    finally:
        parallel_tiles.score_tile = original_score_tile
        parallel_tiles.score_tile_with_cache_state = original_affine_score

    if shared["ordered_hashes"] != affinity["ordered_hashes"]:
        raise AssertionError("shared-pool and worker-affine elevation samples differ")
    output = {"tiles": [name for name, _ in selected], "points_per_tile": [len(v[0]) for v in points.values()],
              "repetitions": args.repetitions, "workers": args.workers, "chunk_size": args.chunk_size,
              "shared_pool": {"elapsed_s": shared_elapsed, **shared},
              "worker_affine": {"elapsed_s": affinity_elapsed, **affinity},
              "elevation_arrays_equal": True,
              "note": "Real saved-grid terrain replay; not a full-search timing or accuracy result."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2), flush=True)


if __name__ == "__main__":
    main()
