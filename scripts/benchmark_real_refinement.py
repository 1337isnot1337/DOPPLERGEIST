"""Compare complete sensitivity profiling on the frozen real-recording case.

Each arm uses a fresh interpreter, the same observed flight index, and restored
terrain. The input candidate is the recorded finalist before its full profile.
Input loading and that earlier finalist refinement are outside the timed span.
This source-informed development replay does not measure localization accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def scalar(value):
    return value.tolist() if hasattr(value, "tolist") else value.item()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=True, default=scalar)


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=True, default=scalar)
        stream.write("\n")


def close_terrain(sampler):
    for raster in sampler.rasters:
        raster.close()
    if sampler.geoid is not None:
        close_terrain(sampler.geoid)


def source_hashes(source):
    return {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((source / "dopplergeist").rglob("*"))
            if path.is_file() and path.suffix in (".py", ".c", ".so", ".pyd")}


def worker(args):
    source = args.source.resolve()
    sys.path.insert(0, str(source))
    import dopplergeist
    from dopplergeist import matching, native_acoustic
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.terrain import Terrain

    if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
        raise RuntimeError("The worker imported a different source tree")
    if args.require_native and not callable(getattr(matching, "_native_fit_irls", None)):
        raise RuntimeError("The selected source's native ridge backend is unavailable")
    native = getattr(native_acoustic, "_native", None)
    counter = getattr(native, "successful_calls", None)
    if args.require_native_acoustic and not callable(counter):
        raise RuntimeError("The selected source's native acoustic counter is unavailable")
    fixture = json.loads(args.fixture.read_text())
    candidate = fixture["candidate"]
    index = FlightIndex(args.index)
    tracks = {track.id: track for track in index.lookup(candidate["flight_ids"])}
    if set(tracks) != set(candidate["flight_ids"]):
        raise ValueError("The observed index is missing a recorded candidate flight")
    events, measurements = matching.prepare_events(fixture["events"], c=343., max_distance_m=20000.)
    dem, geoid = [args.terrain_root / path for path in fixture["source"]["terrain_data"]]
    terrain = Terrain([dem], geoid_path=geoid)
    before_native = counter() if callable(counter) else None
    call = matching._cache_ridge_fits(matching.profile_candidate)
    try:
        began, cpu = time.perf_counter(), time.process_time()
        result = call(candidate, tracks, events, measurements, terrain,
                      radius_m=500., c=343.,
                      recording_start_window_s=fixture["recording_start_window_s"])
        elapsed, cpu_seconds = time.perf_counter() - began, time.process_time() - cpu
        cache_entries = {"terrain": len(getattr(terrain, "_pixel_cache", {})),
                         "geoid": len(getattr(terrain.geoid, "_pixel_cache", {}))}
    finally:
        close_terrain(terrain)
    profiles = len(result["sensitivity"]["profiles"])
    if profiles != fixture["expected_profile_count"]:
        raise AssertionError("The complete recorded scenario inventory changed")
    native_calls = counter() - before_native if before_native is not None else None
    if args.require_native_acoustic and not native_calls:
        raise RuntimeError("The worker did not perform a successful native acoustic solve")
    workload = {"recording_sha256": fixture["source"]["recording_sha256"],
                "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
                "recorded_job": fixture["source"]["job_id"],
                "index_input_hash": index.report["input_hash"],
                "event_records": len(fixture["events"]), "independent_groups": len(events),
                "matched_groups": len(candidate["event_indices"]),
                "trajectories": len(tracks),
                "trajectory_samples": sum(len(track.time) for track in tracks.values()),
                "profiles": profiles}
    summary = {"wall_seconds": elapsed, "cpu_seconds": cpu_seconds,
               "source_sha256": source_hashes(source),
               "native_acoustic_successes": native_calls, "workload": workload,
               "pixel_cache_entries": cache_entries,
               "ridge_fit_backend": matching.RIDGE_FIT_BACKEND,
               "acoustic_backend": native_acoustic.ACOUSTIC_BACKEND,
               "timing_scope": "Complete profile_candidate and its exact-fit cache; excludes imports, index lookup, terrain construction, event preparation and earlier finalist refinement."}
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output / "result.json", result)
    write_new(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


def compare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {"baseline": args.baseline_source.resolve(), "current": args.current_source.resolve()}
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
                       OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    rows, expected, workload = [], None, None
    for repeat in range(1, args.repeats + 1):
        order = ("baseline", "current") if repeat % 2 else ("current", "baseline")
        for label in order:
            output = args.output / f"{repeat}-{label}"
            command = [sys.executable, str(Path(__file__).resolve()), "_worker",
                       "--source", str(sources[label]), "--fixture", str(args.fixture.resolve()),
                       "--index", str(args.index.resolve()), "--terrain-root", str(args.terrain_root.resolve()),
                       "--output", str(output.resolve())]
            if args.require_native:
                command.append("--require-native")
            if args.require_native_acoustic:
                command.append("--require-native-acoustic")
            subprocess.run(command, check=True, env=environment, timeout=args.timeout_s)
            result = encoded(json.loads((output / "result.json").read_text()))
            summary = json.loads((output / "summary.json").read_text())
            if expected is None:
                expected, workload = result, summary["workload"]
            if result != expected or summary["workload"] != workload:
                raise AssertionError(f"Recorded profile or workload changed in {output}")
            rows.append(dict(summary, source=label, pair=repeat))
    medians = {label: {metric: statistics.median(row[metric] for row in rows if row["source"] == label)
                       for metric in ("wall_seconds", "cpu_seconds")} for label in sources}
    report = {"identical_results": True, "repeats": args.repeats,
              "fixture": str(args.fixture.resolve()), "index": str(args.index.resolve()),
              "terrain_root": str(args.terrain_root.resolve()),
              "sources": {key: str(value) for key, value in sources.items()},
              "workload": workload, "medians": medians,
              "speedup": {metric: medians["baseline"][metric] / medians["current"][metric]
                          for metric in ("wall_seconds", "cpu_seconds")},
              "timing_scope": rows[0]["timing_scope"],
              "cache_scope": "Fresh interpreter and terrain per arm; operating-system caches are not flushed. Numerical libraries use one thread.",
              "scope": "Recorded finalist with source-informed bounds and clock; not an independent location-accuracy or complete HTTP benchmark.",
              "runs": rows}
    write_new(args.output / "comparison.json", report)
    print(json.dumps({key: report[key] for key in ("identical_results", "medians", "speedup", "workload")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    comparison = commands.add_parser("compare", help="Compare full recorded profiles in alternating fresh processes")
    comparison.add_argument("--baseline-source", type=Path, required=True)
    comparison.add_argument("--current-source", type=Path, default=ROOT / "src")
    comparison.add_argument("--repeats", type=int, default=3)
    comparison.add_argument("--timeout-s", type=float, default=180.)
    internal = commands.add_parser("_worker", help=argparse.SUPPRESS)
    internal.add_argument("--source", type=Path, required=True)
    for command in (comparison, internal):
        command.add_argument("--fixture", type=Path, default=ROOT / "tests/data/real-refinement-profile.json")
        command.add_argument("--index", type=Path, required=True)
        command.add_argument("--terrain-root", type=Path, default=ROOT,
                             help="Root containing restored data/terrain files")
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--require-native", action="store_true",
                             help="Require the native ridge backend to be enabled")
        command.add_argument("--require-native-acoustic", action="store_true",
                             help="Require successful native acoustic solves")
    args = parser.parse_args()
    if args.command == "compare":
        if args.repeats < 1 or not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
            parser.error("--repeats and --timeout-s must be positive")
        compare(args)
    else:
        worker(args)


if __name__ == "__main__":
    main()
