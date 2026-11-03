"""Measure repeated whole-segment queries against a supplied real flight index.

This measures trajectory loading, including integrity checks and output
fingerprints. It is not an audio/search runtime or location-accuracy benchmark.
The first pass has a cold decoded-track cache; subsequent passes reuse it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

import numpy as np

from dopplergeist.data_access import FlightIndex


def measure(index, bounds, time_range, max_tracks, max_samples):
    digest = hashlib.sha256()
    tracks = samples = 0
    started = time.perf_counter()
    started_cpu = time.process_time()
    for track in index.query(bounds, time_range):
        tracks += 1
        samples += len(track.time)
        if tracks > max_tracks or samples > max_samples:
            raise ValueError("Real query exceeds the benchmark track/sample budget")
        digest.update(json.dumps([track.id, track.typecode, track.altitude_basis,
                                  track.aircraft_class, track.velocity_inferred_components],
                                 sort_keys=True, allow_nan=False).encode())
        for values in (track.time, track.lat, track.lon, track.altitude, track.xyz,
                       track.spline.c, track.derivative.c):
            array = np.asarray(values, dtype="<f8")
            digest.update(str(array.shape).encode())
            digest.update(array.tobytes(order="C"))
    return {"wall_s": time.perf_counter() - started, "cpu_s": time.process_time() - started_cpu, "tracks": tracks,
            "samples": samples, "geometry_and_labels_sha256": digest.hexdigest(),
            "cached_tracks": len(index._track_cache),
            "serialized_cache_bytes": index._track_cache_bytes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--bounds", type=float, nargs=4, required=True, metavar=("W", "S", "E", "N"))
    parser.add_argument("--time-range", type=float, nargs=2, required=True, metavar=("START", "END"))
    parser.add_argument("--passes", type=int, default=4)
    parser.add_argument("--cache-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--max-tracks", type=int, default=2000)
    parser.add_argument("--max-samples", type=int, default=500000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path to preserve earlier measurements")
    if args.passes < 2 or min(args.cache_bytes, args.max_tracks, args.max_samples) < 1:
        parser.error("Use at least two passes and positive cache/track/sample limits")
    instances = {"uncached": FlightIndex(args.index, track_cache_bytes=0),
                 "cached": FlightIndex(args.index, track_cache_bytes=args.cache_bytes)}
    runs = {name: [] for name in instances}
    for trial in range(args.passes):
        for name in (("uncached", "cached") if trial % 2 == 0 else ("cached", "uncached")):
            runs[name].append(measure(instances[name], args.bounds, args.time_range,
                                      args.max_tracks, args.max_samples))
    signatures = {(run["tracks"], run["samples"], run["geometry_and_labels_sha256"])
                  for group in runs.values() for run in group}
    if len(signatures) != 1 or not runs["uncached"][0]["tracks"]:
        raise AssertionError("Queries differ or contain no real tracks")
    medians = {name: statistics.median(run["wall_s"] for run in group[1:]) for name, group in runs.items()}
    totals = {name: sum(run["wall_s"] for run in group) for name, group in runs.items()}
    report = {"scope": "Repeated real trajectory query; excludes acquisition, audio and scoring",
              "index": str(args.index.resolve()), "input_hash": instances["cached"].report["input_hash"],
              "bounds": args.bounds, "time_range_s": args.time_range, "passes": runs,
              "same_geometry_and_labels": True, "median_warm_query_s": medians,
              "warm_query_speedup": medians["uncached"] / medians["cached"],
              "first_query_s": {name: group[0]["wall_s"] for name, group in runs.items()},
              "all_query_passes_s": totals,
              "all_passes_speedup_including_cold_cache": totals["uncached"] / totals["cached"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps(report, indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
