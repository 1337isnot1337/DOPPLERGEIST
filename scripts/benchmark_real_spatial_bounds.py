#!/usr/bin/env python3
"""Compare complete CPA rows on a frozen real query, isolating distance sieves.

Index decoding, audio discovery, acoustic scoring, terrain, and localization
accuracy are outside the timed scope. Every timed arm uses cold track caches.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import statistics
import sys
import time

import pandas as pd

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.matching import prepare_events
from dopplergeist.search import _PreparedCPATrack, _ordered_cpa_rows


def cpa_stage(tracks, points, sieve, radius, c, step, max_rows, max_samples):
    """Keep production track isolation, receiver chunks, and row budgets."""
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    identifiers = points.point_id.to_numpy(dtype=int)
    rows, unsupported, prepared_ids = [], [], []
    for track in tracks:
        samples = math.ceil((track.time[-1] - track.time[0]) / step) + 1
        if samples > max_samples:
            raise ValueError("CPA time-sampling memory budget exceeded")
        receiver_chunk = max(1, max_rows // samples)
        track_rows = []
        try:
            if sieve(track, observers, radius, c):
                continue
            prepared_ids.append(track.id)
            prepared = _PreparedCPATrack(track, c, step)
            for first in range(0, len(points), receiver_chunk):
                track_rows.extend(_ordered_cpa_rows(prepared.raw_rows(
                    observers[first:first + receiver_chunk],
                    identifiers[first:first + receiver_chunk], radius), step))
                if len(rows) + len(track_rows) > max_rows:
                    raise ValueError("Tile CPA-row memory budget exceeded")
        except AcousticSupportError as error:
            unsupported.append(vars(error))
            continue
        rows.extend(track_rows)
    payload = json.dumps([rows, unsupported], sort_keys=True, allow_nan=True)
    counts = {"prepared_tracks": len(prepared_ids), "cpa_rows": len(rows),
              "unsupported_tracks": len(unsupported)}
    return payload, counts, set(prepared_ids), {row[1] for row in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1:
        parser.error("Use a new output path and at least one repeat")
    name = "dopplergeist._spatial_bounds_baseline"
    spec = importlib.util.spec_from_file_location(name, args.baseline_source / "dopplergeist/geometry.py")
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[name] = baseline
    spec.loader.exec_module(baseline)
    # Both methods receive the same current Track objects. Their validation
    # raises this shared exception class, including in the baseline branch.
    baseline.AcousticSupportError = AcousticSupportError
    fixture = json.loads(args.fixture.read_text())
    points = pd.DataFrame(fixture["points"] if "points" in fixture else [fixture["point"]])
    events, _ = prepare_events(fixture["events"])
    budget = fixture["budget"]
    tracks = list(FlightIndex(fixture["real_index"], track_cache_bytes=0).query(
        fixture["query_bounds"], fixture["query_time_s"]))
    # Locally produced trusted snapshots return independent arrays and cold
    # per-track caches while excluding index decoding from this stage timing.
    snapshot = pickle.dumps(tracks, protocol=pickle.HIGHEST_PROTOCOL)
    inventory = {"tracks": len(tracks), "samples": sum(len(t.time) for t in tracks),
                 "receiver_points": len(points), "queried_track_ids": [t.id for t in tracks]}
    del tracks
    options = dict(radius=max(e["slant_range_m"][1] for e in events),
                   c=fixture.get("scoring", {}).get("c", 343.),
                   step=budget["cpa_step_s"], max_rows=budget["max_cpa_rows"],
                   max_samples=budget["max_track_samples_per_tile"])
    results, timings, counts, prepared, cpa_ids = {}, [], {}, {}, {}
    for repeat in range(args.repeats):
        arms = [("baseline", baseline.Track.outside_observer_radius),
                ("current", Track.outside_observer_radius)]
        if repeat % 2:
            arms.reverse()
        for label, sieve in arms:
            tracks = pickle.loads(snapshot)
            assert [t.id for t in tracks] == inventory["queried_track_ids"]
            wall, cpu = time.perf_counter(), time.process_time()
            result, count, identifiers, contributing = cpa_stage(tracks, points, sieve, **options)
            timings.append({"arm": label, "repeat": repeat + 1,
                            "cpu_seconds": time.process_time() - cpu,
                            "wall_seconds": time.perf_counter() - wall})
            if results:
                assert result == next(iter(results.values())), "CPA rows or unsupported accounting changed"
            results[label], counts[label], prepared[label], cpa_ids[label] = result, count, identifiers, contributing
            del tracks
    assert prepared["current"] <= prepared["baseline"], "Previously excluded track retained"
    removed = prepared["baseline"] - prepared["current"]
    assert not removed & cpa_ids["baseline"], "An excluded track had baseline CPA rows"
    medians = {label: {metric: statistics.median(row[metric] for row in timings if row["arm"] == label)
                       for metric in ("cpu_seconds", "wall_seconds")}
               for label in ("baseline", "current")}
    output = {"scope": __doc__.strip(), "fixture": str(args.fixture),
              "baseline_source": str(args.baseline_source), "inventory": inventory,
              "controls": {"independent_cold_track_snapshots": True, "alternating_arm_order": True,
                           "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                           "thread_environment": {name: os.environ.get(name) for name in
                               ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}},
              "identical_queried_inventory": True, "exact_cpa_and_support_parity": True,
              "additional_proven_exclusions": sorted(removed),
              "every_removed_track_had_zero_baseline_cpa_rows": True,
              "counts": counts, "timings": timings, "median_seconds": medians,
              "speedup": {metric: medians["baseline"][metric] / medians["current"][metric]
                          for metric in ("cpu_seconds", "wall_seconds")}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(output, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"counts": counts, "additional_proven_exclusions": len(removed),
                      "exact_cpa_and_support_parity": True, "speedup": output["speedup"]}))


if __name__ == "__main__":
    main()
