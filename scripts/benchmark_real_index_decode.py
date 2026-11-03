"""Compare fresh real index queries and exact Track fields outside the timer.

This component isolates data_access.py from two source trees. Both arms use
the current shared geometry and normalization modules. Timing includes SQLite
traversal, payload integrity, gzip/JSON, column extraction, Track construction
and admission to a fresh cache. Metadata loading and all subsequent pipeline
stages are outside this timer. No generated aircraft observations are used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time


def file_digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def assert_array_exact(actual, expected, label):
    assert type(actual) is type(expected), label
    assert actual.dtype == expected.dtype and actual.shape == expected.shape, label
    if actual.dtype.hasobject:
        assert actual.tolist() == expected.tolist(), label
    else:
        assert actual.tobytes() == expected.tobytes(), label


def assert_tracks_exact(actual, expected):
    import numpy as np
    from scipy.interpolate import PPoly

    assert [track.id for track in actual] == [track.id for track in expected], "Track inventory changed"
    for got, wanted in zip(actual, expected):
        assert vars(got).keys() == vars(wanted).keys(), got.id
        for name, value in vars(wanted).items():
            other, label = getattr(got, name), f"{got.id}:{name}"
            assert type(other) is type(value), label
            if isinstance(value, np.ndarray):
                assert_array_exact(other, value, label)
            elif isinstance(value, PPoly):
                assert_array_exact(other.c, value.c, label + ":coefficients")
                assert_array_exact(other.x, value.x, label + ":knots")
                assert other.axis == value.axis and other.extrapolate == value.extrapolate, label
            elif isinstance(value, (float, np.floating)):
                assert other.hex() == value.hex(), label
            else:
                assert other == value, label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1:
        parser.error("Use a new output path and at least one repeat")
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    from dopplergeist import data_access
    from dopplergeist import _native_index

    if data_access._native_payload_columns is None:
        parser.error("The current native index extractor must be enabled")
    source = args.baseline_source.resolve() / "dopplergeist/data_access.py"
    name = "dopplergeist._recorded_index_decode_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[name] = baseline
    spec.loader.exec_module(baseline)
    fixture = json.loads(args.fixture.read_text())
    expected, timings, inventory = None, [], None
    for repeat in range(args.repeats):
        arms = [("baseline", baseline), ("current", data_access)]
        if repeat % 2:
            arms.reverse()
        for label, module in arms:
            index = module.FlightIndex(fixture["real_index"])
            if index.report["input_hash"] != fixture["index_input_hash"]:
                raise ValueError("The recorded index identity changed")
            native_before = _native_index.successful_calls()
            wall, cpu = time.perf_counter(), time.process_time()
            tracks = list(index.query(fixture["query_bounds"], fixture["query_time_s"]))
            cpu_seconds, wall_seconds = time.process_time() - cpu, time.perf_counter() - wall
            native_calls = _native_index.successful_calls() - native_before
            if label == "current" and native_calls == 0:
                raise AssertionError("The current query made no native column extractions")
            observed = {"tracks": len(tracks), "samples": sum(len(track.time) for track in tracks)}
            prepared = fixture.get("track_query_preparation")
            if prepared is not None:
                assert observed == {"tracks": prepared["queried_trajectories"],
                                    "samples": prepared["queried_trajectory_samples"]}
            if expected is None:
                expected, inventory = tracks, observed
            else:
                assert observed == inventory
                assert_tracks_exact(tracks, expected)
            timings.append({"arm": label, "repeat": repeat + 1,
                            "cpu_seconds": cpu_seconds, "wall_seconds": wall_seconds,
                            "native_extractions": native_calls})
            del tracks, index
    medians = {label: {metric: statistics.median(row[metric] for row in timings if row["arm"] == label)
                       for metric in ("cpu_seconds", "wall_seconds")}
               for label in ("baseline", "current")}
    report = {"scope": __doc__.strip(), "fixture": str(args.fixture.resolve()),
              "index_input_hash": fixture["index_input_hash"], "inventory": inventory,
              "exact_all_track_fields": True, "timings": timings, "median_seconds": medians,
              "speedup": {metric: medians["baseline"][metric] / medians["current"][metric]
                          for metric in ("cpu_seconds", "wall_seconds")},
              "implementation": {"baseline_file": str(source),
                                 "baseline_sha256": file_digest(source),
                                 "current_file": str(Path(data_access.__file__).resolve()),
                                 "current_sha256": file_digest(data_access.__file__),
                                 "native_binary_sha256": file_digest(_native_index.__file__)},
              "environment": {"python": platform.python_version(), "platform": platform.platform(),
                              "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                              "numerical_threads": 1}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({"inventory": inventory, "exact_all_track_fields": True,
                      "median_seconds": medians, "speedup": report["speedup"]}), flush=True)


if __name__ == "__main__":
    main()
