#!/usr/bin/env python3
"""Compare identity/terrain helpers on restored observations and candidate rows.

This is a component benchmark. Both duplicate-query variants use the same
current, cache-disabled FlightIndex so the identity change is measured alone.
No observations, receiver results, or timing evidence are generated artificially.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
from statistics import median
import sys
import time

import numpy as np

from dopplergeist import terrain, tiled_search
from dopplergeist.data_access import FlightIndex, content_hash


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def json_geometry_digest(track):
    return content_hash([track.id, track.time.tolist(), track.xyz.tolist(), track.spline.c.tolist()])


def identity_partition(values):
    groups = {}
    for index, value in enumerate(values):
        groups.setdefault(value, []).append(index)
    return sorted(groups.values())


def assert_tracks_equal(actual, expected):
    assert [track.id for track in actual] == [track.id for track in expected]
    for got, want in zip(actual, expected):
        for name in ("time", "xyz"):
            np.testing.assert_array_equal(getattr(got, name), getattr(want, name))
        np.testing.assert_array_equal(got.spline.c, want.spline.c)


def timed(function):
    wall, cpu = time.perf_counter(), time.process_time()
    result = function()
    return result, {"wall_s": time.perf_counter() - wall, "cpu_s": time.process_time() - cpu}


def compare(functions, repeats, verify):
    trials = {name: [] for name in functions}
    names = list(functions)
    for iteration in range(repeats):
        for name in names if iteration % 2 == 0 else reversed(names):
            result, elapsed = timed(functions[name])
            verify(name, result)
            trials[name].append(elapsed)
    medians = {name: {metric: median(row[metric] for row in rows)
                      for metric in ("wall_s", "cpu_s")}
               for name, rows in trials.items()}
    return {"trials": trials, "median": medians,
            "wall_speedup": medians["baseline"]["wall_s"] / medians["current"]["wall_s"],
            "cpu_speedup": medians["baseline"]["cpu_s"] / medians["current"]["cpu_s"]}


def close_terrain(sampler):
    for raster in sampler.rasters:
        raster.close()
    if sampler.geoid:
        close_terrain(sampler.geoid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path,
                        help="Optional historical fixture containing index path and query bounds/time")
    parser.add_argument("--index", type=Path, help="Restored real flight index; overrides the fixture path")
    parser.add_argument("--bounds", type=float, nargs=4, metavar=("W", "S", "E", "N"))
    parser.add_argument("--time-range", type=float, nargs=2, metavar=("START", "END"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads(args.fixture.read_text()) if args.fixture else {}
    index_path = args.index or fixture.get("real_index")
    bounds = args.bounds or fixture.get("query_bounds")
    time_range = args.time_range or fixture.get("query_time_s")
    if index_path is None or bounds is None or time_range is None:
        parser.error("Supply --index, --bounds and --time-range, or a fixture containing those values")
    query_args = bounds, time_range
    args.output.mkdir(parents=True, exist_ok=False)
    baseline_tiles = load_module("dopplergeist._reference_helper_tiles",
                                 args.baseline / "src/dopplergeist/tiled_search.py")
    baseline_terrain = load_module("dopplergeist._reference_helper_terrain",
                                   args.baseline / "src/dopplergeist/terrain.py")

    def decode():
        return list(FlightIndex(index_path, track_cache_bytes=0).query(*query_args))

    first, second = decode(), decode()
    assert first and all(a is not b for a, b in zip(first, second))
    assert_tracks_equal(first, second)
    old = [json_geometry_digest(track) for track in first + second]
    new = [tiled_search._track_geometry_digest(track) for track in first + second]
    assert identity_partition(old) == identity_partition(new)
    expected_digests = {"baseline": old[:len(first)], "current": new[:len(first)]}

    def verify_digests(name, result):
        assert result == expected_digests[name]

    digest_results = compare({
        "baseline": lambda: [json_geometry_digest(track) for track in first],
        "current": lambda: [tiled_search._track_geometry_digest(track) for track in first],
    }, args.repeats, verify_digests)
    print(json.dumps({"stage": "identity_digest", **digest_results["median"]}), flush=True)

    def duplicate_query(module):
        indexes = [FlightIndex(index_path, track_cache_bytes=0) for _ in range(2)]
        return module._tracks(indexes, *query_args, tiled_search.SearchBudget())

    duplicate_results = compare({
        "baseline": lambda: duplicate_query(baseline_tiles),
        "current": lambda: duplicate_query(tiled_search),
    }, args.repeats, lambda name, result: assert_tracks_equal(result, first))
    print(json.dumps({"stage": "duplicate_query", **duplicate_results["median"]}), flush=True)

    rows = json.loads((root / "evidence/results/reference-local-fast/ranked.json").read_text())
    lat, lon = [np.asarray([row[key] for row in rows]) for key in ("lat", "lon")]
    dem = root / "data/terrain/Copernicus_DSM_COG_10_N40_00_W074_00_DEM.tif"
    geoid = root / "data/terrain/us_nga_egm96_15.tif"
    samplers = {name: module.Terrain([dem], geoid_path=geoid)
                for name, module in (("baseline", baseline_terrain), ("current", terrain))}
    terrain._raster_transformer.cache_clear()
    try:
        expected = samplers["baseline"].sample(lat, lon)
        np.testing.assert_array_equal(samplers["current"].sample(lat, lon), expected)

        def scalar_samples(name):
            return np.asarray([samplers[name].sample(a, b).item() for a, b in zip(lat, lon)])

        scalar_results = compare({name: lambda name=name: scalar_samples(name) for name in samplers},
                                 args.repeats, lambda name, result: np.testing.assert_array_equal(result, expected))
        vector_results = compare({name: lambda name=name: samplers[name].sample(lat, lon) for name in samplers},
                                 args.repeats, lambda name, result: np.testing.assert_array_equal(result, expected))
        cache_info = terrain._raster_transformer.cache_info()._asdict()
    finally:
        for sampler in samplers.values():
            close_terrain(sampler)

    summary = {"scope": "Real observations and archived candidate coordinates; component timings only",
               "fixture": str(args.fixture.resolve()) if args.fixture else None,
               "index": str(Path(index_path).resolve()), "query_bounds": bounds, "query_time_s": time_range,
               "baseline": str(args.baseline.resolve()),
               "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
               "threads": {key: os.environ.get(key) for key in
                           ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
               "tracks": len(first), "samples": sum(len(track.time) for track in first),
               "independent_decodes_exact": True, "old_new_identity_relation_exact": True,
               "duplicate_track_geometry_exact": True, "terrain_arrays_exact": True,
               "candidate_rows": len(rows), "unique_candidate_coordinates": len(set(zip(lat, lon))),
               "identity_digest": digest_results, "duplicate_index_query": duplicate_results,
               "terrain_scalar_queries": scalar_results, "terrain_vector_query": vector_results,
               "terrain_transform_cache": cache_info}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"output": str(args.output / "summary.json"),
                      "speedups": {name: summary[name]["wall_speedup"] for name in
                                   ("identity_digest", "duplicate_index_query", "terrain_scalar_queries",
                                    "terrain_vector_query")}}), flush=True)


if __name__ == "__main__":
    main()
