"""Compare complete point scoring on recorded ridges and historical trajectories.

The archived research candidate supplies workload coordinates and a clock, not
independent truth. Each source runs in a separate interpreter with bounded work
and identical observed inputs. This script generates no audio or trajectories.
"""
from __future__ import annotations

import argparse
from collections import Counter
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


def timing_instrumentation_active():
    """Observe profiling/debugging without installing or changing any hooks."""
    if sys.getprofile() is not None or sys.gettrace() is not None:
        return True
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is None:
        return False
    # Python 3.12 cProfile uses monitoring, leaving getprofile() unset. Count
    # reserved profiler/debugger slots even when events are temporarily paused
    # or enabled only for individual code objects, not globally.
    return any(monitoring.get_tool(tool_id) is not None
               for tool_id in (monitoring.PROFILER_ID, monitoring.DEBUGGER_ID))


def query_tracks(index, points, events, budget, scoring, bounds, time_range, *,
                 anchor_window=None, clock_partition_query=False):
    """Count actual index traversal while exercising the production overload path."""
    from dopplergeist import tiled_search

    requested_time_range = list(time_range)
    narrow_query = getattr(tiled_search, "_partition_query_time_range", None)
    if clock_partition_query and callable(narrow_query):
        time_range = narrow_query(time_range, events, scoring, {}, anchor_window)

    if "elev_m" not in points:
        raise ValueError("The recorded receiver hypothesis must include its elevation")
    operations = {"query_calls": 0, "decoded_track_yields": 0, "decoded_sample_yields": 0}
    inventory = {}

    class CountedIndex:
        def query(self, query_bounds, query_time):
            operations["query_calls"] += 1
            for track in index.query(query_bounds, query_time):
                operations["decoded_track_yields"] += 1
                operations["decoded_sample_yields"] += len(track.time)
                inventory[track.id] = len(track.time)
                yield track

    radius = max(event["slant_range_m"][1] for event in events)
    tracks, points = tiled_search._tracks_for_points(
        [CountedIndex()], bounds, time_range, budget, points, None, radius,
        scoring.get("c", 343.0))
    accounting = {
        "requested_time_range_s": requested_time_range,
        "effective_time_range_s": list(time_range),
        "clock_partition_time_narrowed": list(time_range) != requested_time_range,
        "queried_track_ids": sorted(inventory),
        "queried_trajectory_samples": sum(inventory.values()),
        "selected_track_ids": [track.id for track in tracks],
        "selected_trajectory_samples": sum(len(track.time) for track in tracks),
    }
    return tracks, points, operations, accounting


_PARTITION_WORK_COUNTS = {"cpa_rows", "per_event_survivors", "work_units", "unsupported_cpa_tracks"}


def partition_outcomes(payload):
    """Project only the explicitly allowed early-work diagnostics out of parity.

    Scored candidate payloads, rankings, trial evidence, support during scoring,
    retention records/bounds/stages, and all other counts remain exact checks.
    The removed fields receive separate monotonicity and time-exclusion checks.
    """
    return {key: ({name: value for name, value in item.items()
                  if name not in _PARTITION_WORK_COUNTS} if key == "counts" else item)
            for key, item in payload.items() if key != "track_query_accounting"}


