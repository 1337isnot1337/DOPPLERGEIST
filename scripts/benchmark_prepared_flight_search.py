"""Measure real flight-query, overload-sieve and scoring work with exact parity.

Use a frozen recorded-data fixture and two pinned src/ directories. Each arm runs
in a fresh interpreter. An optional prepared index changes representation only;
its one-time construction is measured separately by the prepare-index command.
The source-informed regional receiver and anchor partition are performance
workloads, not independent localization or complete national-search evidence.
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

try:
    import resource
except ImportError:
    resource = None

ROOT = Path(__file__).resolve().parents[1]

# Query and scientific-output capture adapted from the project's PR #258
# benchmark_prepared_measurements.py; keep the original scoring harness intact.


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

def query_tracks(index, points, events, budget, scoring, bounds, time_range):
    """Count actual index traversal while exercising the production overload path."""
    from dopplergeist.tiled_search import _tracks_for_points

    if "elev_m" not in points:
        raise ValueError("The recorded receiver hypothesis must include its elevation")
    operations = {"query_calls": 0, "decoded_track_yields": 0, "decoded_sample_yields": 0}
    inventory = {}
    ordered_inventory = []

    class CountedIndex:
        def query(self, query_bounds, query_time):
            operations["query_calls"] += 1
            for track in index.query(query_bounds, query_time):
                operations["decoded_track_yields"] += 1
                operations["decoded_sample_yields"] += len(track.time)
                inventory[track.id] = len(track.time)
                ordered_inventory.append([track.id, len(track.time)])
                yield track

    radius = max(event["slant_range_m"][1] for event in events)
    tracks, points = _tracks_for_points(
        [CountedIndex()], bounds, time_range, budget, points, None, radius,
        scoring.get("c", 343.0))
    accounting = {
        "queried_tracks_in_order": ordered_inventory,
        "queried_track_ids": sorted(inventory),
        "queried_trajectory_samples": sum(inventory.values()),
        "selected_track_ids": [track.id for track in tracks],
        "selected_trajectory_samples": sum(len(track.time) for track in tracks),
    }
    return tracks, points, operations, accounting

def worker(args):
    source = args.source.resolve()
    sys.path.insert(0, str(source))
    import dopplergeist
    import pandas as pd
    from dopplergeist import geometry, matching, tiled_search
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.finite_search import RetentionLedger
    from dopplergeist.geometry import AcousticSupportError, Track

    if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
        raise RuntimeError("Comparison imported a different source tree")
    native_fit = getattr(matching, "_native_fit_irls", None)
    ridge_backend = getattr(matching, "RIDGE_FIT_BACKEND", "python-irls-v1")
    acoustic_backend = getattr(geometry, "ACOUSTIC_BACKEND", "python-acoustic-v1")
    try:
        from dopplergeist.native_acoustic import _native as native_acoustic
    except ImportError:
        native_acoustic = None
    if args.require_native and not callable(native_fit):
        raise RuntimeError("The selected source's native ridge fitter is unavailable")
    if args.require_native_acoustic and native_acoustic is None:
        raise RuntimeError("The selected source's native acoustic solver is unavailable")
    fixture = json.loads(args.fixture.read_text())
    index = FlightIndex(args.index or fixture["real_index"],
                        track_cache_bytes=args.track_cache_bytes)
    if index.report["input_hash"] != fixture["index_input_hash"]:
        raise ValueError("The real trajectory index no longer matches the fixture")
    if args.require_prepared and not getattr(index, "_prepared_tracks", False):
        raise RuntimeError("The selected source cannot use this prepared index")
    budget = tiled_search.SearchBudget(**fixture["budget"])
    loaded_at = time.perf_counter()
    tracks = None
    if not args.include_track_query:
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
                  "native_fit_calls": 0, "native_fit_successes": 0,
                  "native_acoustic_successes": 0, "prepared_decode_calls": 0,
                  "prepared_decode_successes": 0}
    all_rows = []
    original_fit, original_acoustic = matching._fit_ridge_uncached, Track.acoustic
    original_score = tiled_search.score_candidate
    phase_seconds, phase_patches = {}, []
    original_decoder, payload_module = None, None
    if getattr(index, "_prepared_tracks", False):
        from dopplergeist import flight_payload as payload_module
        original_decoder = payload_module.decode_track

        def counted_decode(*values, **options):
            operations["prepared_decode_calls"] += 1
            track = original_decoder(*values, **options)
            operations["prepared_decode_successes"] += 1
            return track

        payload_module.decode_track = counted_decode

    def timed_phase(name, function):
        def run(*values, **options):
            began, cpu = time.perf_counter(), time.process_time()
            try:
                return function(*values, **options)
            finally:
                phase = phase_seconds.setdefault(name, {"wall_seconds": 0.0, "cpu_seconds": 0.0, "calls": 0})
                phase["wall_seconds"] += time.perf_counter() - began
                phase["cpu_seconds"] += time.process_time() - cpu
                phase["calls"] += 1
        return run

    if args.stage_timing:
        phase_targets = [
            (Track, "outside_observer_radius", "distance_sieve"),
            (matching, "association_candidates", "association_enumeration"),
            (tiled_search, "merge_candidates", "retention"),
        ]
        if callable(getattr(tiled_search, "cpa_table", None)):
            phase_targets.append((tiled_search, "cpa_table", "closest_approach"))
        else:
            prepared_cpa = getattr(tiled_search, "_PreparedCPATrack", None)
            if prepared_cpa is not None:
                phase_targets.extend([
                    (prepared_cpa, "__init__", "closest_approach_preparation"),
                    (prepared_cpa, "raw_rows", "closest_approach"),
                ])
        for owner, attribute, name in phase_targets:
            function = getattr(owner, attribute, None)
            if function is not None:
                phase_patches.append((owner, attribute, function))
                setattr(owner, attribute, timed_phase(name, function))
    score_function = timed_phase("candidate_scoring", original_score) if args.stage_timing else original_score

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
            result = score_function(*values, **options)
        except AcousticSupportError as error:
            all_rows.append({"support_failure": tiled_search._support_error(error)})
            raise
        all_rows.append(result)
        return result

    matching._fit_ridge_uncached, Track.acoustic = counted_fit, counted_acoustic
    tiled_search.score_candidate = captured_score
    if callable(native_fit):
        matching._native_fit_irls = counted_native
    native_acoustic_before = native_acoustic.successful_calls() if native_acoustic is not None else 0
    query_accounting, query_operations, execution_stages = None, None, {}
    began, cpu = time.perf_counter(), time.process_time()
    try:
        if args.include_track_query:
            query_began, query_cpu = time.perf_counter(), time.process_time()
            tracks, points, query_operations, query_accounting = query_tracks(
                index, points, events, budget, fixture["scoring"],
                fixture["query_bounds"], fixture["query_time_s"])
            execution_stages["track_query_and_distance_sieve"] = {
                "wall_seconds": time.perf_counter() - query_began,
                "cpu_seconds": time.process_time() - query_cpu,
            }
            if query_accounting["selected_track_ids"] != fixture["track_ids"]:
                raise AssertionError("The real query changed the ordered selected-track inventory")
            if query_accounting["selected_trajectory_samples"] != fixture["counts"]["trajectory_samples"]:
                raise AssertionError("The real query changed the selected trajectory sample count")
            prepared_query = fixture.get("track_query_preparation")
            if prepared_query is not None:
                if (len(query_accounting["queried_track_ids"]) != prepared_query["queried_trajectories"]
                        or query_accounting["queried_trajectory_samples"] != prepared_query["queried_trajectory_samples"]):
                    raise AssertionError("The real query changed the complete observed-track inventory")
            scoring_began, scoring_cpu = time.perf_counter(), time.process_time()
        partition = ({"anchor_window": fixture["anchor_window_s"]}
                     if "anchor_window_s" in fixture else {})
        ranked, counts = tiled_search._score(
            points, tracks, events, measurements, budget, fixture["scoring"], {},
            start_window=fixture["recording_start_window_s"], ledger=ledger, stage=stage, **partition)
        if args.include_track_query:
            execution_stages["cpa_association_scoring_and_retention"] = {
                "wall_seconds": time.perf_counter() - scoring_began,
                "cpu_seconds": time.process_time() - scoring_cpu,
            }
    finally:
        elapsed, cpu_seconds = time.perf_counter() - began, time.process_time() - cpu
        matching._fit_ridge_uncached, Track.acoustic = original_fit, original_acoustic
        tiled_search.score_candidate = original_score
        if callable(native_fit):
            matching._native_fit_irls = native_fit
        if native_acoustic is not None:
            operations["native_acoustic_successes"] = native_acoustic.successful_calls() - native_acoustic_before
        for owner, attribute, function in reversed(phase_patches):
            setattr(owner, attribute, function)
        if payload_module is not None:
            payload_module.decode_track = original_decoder
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
        raise AssertionError("No successful native ridge fit occurred inside the timed scoring call")
    if args.require_native_acoustic and not operations["native_acoustic_successes"]:
        raise AssertionError("No successful native acoustic solve occurred inside the timed scoring call")
    if args.require_prepared and not operations["prepared_decode_successes"]:
        raise AssertionError("No successful prepared decode occurred inside the timed query")
    with ledger.connect() as database:
        retention = {name: database.execute(f"SELECT * FROM {name} ORDER BY 1,2").fetchall()
                     for name in ("records", "bounds", "stages")}
    results = {"ranked": ranked, "counts": counts,
               "all_scored_candidates": all_rows, "retention": retention}
    if query_accounting is not None:
        results["track_query_accounting"] = query_accounting
    results["workload"] = {key: fixture.get(key) for key in (
        "index_input_hash", "point", "events", "query_bounds", "query_time_s",
        "recording_start_window_s", "anchor_window_s", "budget", "scoring")}
    results["index_coverage"] = index.report["coverage"]
    write_new(args.output / "results.json", results)
    summary = {"wall_seconds": elapsed, "cpu_seconds": cpu_seconds,
               "load_seconds_excluded": load_seconds, "operations": operations,
               "ridge_fit_backend": ridge_backend, "acoustic_backend": acoustic_backend,
               "native_extension_available": callable(native_fit),
               "peak_rss_mib": peak_rss_mib,
               "peak_rss_scope": ("Worker lifetime through scoring, including imports and input loading"
                                  if peak_rss_mib is not None else "Unavailable on this platform"),
               "retained": len(ranked), "independent_groups": len(events), "scope": fixture["scope"]}
    summary["index_prepared_tracks"] = index.report.get("prepared_tracks")
    summary["track_cache_bytes"] = args.track_cache_bytes
    if "anchor_window_s" in fixture:
        summary["anchor_window_s"] = fixture["anchor_window_s"]
    if args.include_track_query:
        summary["track_query_operations"] = query_operations
        summary["execution_stage_seconds"] = execution_stages
        summary["timing_scope"] = (
            "Initial local index traversal and conservative distance sieve, followed by complete "
            "CPA/association scoring and retention. Excludes imports, index metadata, event "
            "preparation, downloads, terrain sampling, audio discovery, and refinement.")
    if args.stage_timing:
        summary["phase_seconds"] = phase_seconds
        summary["phase_timing_scope"] = "Inclusive instrumented call times; overlapping phases must not be summed."
    write_new(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_index(args):
    """Time a new optional representation without changing the original index."""
    sys.path.insert(0, str(args.source.resolve()))
    import dopplergeist
    from dopplergeist.data_access import FlightIndex

    if Path(dopplergeist.__file__).resolve().parent != args.source.resolve() / "dopplergeist":
        raise RuntimeError("Preparation imported a different source tree")
    if args.output.exists() or args.destination.exists():
        raise FileExistsError("Choose new preparation output and index paths")
    before = file_digest(args.index)
    began, cpu = time.perf_counter(), time.process_time()
    original = FlightIndex(args.index)
    prepared = original.prepare(args.destination)
    elapsed, cpu_seconds = time.perf_counter() - began, time.process_time() - cpu
    if before != file_digest(args.index):
        raise AssertionError("Preparation modified the original observed index")
    for key in ("input_hash", "coverage", "sources"):
        if original.report.get(key) != prepared.report.get(key):
            raise AssertionError(f"Preparation changed the original {key}")
    if not getattr(prepared, "_prepared_tracks", False):
        raise AssertionError("The optional representation is unavailable to its builder")
    report = {
        "wall_seconds": elapsed, "cpu_seconds": cpu_seconds,
        "source": str(args.source.resolve()), "index": str(args.index.resolve()),
        "destination": str(args.destination.resolve()),
        "input_hash": original.report["input_hash"],
        "original_unchanged": True,
        "source_bytes": args.index.stat().st_size,
        "prepared_bytes": args.destination.stat().st_size,
        "prepared_tracks": prepared.report["prepared_tracks"],
        "timing_scope": "One-time index copy, canonical decoding, optional representation and commit; excludes imports and verification.",
        "cache_scope": "Source integrity verification reads the original index before timing; operating-system file caches are not flushed.",
    }
    write_new(args.output, report)
    print(json.dumps(report), flush=True)


def compare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {"baseline": args.baseline_source.resolve(), "current": args.current_source.resolve()}
    fixture = json.loads(args.fixture.read_text())
    indexes = {"baseline": Path(args.baseline_index or fixture["real_index"]).resolve(),
               "current": Path(args.current_index or fixture["real_index"]).resolve()}
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[variable] = "1"
    runs, expected = [], None
    for repetition in range(args.repeats):
        order = ("baseline", "current") if repetition % 2 == 0 else ("current", "baseline")
        for name in order:
            output = args.output / f"{repetition + 1}-{name}"
            command = [sys.executable, str(Path(__file__).resolve()), "_worker",
                       "--source", str(sources[name]), "--fixture", str(args.fixture.resolve()),
                       "--index", str(indexes[name]), "--output", str(output.resolve()),
                       "--track-cache-bytes", str(args.track_cache_bytes)]
            for flag in ("stage_timing", "require_native", "require_native_acoustic"):
                if getattr(args, flag):
                    command.append("--" + flag.replace("_", "-"))
            if name == "current" and args.require_current_prepared:
                command.append("--require-prepared")
            print(f"Starting pair {repetition + 1}: {name}", flush=True)
            subprocess.run(command, check=True, env=environment, timeout=args.timeout_s)
            payload = canonical(json.loads((output / "results.json").read_text()))
            if expected is None:
                expected = payload
            elif payload != expected:
                raise AssertionError(f"Exact inventory, scientific-output or retention mismatch: {output}")
            summary = json.loads((output / "summary.json").read_text())
            runs.append({"source": name, "repetition": repetition + 1, **summary})
    medians = {name: {} for name in sources}
    for name in sources:
        for metric in ("wall_seconds", "cpu_seconds", "peak_rss_mib"):
            values = [row[metric] for row in runs if row["source"] == name and row[metric] is not None]
            medians[name][metric] = statistics.median(values) if values else None
    report = {
        "identical_results": True, "repeats": args.repeats,
        "fixture": str(args.fixture.resolve()),
        "sources": {name: str(path) for name, path in sources.items()},
        "indexes": {name: str(path) for name, path in indexes.items()},
        "medians": medians,
        "speedup": {metric: medians["baseline"][metric] / medians["current"][metric]
                    for metric in ("wall_seconds", "cpu_seconds")},
        "execution_stage_medians": {
            name: {stage: {metric: statistics.median(
                row["execution_stage_seconds"][stage][metric]
                for row in runs if row["source"] == name)
                for metric in ("wall_seconds", "cpu_seconds")}
                for stage in runs[0]["execution_stage_seconds"]}
            for name in sources},
        "scope": runs[0]["scope"], "timing_scope": runs[0]["timing_scope"],
        "cache_scope": "Fresh interpreter and FlightIndex per arm; operating-system file caches are not flushed.",
        "runs": runs,
    }
    if args.preparation_report:
        preparation = json.loads(args.preparation_report.read_text())
        if (Path(preparation["destination"]).resolve() != indexes["current"]
                or preparation["input_hash"] != fixture["index_input_hash"]):
            raise ValueError("Preparation report does not describe the compared current index")
        report["preparation"] = preparation
        report["preparation_amortization_scope"] = (
            "Preparation cost divided by the complete baseline/current query-and-score saving. "
            "This includes other code improvements and measures the combined upgrade, "
            "not the isolated prepared-format contribution.")
        report["queries_to_amortize_preparation"] = {}
        for metric in ("wall_seconds", "cpu_seconds"):
            saved = medians["baseline"][metric] - medians["current"][metric]
            report["queries_to_amortize_preparation"][metric] = (
                max(1, math.ceil(preparation[metric] / saved)) if saved > 0 else None)
    write_new(args.output / "comparison.json", report)
    print(json.dumps({key: report[key] for key in (
        "identical_results", "medians", "speedup", "execution_stage_medians", "scope")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare-index", help="Measure one-time creation of an optional index representation")
    preparation.add_argument("--source", type=Path, default=ROOT / "src")
    preparation.add_argument("--index", type=Path, required=True)
    preparation.add_argument("--destination", type=Path, required=True)
    preparation.add_argument("--output", type=Path, required=True)
    comparison = commands.add_parser("compare", help="Compare equal real query/sieve/scoring workloads")
    comparison.add_argument("--fixture", required=True, type=Path)
    comparison.add_argument("--baseline-source", required=True, type=Path)
    comparison.add_argument("--current-source", type=Path, default=ROOT / "src")
    comparison.add_argument("--baseline-index", type=Path)
    comparison.add_argument("--current-index", type=Path)
    comparison.add_argument("--preparation-report", type=Path)
    comparison.add_argument("--repeats", type=int, default=3)
    comparison.add_argument("--timeout-s", type=float, default=900.0)
    comparison.add_argument("--output", required=True, type=Path)
    comparison.add_argument("--require-current-prepared", action="store_true")
    internal = commands.add_parser("_worker", help=argparse.SUPPRESS)
    internal.add_argument("--source", required=True, type=Path)
    internal.add_argument("--fixture", required=True, type=Path)
    internal.add_argument("--index", type=Path)
    internal.add_argument("--output", required=True, type=Path)
    internal.add_argument("--require-prepared", action="store_true")
    for command in (comparison, internal):
        command.add_argument("--track-cache-bytes", type=int, default=32 * 1024 * 1024)
        command.add_argument("--stage-timing", action="store_true",
                             help="Collect inclusive call times in a separate diagnostic run")
        command.add_argument("--require-native", action="store_true",
                             help="Require successful native ridge fits in every compared source")
        command.add_argument("--require-native-acoustic", action="store_true",
                             help="Require successful native acoustic solves in every compared source")
        command.set_defaults(include_track_query=True)
    args = parser.parse_args()
    if hasattr(args, "track_cache_bytes") and args.track_cache_bytes < 0:
        parser.error("--track-cache-bytes must be nonnegative")
    if args.command == "prepare-index":
        prepare_index(args)
    elif args.command == "compare":
        if args.repeats < 1 or not math.isfinite(args.timeout_s) or args.timeout_s <= 0:
            parser.error("--repeats and --timeout-s must be positive")
        compare(args)
    else:
        worker(args)


if __name__ == "__main__":
    main()
