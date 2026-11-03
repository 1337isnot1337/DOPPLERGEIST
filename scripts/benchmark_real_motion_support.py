#!/usr/bin/env python3
"""Compare motion-support checks on the archived real trajectory audit."""
import argparse
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import platform
import statistics
import sys
import time

import numpy as np


def load_geometry(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def observed_tracks(module, observations):
    grouped = defaultdict(list)
    for row in observations:
        grouped[row["flight_id"]].append(row)
    tracks = []
    for identity, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row["time_s"])
        values = {name: np.array([row[name] for row in rows]) for name in
                  ("time_s", "lat", "lon", "alt_m", "east_mps", "north_mps", "up_mps")}
        velocity = module.velocity_ecef(values["lat"], values["lon"],
            values["east_mps"], values["north_mps"], values["up_mps"])
        tracks.append(module.Track(identity, values["time_s"], values["lat"], values["lon"],
                                     values["alt_m"], rows[0]["typecode"], velocity))
    return tracks


def arrival_outcome(module, track, receive, observer):
    try:
        track._check_motion_support(receive, observer, 343.)
    except module.AcousticSupportError as error:
        return {key: getattr(error, key) for key in
                ("track_id", "reason", "emission_intervals_s", "receive_intervals_s")}
    return None


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-geometry", type=Path, required=True)
    parser.add_argument("--current-geometry", type=Path, default=root/"src/dopplergeist/geometry.py")
    parser.add_argument("--observations", type=Path,
        default=root/"research/trajectory-motion/frozen/canonical-observations.json")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--interval-calls", type=int, default=1000)
    parser.add_argument("--arrival-calls", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.repetitions, args.interval_calls, args.arrival_calls) < 1:
        parser.error("repetitions and call counts must be positive")
    if args.output.exists():
        parser.error("output exists; use a new result path")
    observations = json.loads(args.observations.read_text())
    modules = {"baseline": load_geometry("motion_baseline", args.baseline_geometry),
               "current": load_geometry("motion_current", args.current_geometry)}
    tracks = {label: observed_tracks(module, observations) for label, module in modules.items()}
    results = []
    for before, after in zip(tracks["baseline"], tracks["current"]):
        middle = len(before.time)//2
        observer = modules["baseline"].ecef(before.lat[middle], before.lon[middle], 0.)
        receive = before.time+np.linalg.norm(before.xyz-observer, axis=1)/343.
        expected = before._unsupported_motion_intervals(343.)
        actual = after._unsupported_motion_intervals(343.)
        if not np.array_equal(expected, actual):
            raise AssertionError(f"Motion interval mismatch for {before.id}")
        if arrival_outcome(modules["baseline"], before, receive, observer) != arrival_outcome(
                modules["current"], after, receive, observer):
            raise AssertionError(f"Arrival support mismatch for {before.id}")
        for method, count in (("intervals", args.interval_calls), ("arrivals", args.arrival_calls)):
            runs = {"baseline": [], "current": []}
            for repetition in range(args.repetitions):
                order = [("baseline", before), ("current", after)]
                if repetition % 2:
                    order.reverse()
                for label, track in order:
                    cpu, wall = time.process_time(), time.perf_counter()
                    for _ in range(count):
                        if method == "intervals":
                            track._unsupported_motion_intervals(343.)
                        else:
                            arrival_outcome(modules[label], track, receive, observer)
                    runs[label].append({"cpu_s": time.process_time()-cpu,
                                        "wall_s": time.perf_counter()-wall})
            medians = {label: {clock: statistics.median(row[clock] for row in trials)
                              for clock in ("cpu_s", "wall_s")}
                       for label, trials in runs.items()}
            result = {"track_id": before.id, "observations": len(before.time),
                      "unsupported_intervals": len(expected), "method": method,
                      "calls_per_trial": count, "trials": runs, "median": medians,
                      "cpu_speedup": medians["baseline"]["cpu_s"]/medians["current"]["cpu_s"]}
            results.append(result)
            print(json.dumps({key: result[key] for key in
                  ("track_id", "method", "median", "cpu_speedup")}), flush=True)
    report = {"scope": "Warm motion-support checks on four recorded aircraft with known input-motion inconsistencies. No synthesized audio or trajectories; not an end-to-end or location-accuracy benchmark.",
              "baseline_geometry": str(args.baseline_geometry.resolve()),
              "current_geometry": str(args.current_geometry.resolve()),
              "python": platform.python_version(), "numpy": np.__version__,
              "observation_count": len(observations), "repetitions": args.repetitions,
              "exact_results": True, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