def verify_partition_work(baseline, current):
    """Explain every permitted diagnostic change; reject unexplained omissions."""
    before, after = (payload["track_query_accounting"] for payload in (baseline, current))
    if before["requested_time_range_s"] != after["requested_time_range_s"]:
        raise AssertionError("Partition comparison changed the requested source interval")
    lower, upper = after["effective_time_range_s"]
    broad_lower, broad_upper = before["effective_time_range_s"]
    if not broad_lower <= lower <= upper <= broad_upper:
        raise AssertionError("Partition query did not conservatively narrow the original query")
    if not set(after["queried_track_ids"]) <= set(before["queried_track_ids"]):
        raise AssertionError("Partition query introduced unobserved source tracks")
    if after["queried_trajectory_samples"] > before["queried_trajectory_samples"]:
        raise AssertionError("Partition query increased source sample traversal")
    old_counts, new_counts = baseline["counts"], current["counts"]
    for field in ("cpa_rows", "work_units"):
        if new_counts.get(field, 0) > old_counts.get(field, 0):
            raise AssertionError(f"Partition unexpectedly increased {field}")
    old_survivors = old_counts.get("per_event_survivors", [])
    new_survivors = new_counts.get("per_event_survivors", [])
    if len(old_survivors) != len(new_survivors) or any(
            new > old for old, new in zip(old_survivors, new_survivors)):
        raise AssertionError("Partition unexpectedly changed event filtering")
    old_support = {canonical(item): item for item in old_counts.get("unsupported_cpa_tracks", [])}
    old_multiplicity = Counter(canonical(item) for item in old_counts.get("unsupported_cpa_tracks", []))
    new_multiplicity = Counter(canonical(item) for item in new_counts.get("unsupported_cpa_tracks", []))
    if not new_multiplicity <= old_multiplicity:
        raise AssertionError("Partition introduced or changed an unsupported-track report")
    removed = old_multiplicity - new_multiplicity
    for identity in removed:
        lo, hi = old_support[identity]["emission_time_range_s"]
        if lo <= upper and hi >= lower:
            raise AssertionError("Partition dropped an unsupported track touching the feasible emission interval")
    return {
        "requested_time_range_s": before["requested_time_range_s"],
        "effective_time_range_s": after["effective_time_range_s"],
        "excluded_unsupported_tracks_proved_outside_time_range": removed.total(),
        "baseline": {"queried_tracks": len(before["queried_track_ids"]),
                     "queried_samples": before["queried_trajectory_samples"],
                     "selected_tracks": len(before["selected_track_ids"]),
                     "cpa_rows": old_counts["cpa_rows"],
                     "unsupported_cpa_tracks": old_multiplicity.total(),
                     "association_work_units": old_counts.get("work_units")},
        "current": {"queried_tracks": len(after["queried_track_ids"]),
                    "queried_samples": after["queried_trajectory_samples"],
                    "selected_tracks": len(after["selected_track_ids"]),
                    "cpa_rows": new_counts["cpa_rows"],
                    "unsupported_cpa_tracks": new_multiplicity.total(),
                    "association_work_units": new_counts.get("work_units")},
    }


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
    points = pd.DataFrame([point])
    query_preparation = None
    if args.include_track_query:
        tracks, points, query_operations, query_accounting = query_tracks(
            index, points, events, budget, {"mode": "robust_ridge"}, query_bounds, query_time)
        samples = query_accounting["selected_trajectory_samples"]
        query_preparation = {
            "queried_trajectories": len(query_accounting["queried_track_ids"]),
            "queried_trajectory_samples": query_accounting["queried_trajectory_samples"],
            "operations": query_operations,
        }
    else:
        tracks, samples = [], 0
        for track in index.query(query_bounds, query_time):
            tracks.append(track)
            samples += len(track.time)
            if len(tracks) > args.max_tracks or samples > args.max_samples:
                raise ValueError("Declared trajectory budget exceeded; no input was silently truncated")
    if not tracks:
        raise ValueError("The declared real-data query returned no trajectories")
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
        "scope": ("Recorded-input computation comparison; source-informed receiver, no recording-clock prior or accuracy claim"
                  if args.full_day else
                  "Recorded-input computation comparison; source-informed receiver/clock, no accuracy claim"),
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
    if args.anchor_window_s is not None:
        fixture["anchor_window_s"] = args.anchor_window_s
        fixture["scope"] += ". One association-anchor partition. Physical fit intervals remain unchanged."
    if query_preparation is not None:
        fixture["track_query_preparation"] = query_preparation
    write_new(args.output, fixture)
    print(json.dumps({"fixture": str(args.output), **fixture["counts"],
                      "scope": fixture["scope"],
                      **({"track_query_preparation": query_preparation}
                         if query_preparation is not None else {})}), flush=True)


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
    native_module = getattr(matching, "_native_ridge_module", None)
    native_statistics = getattr(native_module, "fit_statistics", None)
    ridge_backend = getattr(matching, "RIDGE_FIT_BACKEND", "python-irls-v1")
    acoustic_backend = getattr(geometry, "ACOUSTIC_BACKEND", "python-acoustic-v1")
    try:
        from dopplergeist.native_acoustic import _native as native_acoustic
    except ImportError:
        native_acoustic = None
    try:
        from dopplergeist.native_cpa import _native as native_cpa
    except ImportError:
        native_cpa = None
    if args.require_native and not callable(native_fit):
        raise RuntimeError("The selected source's native ridge fitter is unavailable")
    if args.require_native_acoustic and native_acoustic is None:
        raise RuntimeError("The selected source's native acoustic solver is unavailable")
    if args.require_native_cpa and native_cpa is None:
        raise RuntimeError("The selected source's native CPA reducer is unavailable")
    fixture = json.loads(args.fixture.read_text())
    index = FlightIndex(args.index or fixture["real_index"])
    if index.report["input_hash"] != fixture["index_input_hash"]:
        raise ValueError("The real trajectory index no longer matches the fixture")
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
                  "native_acoustic_successes": 0}
    all_rows = []
    original_fit, original_acoustic = matching._fit_ridge_uncached, Track.acoustic
    original_score = tiled_search.score_candidate
    phase_seconds, phase_patches = {}, []

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

    if args.instrument_numerics:
        matching._fit_ridge_uncached, Track.acoustic = counted_fit, counted_acoustic
    else:
        for name in ("scalar_fit_calls", "acoustic_calls", "native_fit_calls", "native_fit_successes"):
            operations[name] = None
    tiled_search.score_candidate = captured_score
    native_before = native_statistics() if callable(native_statistics) else None
    if args.instrument_numerics and callable(native_fit) and native_before is None:
        matching._native_fit_irls = counted_native
    native_acoustic_before = native_acoustic.successful_calls() if native_acoustic is not None else 0
    native_cpa_before = native_cpa.successful_calls() if native_cpa is not None else 0
    query_accounting, query_operations, execution_stages = None, None, {}
    diagnostic = args.instrument_numerics or args.stage_timing or timing_instrumentation_active()
    began, cpu = time.perf_counter(), time.process_time()
    try:
        if args.include_track_query:
            query_began, query_cpu = time.perf_counter(), time.process_time()
            tracks, points, query_operations, query_accounting = query_tracks(
                index, points, events, budget, fixture["scoring"],
                fixture["query_bounds"], fixture["query_time_s"],
                anchor_window=fixture.get("anchor_window_s"),
                clock_partition_query=args.clock_partition_query)
            execution_stages["track_query_and_distance_sieve"] = {
                "wall_seconds": time.perf_counter() - query_began,
                "cpu_seconds": time.process_time() - query_cpu,
            }
            if not query_accounting["clock_partition_time_narrowed"]:
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
        diagnostic = diagnostic or timing_instrumentation_active()
        matching._fit_ridge_uncached, Track.acoustic = original_fit, original_acoustic
        tiled_search.score_candidate = original_score
        if callable(native_fit):
            matching._native_fit_irls = native_fit
        if native_before is not None:
            native_after = native_statistics()
            delta = {key: native_after[key] - native_before[key] for key in native_before}
            operations["native_fit_calls"] = delta["scalar_calls"] + delta["batch_rows"]
            operations["native_fit_successes"] = delta["scalar_successes"] + delta["batch_successful_rows"]
            operations["native_batch_calls"] = delta["batch_calls"]
            operations["native_batch_rows"] = delta["batch_rows"]
        if native_acoustic is not None:
            operations["native_acoustic_successes"] = native_acoustic.successful_calls() - native_acoustic_before
        if native_cpa is not None:
            operations["native_cpa_successes"] = native_cpa.successful_calls() - native_cpa_before
        for owner, attribute, function in reversed(phase_patches):
            setattr(owner, attribute, function)
    expected_counts = fixture.get("expected_counts")
    if expected_counts is not None:
        actual_counts = {"cpa_rows": counts["cpa_rows"],
                         "associations": counts["candidates"], "retained": len(ranked)}
        changed_work_only = (args.clock_partition_query
            and actual_counts["cpa_rows"] <= expected_counts["cpa_rows"]
            and all(actual_counts[key] == expected_counts[key] for key in ("associations", "retained")))
        if actual_counts != expected_counts and not changed_work_only:
            raise AssertionError(f"Recorded workload counts changed: {actual_counts}")
    # Linux ru_maxrss can include the comparison parent's high-water mark
    # inherited across fork/exec. VmHWM belongs to this worker's address space.
    # Keep unknown platforms usable without guessing a memory unit or scope.
    peak_rss_mib = None
    peak_rss_method = "Unavailable on this platform"
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/self/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    fields = line.split()
                    if len(fields) == 3 and fields[2] == "kB":
                        peak_rss_mib = int(fields[1]) / 1024
                        peak_rss_method = "/proc/self/status VmHWM after exec"
                    break
        except (OSError, ValueError):
            pass
    elif resource is not None and sys.platform == "darwin":
        peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
        peak_rss_method = "resource.getrusage(RUSAGE_SELF).ru_maxrss"
    checksum = ledger.checksum(stage)
    if not ledger.stage_valid(stage, checksum):
        raise AssertionError("The scoring pass produced an invalid retention ledger")
    if not operations["scored_candidates"]:
        raise AssertionError("The benchmark did not score any real associations")
    if (args.require_native and (args.instrument_numerics or native_before is not None)
            and not operations["native_fit_successes"]):
        raise AssertionError("No successful native ridge fit occurred inside the timed scoring call")
    if args.require_native_acoustic and not operations["native_acoustic_successes"]:
        raise AssertionError("No successful native acoustic solve occurred inside the timed scoring call")
    if args.require_native_cpa and not operations.get("native_cpa_successes"):
        raise AssertionError("No successful native CPA reduction occurred inside the timed scoring call")
    with ledger.connect() as database:
        retention = {name: database.execute(f"SELECT * FROM {name} ORDER BY 1,2").fetchall()
                     for name in ("records", "bounds", "stages")}
    results = {"ranked": ranked, "counts": counts,
               "all_scored_candidates": all_rows, "retention": retention}
    if query_accounting is not None:
        results["track_query_accounting"] = query_accounting
    write_new(args.output / "results.json", results)
    summary = {"wall_seconds": elapsed, "cpu_seconds": cpu_seconds,
               "load_seconds_excluded": load_seconds, "operations": operations,
               "numerical_functions_canonical": not (args.instrument_numerics or args.stage_timing),
               "performance_timing_eligible": not diagnostic,
               "ridge_execution_check": ("In-module successful-call counters" if native_before is not None else
                    "Wrapped successful-call counters" if args.instrument_numerics else
                    "Backend availability; successful-call count unmeasured"),
               "ridge_fit_backend": ridge_backend, "acoustic_backend": acoustic_backend,
               "native_extension_available": callable(native_fit),
               "peak_rss_mib": peak_rss_mib,
               "peak_rss_measurement": peak_rss_method,
               "peak_rss_scope": ("Worker lifetime through scoring, including imports and input loading"
                                  if peak_rss_mib is not None else "Unavailable on this platform"),
               "retained": len(ranked), "independent_groups": len(events), "scope": fixture["scope"]}
    if "anchor_window_s" in fixture:
        summary["anchor_window_s"] = fixture["anchor_window_s"]
    if args.include_track_query:
        summary["track_query_operations"] = query_operations
        summary["clock_partition_time_narrowed"] = query_accounting["clock_partition_time_narrowed"]
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


