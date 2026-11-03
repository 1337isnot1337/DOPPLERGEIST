#!/usr/bin/env python3
"""Compare CPA preparation on archived aircraft observations, without fake tracks."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

import numpy as np
import pandas as pd

from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist import search
from dopplergeist.tracks import _segment_velocity


ROOT = Path(__file__).resolve().parents[1]


def recorded_tracks():
    """Use the normal gap split and velocity inference on frozen real traces."""
    tracks = []
    for source in sorted((ROOT / "research/trajectory-motion/frozen").glob("fresh-*.json")):
        frame = pd.DataFrame(json.loads(source.read_text())).sort_values("time_s")
        for part, (_, rows) in enumerate(frame.groupby((frame.time_s.diff() > 30.).cumsum())):
            if len(rows) < 3:
                continue
            velocity, _ = _segment_velocity(rows)
            tracks.append(Track(f"{rows.flight_id.iloc[0]}:{part}", rows.time_s.to_numpy(),
                rows.lat.to_numpy(), rows.lon.to_numpy(), rows.alt_m.to_numpy(),
                str(rows.typecode.iloc[0]), velocity))
    if not tracks:
        raise ValueError("Archived real observation inputs are missing")
    return tracks


def recorded_points(tracks, count):
    """Candidate coordinates sampled from the real traces; no accuracy claim."""
    locations = np.concatenate([np.column_stack((track.lat, track.lon)) for track in tracks])
    selected = locations[np.linspace(0, len(locations)-1, count, dtype=int)]
    return pd.DataFrame({"point_id": np.arange(count), "lat": selected[:, 0],
                         "lon": selected[:, 1], "elev_m": np.zeros(count)})


def cpa_stage(module, tracks, points, radius=20000., c=343., step=2., chunk_size=512,
              row_mode=False, *, reuse_samples=True, max_cpa_rows=100000, counters=None):
    """The bounded track-isolation loop, before acoustic candidate scoring."""
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    point_ids = points.point_id.to_numpy(dtype=int)
    tables, batches, unsupported = [], [], []
    count = 0
    for track in tracks:
        samples = math.ceil((track.time[-1]-track.time[0])/step)+1
        receiver_chunk = max(1, max_cpa_rows//samples)
        track_tables, track_batches, track_rows = [], [], 0
        prepared = None
        try:
            if track.outside_observer_radius(observers, radius, c):
                continue
            if row_mode and reuse_samples and hasattr(module, "_PreparedCPATrack"):
                prepared = module._PreparedCPATrack(track, c, step)
                if counters is not None:
                    counters["sample_preparations"] += 1
            for first in range(0, len(points), receiver_chunk):
                if counters is not None:
                    counters["receiver_chunks"] += 1
                if prepared is not None:
                    result = module._ordered_cpa_rows(prepared.raw_rows(
                        observers[first:first+receiver_chunk], point_ids[first:first+receiver_chunk],
                        radius, chunk_size), step)
                else:
                    if counters is not None:
                        counters["sample_preparations"] += 1
                    result = (module._cpa_rows([track], observers[first:first+receiver_chunk],
                              point_ids[first:first+receiver_chunk], radius, c, step, chunk_size) if row_mode else
                              module.cpa_table([track], points.iloc[first:first+receiver_chunk],
                                               radius, c, step, chunk_size))
                track_rows += len(result)
                if count+track_rows > max_cpa_rows:
                    raise ValueError("Tile CPA-row memory budget exceeded")
                if len(result):
                    if row_mode:
                        track_batches.append(np.array(result, dtype=search._CPA_DTYPE))
                    else:
                        track_tables.append(result)
                del result
        except AcousticSupportError as error:
            unsupported.append(vars(error))
            continue
        finally:
            prepared = None
        count += track_rows
        if row_mode:
            batches.extend(track_batches)
        else:
            tables.extend(track_tables)
    if row_mode:
        table = (pd.DataFrame({name: np.concatenate([batch[name] for batch in batches])
                              for name in search._CPA_DTYPE.names}, copy=False) if batches else
                 pd.DataFrame(columns=search._CPA_COLUMNS))
    else:
        table = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(columns=search._CPA_COLUMNS)
    return table, unsupported


def compare(before, after):
    pd.testing.assert_frame_equal(before[0], after[0], check_exact=True)
    assert before[1] == after[1], "Unsupported-track accounting changed"


def counted_chunked_stage(tracks, points, reuse):
    """Count actual tree construction while keeping every recorded input fixed."""
    counters = {"sample_preparations": 0, "tree_builds": 0, "receiver_chunks": 0}
    tree = search.cKDTree

    def counted_tree(*args, **kwargs):
        counters["tree_builds"] += 1
        return tree(*args, **kwargs)

    search.cKDTree = counted_tree
    try:
        result = cpa_stage(search, tracks, points, row_mode=True, reuse_samples=reuse,
                           counters=counters)
    finally:
        search.cKDTree = tree
    return result, counters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True,
                        help="Baseline src directory from a separate checkout")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    if args.repeats < 1 or args.iterations < 1:
        parser.error("repeats and iterations must be positive")
    path = args.baseline_source / "dopplergeist/search.py"
    spec = importlib.util.spec_from_file_location("dopplergeist._cpa_before", path)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    tracks = recorded_tracks()
    workloads = {str(count): recorded_points(tracks, count) for count in (1, 32, 128)}
    checks = 0
    for points in workloads.values():
        wide_ids = pd.concat([points.iloc[:1], points.iloc[:1]], ignore_index=True)
        wide_ids["point_id"] = [2**53, 2**53+1]
        for radius, c, step, chunk_size in ((1000., 343., 2., 512), (20000., 343., 2., 512),
                                           (20000., 338., 1., 7), (20000., 348., 8., 1),
                                           (20000., 343., np.float32(2), 512)):
            for candidate_points in (points, points.iloc[::-1], pd.concat([points, points], ignore_index=True), wide_ids):
                old = cpa_stage(baseline, tracks, candidate_points, radius, c, step, chunk_size)
                new = cpa_stage(search, tracks, candidate_points, radius, c, step, chunk_size, True)
                compare(old, new)
                checks += 1
                supported = []
                for track in tracks:
                    try:
                        track.validate_motion_support(c)
                        supported.append(track)
                    except AcousticSupportError:
                        pass
                pd.testing.assert_frame_equal(
                    baseline.cpa_table(supported, candidate_points, radius, c, step, chunk_size),
                    search.cpa_table(supported, candidate_points, radius, c, step, chunk_size),
                    check_exact=True)
                checks += 1
    timings = []
    for name, points in workloads.items():
        runs = {"baseline": [], "current": []}
        final = None
        for repeat in range(args.repeats):
            arms = [("baseline", baseline, False), ("current", search, True)]
            if repeat % 2:
                arms.reverse()
            for label, module, row_mode in arms:
                start = time.process_time()
                for _ in range(args.iterations):
                    result = cpa_stage(module, tracks, points, row_mode=row_mode)
                runs[label].append(time.process_time()-start)
                final = result
        medians = {name: statistics.median(values) for name, values in runs.items()}
        timings.append({"receiver_points": int(name), "cpa_rows": len(final[0]),
            "unsupported_tracks": len(final[1]), "iterations_per_trial": args.iterations,
            "cpu_s": runs, "median_cpu_s": medians,
            "speedup": medians["baseline"]/medians["current"]})
    chunked_timings = []
    for size in (1024, 4096):
        points = recorded_points(tracks, size)
        before, old_counts = counted_chunked_stage(tracks, points, False)
        after, new_counts = counted_chunked_stage(tracks, points, True)
        compare(before, after)
        checks += 1
        runs = {"repeated_preparation": [], "reused_preparation": []}
        for repeat in range(args.repeats):
            arms = [("repeated_preparation", False), ("reused_preparation", True)]
            if repeat % 2:
                arms.reverse()
            for label, reuse in arms:
                started = time.process_time()
                for _ in range(args.iterations):
                    cpa_stage(search, tracks, points, row_mode=True, reuse_samples=reuse)
                runs[label].append(time.process_time()-started)
        medians = {label: statistics.median(values) for label, values in runs.items()}
        chunked_timings.append({"receiver_points": size, "cpa_rows": len(after[0]),
            "unsupported_tracks": len(after[1]), "max_cpa_rows": 100000,
            "iterations_per_trial": args.iterations, "cpu_s": runs, "median_cpu_s": medians,
            "speedup": medians["repeated_preparation"]/medians["reused_preparation"],
            "operations": {"repeated_preparation": old_counts, "reused_preparation": new_counts}})
    result = {"scope": "CPA preparation on archived real ADS-B observations; excludes acoustic fitting, downloads, and localization accuracy.",
        "baseline_source": str(args.baseline_source), "tracks": len(tracks),
        "runtime": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                    "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None},
        "observed_samples": sum(len(track.time) for track in tracks),
        "exact_comparisons": checks, "timings": timings,
        "chunked_comparison": "Same current code and recorded inputs, trajectory/tree reuse disabled versus enabled; normal 100000-row budget",
        "chunked_timings": chunked_timings}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
