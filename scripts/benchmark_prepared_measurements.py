"""Compare complete point scoring on recorded ridges and historical trajectories.

The archived research candidate supplies workload coordinates and a clock, not
independent truth. Each source runs in a separate interpreter with bounded work
and identical observed inputs. This script generates no audio or trajectories.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

try:
    import resource
except ImportError:  # Windows does not provide the Unix resource module.
    resource = None

ROOT = Path(__file__).resolve().parents[1]


def json_scalar(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as output:
        json.dump(value, output, indent=2, allow_nan=True, default=json_scalar)
        output.write("\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=True, default=json_scalar)


def prepare(args):
    import pandas as pd
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.geometry import AcousticSupportError, ecef
    from dopplergeist.matching import prepare_events
    from dopplergeist.search import cpa_table
    from dopplergeist.tiled_search import SearchBudget, _support_error

    if args.output.exists():
        raise FileExistsError(f"Choose a new fixture path: {args.output}")
    discovery = json.loads(args.discovery.read_text())
    report = json.loads(args.reference_report.read_text())
    seed = report[0] if isinstance(report, list) else report["best"]
    point = {key: seed[key] for key in ("point_id", "lat", "lon", "elev_m", "x", "y")}
    clock = float(seed["recording_start_time_s"])
    events, measurements = prepare_events(discovery["events"])
    index = FlightIndex(args.index)
    window = [clock - args.clock_half_width_s, clock + args.clock_half_width_s]
    query_time = [window[0] - 120.0, window[1] + max(e["end_s"] for e in events) + 120.0]
    if args.full_day:
        query_time = list(index.report["coverage"]["time_range_s"])
    query_bounds = list(index.report["coverage"]["bounds"])
    budget = SearchBudget(max_tracks_per_tile=args.max_tracks,
                          max_track_samples_per_tile=args.max_samples,
                          max_candidates_per_tile=args.max_candidates, top_k=args.top_k)
    tracks, samples = [], 0
    for track in index.query(query_bounds, query_time):
        tracks.append(track)
        samples += len(track.time)
        if len(tracks) > args.max_tracks or samples > args.max_samples:
            raise ValueError("Declared trajectory budget exceeded; no input was silently truncated")
    if not tracks:
        raise ValueError("The declared real-data query returned no trajectories")
    points = pd.DataFrame([point])
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    radius = max(e["slant_range_m"][1] for e in events)
    tables, unsupported, row_count = [], [], 0
    for track in tracks:
        try:
            if track.outside_observer_radius(observers, radius):
                continue
            table = cpa_table([track], points, radius, step_s=budget.cpa_step_s)
        except AcousticSupportError as error:
            unsupported.append(_support_error(error))
            continue
        row_count += len(table)
        if row_count > budget.max_cpa_rows:
            raise ValueError("Declared CPA budget exceeded; no rows were silently truncated")
        if len(table):
            tables.append(table)
    if not tables:
        raise ValueError("The real-data point has no supported CPA rows")
    fixture = {
        "scope": "Recorded-input computation comparison; source-informed receiver/clock, no accuracy claim",
        "discovery_source": str(args.discovery.resolve()),
        "reference_report": str(args.reference_report.resolve()),
        "real_index": str(args.index.resolve()), "index_input_hash": index.report["input_hash"],
        "events": discovery["events"], "point": point,
        "query_bounds": query_bounds, "query_time_s": query_time,
        "track_ids": [track.id for track in tracks],
        "cpa_rows": pd.concat(tables, ignore_index=True).to_dict(orient="records"),
        "unsupported_cpa_tracks": unsupported,
        "budget": asdict(budget), "scoring": {"mode": "robust_ridge"},
        "recording_start_window_s": None if args.full_day else window,
        "counts": {"trajectories": len(tracks), "trajectory_samples": samples,
                   "ridge_records": len(discovery["events"]), "independent_groups": len(events),
                   "ridge_samples": sum(len(measurement[1]) for measurement in measurements),
                   "cpa_rows": row_count, "unsupported_cpa_tracks": len(unsupported)},
    }
    write_new(args.output, fixture)
    print(json.dumps({"fixture": str(args.output), **fixture["counts"],
                      "scope": fixture["scope"]}), flush=True)


def worker(args):
    source = args.source.resolve()
    sys.path.insert(0, str(source))
    import dopplergeist
    import pandas as pd
    from dopplergeist import matching, tiled_search
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.finite_search import RetentionLedger
    from dopplergeist.geometry import AcousticSupportError, Track

    if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
        raise RuntimeError("Comparison imported a different source tree")
    native_fit = getattr(matching, "_native_fit_irls", None)
    backend = getattr(matching, "RIDGE_FIT_BACKEND", "python-irls-v1")
    if args.require_native and not callable(native_fit):
        raise RuntimeError("The source-tree native fitter is unavailable; build it in place before timing")
    fixture = json.loads(args.fixture.read_text())
    index = FlightIndex(args.index or fixture["real_index"])
    if index.report["input_hash"] != fixture["index_input_hash"]:
        raise ValueError("The real trajectory index no longer matches the fixture")
    budget = tiled_search.SearchBudget(**fixture["budget"])
    loaded_at = time.perf_counter()
    tracks = list(index.lookup(fixture["track_ids"], max_tracks=budget.max_tracks_per_tile,
                               max_samples=budget.max_track_samples_per_tile))
    if sorted(track.id for track in tracks) != sorted(fixture["track_ids"]):
        raise ValueError("The index is missing a recorded trajectory")
    events, measurements = matching.prepare_events(fixture["events"])
    points = pd.DataFrame([fixture["point"]])
    load_seconds = time.perf_counter() - loaded_at
    args.output.mkdir(parents=True, exist_ok=False)
    ledger = RetentionLedger(args.output / "retention.sqlite", "recorded-point-benchmark",
                             "matched_group_support_minus_normalized_residual")
    stage = "coarse:recorded-point"
    operations = {"scalar_fit_calls": 0, "acoustic_calls": 0, "scored_candidates": 0,
                  "native_fit_calls": 0, "native_fit_successes": 0}
    all_rows = []
    original_fit, original_acoustic = matching._fit_ridge_uncached, Track.acoustic
    original_score = tiled_search.score_candidate

    def counted_fit(*values, **options):
        operations["scalar_fit_calls"] += 1
        return original_fit(*values, **options)

    def counted_acoustic(*values, **options):
        operations["acoustic_calls"] += 1
        return original_acoustic(*values, **options)

    def counted_native(*values, **options):
        operations["native_fit_calls"] += 1
        result = native_fit(*values, **options)
        if result is not None and all(math.isfinite(value) for value in result):
            operations["native_fit_successes"] += 1
        return result

    def captured_score(*values, **options):
        operations["scored_candidates"] += 1
        try:
            result = original_score(*values, **options)
        except AcousticSupportError as error:
            all_rows.append({"support_failure": tiled_search._support_error(error)})
            raise
        all_rows.append(result)
        return result

    matching._fit_ridge_uncached, Track.acoustic = counted_fit, counted_acoustic
    if callable(native_fit):
        matching._native_fit_irls = counted_native
    tiled_search.score_candidate = captured_score
    began, cpu = time.perf_counter(), time.process_time()
    try:
        ranked, counts = tiled_search._score(
            points, tracks, events, measurements, budget, fixture["scoring"], {},
            start_window=fixture["recording_start_window_s"], ledger=ledger, stage=stage)
    finally:
        elapsed, cpu_seconds = time.perf_counter() - began, time.process_time() - cpu
        matching._fit_ridge_uncached, Track.acoustic = original_fit, original_acoustic
        if callable(native_fit):
            matching._native_fit_irls = native_fit
        tiled_search.score_candidate = original_score
    expected_counts = fixture.get("expected_counts")
    if expected_counts is not None:
        actual_counts = {"cpa_rows": counts["cpa_rows"],
                         "associations": counts["candidates"], "retained": len(ranked)}
        if actual_counts != expected_counts:
            raise AssertionError(f"Recorded workload counts changed: {actual_counts}")
    # macOS reports bytes and Linux reports KiB. Keep scoring usable where
    # resource or its unit convention is unavailable, without guessing a value.
    peak_rss_mib = None
    if resource is not None and (sys.platform == "darwin" or sys.platform.startswith("linux")):
        rss_divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / rss_divisor
    checksum = ledger.checksum(stage)
    if not ledger.stage_valid(stage, checksum):
        raise AssertionError("The scoring pass produced an invalid retention ledger")
    if not operations["scored_candidates"]:
        raise AssertionError("The benchmark did not score any real associations")
    if args.require_native and not operations["native_fit_successes"]:
        raise AssertionError("The native fitter was available but no successful native fit was timed")
    with ledger.connect() as database:
        retention = {name: database.execute(f"SELECT * FROM {name} ORDER BY 1,2").fetchall()
                     for name in ("records", "bounds", "stages")}
    write_new(args.output / "results.json", {"ranked": ranked, "counts": counts,
              "all_scored_candidates": all_rows, "retention": retention})
    summary = {"wall_seconds": elapsed, "cpu_seconds": cpu_seconds,
               "load_seconds_excluded": load_seconds, "operations": operations,
               "ridge_fit_backend": backend, "native_extension_available": callable(native_fit),
               "peak_rss_mib": peak_rss_mib,
               "peak_rss_scope": ("Worker lifetime through scoring, including imports and input loading"
                                  if peak_rss_mib is not None else "Unavailable on this platform"),
               "retained": len(ranked), "independent_groups": len(events), "scope": fixture["scope"]}
    write_new(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


def compare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {"baseline": args.baseline_source.resolve(), "current": args.current_source.resolve()}
    environment = dict(os.environ)
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        environment[variable] = "1"
    runs, expected = [], None
    for repetition in range(args.repeats):
        order = ("baseline", "current") if repetition % 2 == 0 else ("current", "baseline")
        for name in order:
            output = args.output / f"{repetition + 1}-{name}"
            command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--source", str(sources[name]),
                       "--fixture", str(args.fixture.resolve()), "--output", str(output.resolve())]
            if args.index:
                command.extend(["--index", str(args.index.resolve())])
            if name == "current" and args.require_current_native:
                command.append("--require-native")
            subprocess.run(command, check=True, env=environment, timeout=args.timeout_s)
            payload = canonical(json.loads((output / "results.json").read_text()))
            if expected is None:
                expected = payload
            elif payload != expected:
                raise AssertionError(f"Exact candidate, diagnostic, support, or retention mismatch: {output}")
            summary = json.loads((output / "summary.json").read_text())
            runs.append({"source": name, "repetition": repetition + 1, **summary})
    medians = {}
    for name in sources:
        medians[name] = {}
        for metric in ("wall_seconds", "cpu_seconds", "peak_rss_mib"):
            values = [row[metric] for row in runs if row["source"] == name and row[metric] is not None]
            medians[name][metric] = statistics.median(values) if values else None
    report = {"identical_results": True, "repeats": args.repeats,
              "fixture": str(args.fixture.resolve()),
              "sources": {name: str(path) for name, path in sources.items()}, "medians": medians,
              "speedup": {metric: medians["baseline"][metric] / medians["current"][metric]
                          for metric in ("wall_seconds", "cpu_seconds")},
              "scope": runs[0]["scope"], "runs": runs}
    write_new(args.output / "comparison.json", report)
    print(json.dumps({key: report[key] for key in ("identical_results", "medians", "speedup", "scope")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare", help="Freeze a real observed-data scoring workload")
    preparation.add_argument("--discovery", required=True, type=Path)
    preparation.add_argument("--index", required=True, type=Path)
    preparation.add_argument("--reference-report", type=Path,
                             default=ROOT / "evidence/results/reference-local/report.json")
    preparation.add_argument("--clock-half-width-s", type=float, default=120.0)
    preparation.add_argument("--full-day", action="store_true", help="Use all indexed times with an unknown clock")
    preparation.add_argument("--max-tracks", type=int, default=5000)
    preparation.add_argument("--max-samples", type=int, default=1000000)
    preparation.add_argument("--max-candidates", type=int, default=20000)
    preparation.add_argument("--top-k", type=int, default=100)
    preparation.add_argument("--output", required=True, type=Path)
    comparison = commands.add_parser("compare", help="Require exact output parity before reporting speedup")
    comparison.add_argument("--fixture", required=True, type=Path)
    comparison.add_argument("--index", type=Path)
    comparison.add_argument("--baseline-source", required=True, type=Path, help="Baseline src/ directory")
    comparison.add_argument("--current-source", type=Path, default=ROOT / "src")
    comparison.add_argument("--repeats", type=int, default=3)
    comparison.add_argument("--timeout-s", type=float, default=600.0)
    comparison.add_argument("--output", required=True, type=Path)
    comparison.add_argument("--require-current-native", action="store_true",
                            help="Fail unless the timed current worker actually uses its native fitter")
    internal = commands.add_parser("_worker", help=argparse.SUPPRESS)
    internal.add_argument("--source", required=True, type=Path)
    internal.add_argument("--fixture", required=True, type=Path)
    internal.add_argument("--index", type=Path)
    internal.add_argument("--output", required=True, type=Path)
    internal.add_argument("--require-native", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.clock_half_width_s < 0:
            parser.error("--clock-half-width-s must be nonnegative")
        sys.path.insert(0, str(ROOT / "src"))
        prepare(args)
    elif args.command == "compare":
        if args.repeats < 1 or args.timeout_s <= 0:
            parser.error("--repeats and --timeout-s must be positive")
        compare(args)
    else:
        worker(args)


if __name__ == "__main__":
    main()