def compare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    sources = {"baseline": args.baseline_source.resolve(), "current": args.current_source.resolve()}
    environment = dict(os.environ)
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        environment[variable] = "1"
    runs, expected, source_payloads, source_canonical = [], None, {}, {}
    for repetition in range(args.repeats):
        order = ("baseline", "current") if repetition % 2 == 0 else ("current", "baseline")
        for name in order:
            output = args.output / f"{repetition + 1}-{name}"
            command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--source", str(sources[name]),
                       "--fixture", str(args.fixture.resolve()), "--output", str(output.resolve())]
            if args.index:
                command.extend(["--index", str(args.index.resolve())])
            if args.stage_timing:
                command.append("--stage-timing")
            if args.include_track_query:
                command.append("--include-track-query")
            if args.clock_partition_query:
                command.append("--clock-partition-query")
            if args.instrument_numerics:
                command.append("--instrument-numerics")
            if name == "current" and args.require_current_native:
                command.append("--require-native")
            if name == "current" and args.require_current_native_acoustic:
                command.append("--require-native-acoustic")
            if name == "current" and args.require_current_native_cpa:
                command.append("--require-native-cpa")
            subprocess.run(command, check=True, env=environment, timeout=args.timeout_s)
            result = json.loads((output / "results.json").read_text())
            complete = canonical(result)
            if name in source_canonical and source_canonical[name] != complete:
                raise AssertionError(f"Repeated source output was not deterministic: {output}")
            source_canonical[name] = complete
            source_payloads[name] = result
            payload = canonical(partition_outcomes(result) if args.clock_partition_query else result)
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
    report = {"identical_results": source_canonical["baseline"] == source_canonical["current"],
              "identical_scored_candidates_rankings_and_retention": True, "repeats": args.repeats,
              "fixture": str(args.fixture.resolve()),
              "sources": {name: str(path) for name, path in sources.items()}, "medians": medians,
              "speedup": {metric: medians["baseline"][metric] / medians["current"][metric]
                          for metric in ("wall_seconds", "cpu_seconds")},
              "scope": runs[0]["scope"], "runs": runs}
    if args.clock_partition_query:
        report["clock_partition_query_verification"] = verify_partition_work(
            source_payloads["baseline"], source_payloads["current"])
        report["equality_scope"] = (
            "Exact scored candidate payloads, rankings, trial/support evidence and retention records. "
            "Early query/CPA/event/work counts may decrease; every removed unsupported track's "
            "complete emission interval must miss the proved partition interval.")
    report["performance_timing_eligible"] = all(row["performance_timing_eligible"] for row in runs)
    if not report["performance_timing_eligible"]:
        report["diagnostic_ratio"] = report["speedup"]
        report["speedup"] = None
    if args.include_track_query:
        report["timing_scope"] = runs[0]["timing_scope"]
        report["track_query_included"] = True
        report["execution_stage_medians"] = {
            name: {stage: {metric: statistics.median(
                row["execution_stage_seconds"][stage][metric]
                for row in runs if row["source"] == name)
                for metric in ("wall_seconds", "cpu_seconds")}
                for stage in runs[0]["execution_stage_seconds"]}
            for name in sources}
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
    preparation.add_argument("--anchor-window-s", nargs=2, type=float, metavar=("LOW", "HIGH"),
                             help="Optional half-open association ownership partition; physical fit windows remain unchanged")
    preparation.add_argument("--include-track-query", action="store_true",
                             help="Prepare the production query/sieve workload; budgets bound retained tracks, including overloaded queries")
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
    comparison.add_argument("--stage-timing", action="store_true",
                            help="Collect inclusive phase times in a separate diagnostic run")
    comparison.add_argument("--include-track-query", action="store_true",
                            help="Include initial index traversal and the production overload sieve in each timed worker")
    comparison.add_argument("--clock-partition-query", action="store_true",
                            help="Exercise the production clock-partition query bound where available; verify exact outcomes and explain reduced work")
    comparison.add_argument("--instrument-numerics", action="store_true",
                            help="Diagnostic only: wrap numerical calls for counters; changes execution overhead")
    comparison.add_argument("--require-current-native", action="store_true",
                            help="Require successful native ridge fits inside each current scoring run")
    comparison.add_argument("--require-current-native-acoustic", action="store_true",
                            help="Require successful native acoustic solves inside each current scoring run")
    comparison.add_argument("--require-current-native-cpa", action="store_true",
                            help="Require successful native CPA reductions inside each current scoring run")
    internal = commands.add_parser("_worker", help=argparse.SUPPRESS)
    internal.add_argument("--source", required=True, type=Path)
    internal.add_argument("--fixture", required=True, type=Path)
    internal.add_argument("--index", type=Path)
    internal.add_argument("--output", required=True, type=Path)
    internal.add_argument("--stage-timing", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--instrument-numerics", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--include-track-query", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--clock-partition-query", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--require-native", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--require-native-acoustic", action="store_true", help=argparse.SUPPRESS)
    internal.add_argument("--require-native-cpa", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.command == "prepare":
        if args.clock_half_width_s < 0:
            parser.error("--clock-half-width-s must be nonnegative")
        if (args.anchor_window_s is not None
                and (not all(math.isfinite(value) for value in args.anchor_window_s)
                     or args.anchor_window_s[0] >= args.anchor_window_s[1])):
            parser.error("--anchor-window-s requires finite increasing endpoints")
        sys.path.insert(0, str(ROOT / "src"))
        prepare(args)
    elif args.command == "compare":
        if args.repeats < 1 or args.timeout_s <= 0:
            parser.error("--repeats and --timeout-s must be positive")
        if args.clock_partition_query:
            fixture = json.loads(args.fixture.read_text())
            if not args.include_track_query or "anchor_window_s" not in fixture:
                parser.error("--clock-partition-query requires --include-track-query and a recorded anchor partition")
        compare(args)
    else:
        worker(args)


if __name__ == "__main__":
    main()
