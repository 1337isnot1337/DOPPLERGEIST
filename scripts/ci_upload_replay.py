#!/usr/bin/env python3
"""Run the published browser verifier, then evaluate a complete synthetic case.

HTTP/browser code stays in PR33's verifier. Only its service shutdown signal is
adapted to graceful SIGINT. Transport/UI and supported localization are separate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import secrets
import shutil
import signal
from statistics import median
import subprocess
import sys
from types import SimpleNamespace
import time


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPERS = load_module(Path(__file__).with_name("ci_checkpoint_replay.py"), "upload_replay_helpers")
read_json, write_json = HELPERS.read_json, HELPERS.write_json
file_record, utc_now = HELPERS.file_record, HELPERS.utc_now
TERMINAL = {"succeeded", "inconclusive", "failed", "needs_input", "cancelled"}
SCOPE = [-125.0, 24.0, -66.0, 50.0]
THRESHOLDS_M = (100, 500, 1000)
PRIMARY_THRESHOLD_M = 1000
TIME_SOURCE = "Known sample-zero clock of the published independent synthetic generator"
# The reviewed service catches SIGINT and finally calls manager.close(), which
# joins its analysis-management threads. Changed lifecycle code needs review.
AUDITED_BLOBS = {
    "scripts/verify_methodology.py": "bc349e9005bd9e14d980c857486f6927a641112d",
    "scripts/verify_upload_browser.py": "17f0bbef5fa8abf86fb9ae85cf662600c32cc104",
    "scripts/make_multi_event_case.py": "48c809ac701919da3f209f67ccc5cf66d090463e",
    "scripts/ci_checkpoint_replay.py": "1612021776965713e88c586563ab51d4b8682a8b",
    "src/aircraft_geoloc/service.py": "67b541805cb6ae14d56b5d4f03fcf7c2f84574fe",
    "src/aircraft_geoloc/jobs.py": "29e8aa37ff1b82daecdae45af908272e960755ab",
}
REQUIRED_ARTIFACTS = (
    "input.json", "request.json", "operator.json", "provenance.json", "worker.log",
    "intake/recording.json", "discovery/discovery.json", "data-provenance.json",
    "search/search-report.json", "refined-candidates.json", "decision.json", "result.json",
)
REQUIRED_CHECKS = {
    "evidence_collection_complete", "all_stage_artifacts_present", "job_identity_matches",
    "normal_request_verified", "uploaded_bytes_verified", "operator_verified", "implementation_verified",
    "decision_consistent", "search_consistent", "alternative_evidence_consistent",
    "all_discovered_events_retained", "leading_refinement_row_bound", "nominal_joint_fit_recorded",
    "all_event_groups_considered",
}


def git_blob(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def snapshot_sources(repo, output):
    for name, expected in AUDITED_BLOBS.items():
        if git_blob(repo / name) != expected:
            raise RuntimeError(f"Reviewed source changed: {name}; review before execution")
    snapshot, record = HELPERS.code_snapshot(repo, output)
    scripts = snapshot / "scripts"
    scripts.mkdir()
    for name in ("ci_upload_replay.py", "ci_checkpoint_replay.py", "verify_methodology.py",
                 "verify_upload_browser.py", "make_multi_event_case.py"):
        shutil.copy2(repo / "scripts" / name, scripts / name)
    files, combined = {}, hashlib.sha256()
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            relative = path.relative_to(snapshot).as_posix()
            files[relative] = file_record(path)
            combined.update(relative.encode() + b"\0" + files[relative]["sha256"].encode() + b"\0")
    record.update(files=files, snapshot_sha256=combined.hexdigest(), audited_git_blobs=AUDITED_BLOBS,
                  expected_implementation_files={p.name: file_record(p)["sha256"]
                      for p in sorted((snapshot / "src/aircraft_geoloc").glob("*.py"))})
    return snapshot, record


def normal_wire_request(value):
    if set(value) != {"schema_version", "audio_path", "time_window", "search"}:
        raise ValueError("Generated request contains unexpected fields")
    if value["schema_version"] != 1 or value["search"] != {"coverage": "conus"}:
        raise ValueError("Expected the declared CONUS request")
    window = value["time_window"]
    if set(window) != {"start_utc", "end_utc", "source"} or window["source"] != "user":
        raise ValueError("Unexpected recording clock fields")
    if window["start_utc"] != window["end_utc"]:
        raise ValueError("This fixture declares one known sample-zero clock")
    return {"schema_version": 1, "search": {"coverage": "conus"},
            "time_window": dict(window, source_detail=TIME_SOURCE)}


def index_fixture(inputs, evaluation, index_path, report_path, event_count):
    """No truth is read. Preserve all trajectory values except opaque ID/order."""
    import pandas as pd
    from aircraft_geoloc.data_access import FlightIndex

    source = evaluation / "original-tracks.parquet"
    if source.exists():
        raise ValueError("Refusing to overwrite original trajectory evidence")
    (inputs / "tracks.parquet").replace(source)
    frame = pd.read_parquet(source)
    counts = frame.groupby("flight_id", dropna=False).size()
    if len(counts) != 3 * event_count or not (counts == 271).all():
        raise ValueError("Complete generated traffic inventory was not retained")
    expected_types = {name: 813 for name in ["C172", "PC12", "A320", "", "C208", "B350"][:event_count]}
    types = dict(Counter(frame["typecode"].fillna("").astype(str)))
    if types != expected_types or not (frame["altitude_basis"] == "ellipsoidal").all():
        raise ValueError("Aircraft classes or altitude basis differ from the fixture")
    identities = [str(value) for value in counts.index]
    mapping = {old: secrets.token_hex(16) for old in identities}
    if len(set(mapping.values())) != len(mapping):
        raise RuntimeError("Opaque trajectory ID collision")
    order = list(identities)
    secrets.SystemRandom().shuffle(order)
    blocks = []
    for old in order:
        original = frame.loc[frame["flight_id"].astype(str) == old].copy()
        changed = original.copy()
        changed["flight_id"] = mapping[old]
        if not original.drop(columns="flight_id").equals(changed.drop(columns="flight_id")):
            raise ValueError("Trajectory values changed during anonymization")
        blocks.append(changed)
    blinded = pd.concat(blocks, ignore_index=True)
    target = inputs / "tracks.parquet"
    blinded.to_parquet(target, index=False)
    if not blinded.equals(pd.read_parquet(target)):
        raise ValueError("Derived Parquet changed column values")
    write_json(evaluation / "flight-id-mapping.json", {"original_to_opaque": mapping,
               "order_randomized": True, "all_non_id_values_preserved": True})
    coverage = read_json(inputs / "coverage.json")
    if (coverage.get("source_kind") != "complete_finite_synthetic_population"
            or coverage.get("all_aircraft") is not True or coverage.get("real_receiver_coverage") is not False):
        raise ValueError("Coverage must describe only the complete finite synthetic population")
    indexed_coverage = dict(coverage, synthetic=True)
    index = FlightIndex.from_parquet(index_path, target, coverage=indexed_coverage)
    returned = {track.id: len(track.time) for track in index.query(SCOPE, coverage["time_range_s"])}
    expected = {mapping[old]: int(counts[old]) for old in identities}
    report = index.report() if callable(index.report) else index.report
    if (report.get("index_version") != 2 or returned != expected
            or report.get("rows") != len(frame) or report.get("segments") != len(expected)
            or report.get("invalid_rows") != 0 or report.get("jets_excluded") is not False
            or report.get("unknown_types_retained") is not True or report.get("geometry_clipped") is not False):
        raise ValueError("Indexed/query traffic differs from the complete source inventory")
    write_json(report_path, {"rows": len(frame), "tracks": len(expected), "rows_per_track": returned,
        "typecode_rows": types, "all_non_id_values_preserved": True, "all_rows_retained": True,
        "original_parquet": file_record(source), "derived_parquet": file_record(target),
        "indexed_coverage": indexed_coverage, "index_report": report})


class ManagedServer:
    """Lifecycle-only adapter; HTTP, browser requests and science are unchanged."""
    def __init__(self, process, record, save):
        self.process, self.record, self.save = process, record, save

    def __getattr__(self, name):
        return getattr(self.process, name)

    def terminate(self):
        self.record.update(shutdown_signal="SIGINT", shutdown_requested_utc=utc_now())
        self.save()
        self.process.send_signal(signal.SIGINT)

    def kill(self):
        self.record["forced_kill"] = True
        self.save()
        self.process.kill()

    def wait(self, timeout=None):
        code = self.process.wait(timeout=timeout)
        self.record.update(returncode=code, stopped_utc=utc_now())
        self.save()
        return code


class VerifierSubprocess:
    """Proxy only the published verifier's server Popen, not subprocess globally."""
    def __init__(self, record_path):
        self.path, self.records = record_path, []

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def save(self):
        write_json(self.path, {"adapter": "service SIGTERM request replaced by SIGINT only",
            "scientific_stages_replaced": False, "servers": self.records})

    def Popen(self, command, **kwargs):
        if list(command)[1:4] != ["-m", "aircraft_geoloc.cli", "serve"]:
            raise ValueError("Unreviewed verifier Popen command")
        process = subprocess.Popen(command, **kwargs)
        record = {"pid": process.pid, "command": list(map(str, command)),
                  "started_utc": utc_now(), "forced_kill": False, "returncode": None}
        self.records.append(record)
        self.save()
        return ManagedServer(process, record, self.save)


def run_published_verifier(args):
    verifier = load_module(Path(__file__).with_name("verify_methodology.py"), "published_upload_verifier")
    wire = read_json(args.request)
    proxy = VerifierSubprocess(args.lifecycle)
    verifier.subprocess = proxy
    proxy.save()
    arguments = SimpleNamespace(audio=args.audio, output=args.output, operator_config=args.operator,
        start_utc=wire["time_window"]["start_utc"], end_utc=wire["time_window"]["end_utc"],
        time_source=TIME_SOURCE, via=["browser"], browser_python=args.browser_python,
        timeout=args.timeout_s, expect_status=args.expect_status, expect_reason=None)
    try:
        return verifier.product_audit(arguments)
    finally:
        proxy.save()


def ready_for_truth(result, execution, lifecycle):
    servers = lifecycle.get("servers", [])
    return (not execution.get("timed_out") and result.get("status") in TERMINAL
        and len(servers) == 1 and servers[0].get("shutdown_signal") == "SIGINT"
        and servers[0].get("returncode") == 0 and servers[0].get("forced_kill") is False
        and bool(servers[0].get("stopped_utc")))


def search_matches_result(search, coverage, provenance):
    total, completed = search.get("tiles_total"), search.get("tiles_completed")
    counts_ok = (type(total) is int and type(completed) is int and total > 0
                 and 0 <= completed <= total and search.get("unsearched_tiles") == total - completed)
    work_complete = bool(counts_ok and completed == total and not search.get("tile_failures")
                         and not search.get("refinement_failure"))
    data_complete = search.get("data_scope_complete") is True
    all_events = search.get("all_event_groups_considered", True) is True
    return (counts_ok and type(search.get("data_scope_complete")) is bool
        and search.get("status") == ("complete" if work_complete and data_complete and all_events else "partial")
        and search.get("scope") == SCOPE and coverage.get("search_complete") is work_complete
        and coverage.get("data_status") == ("available" if data_complete else "partial")
        and bool(search.get("run_hash")) and provenance.get("search_run_hash") == search.get("run_hash"))


def prepared_group_order(events):
    """Reconstruct only W3's metadata ordering, without fitting/scoring ridges."""
    groups = {}
    for event in events:
        groups.setdefault(event.get("harmonic_group_id") or event["event_id"], []).append(event)
    centers = {}
    for identity, members in groups.items():
        reference = min(members, key=lambda event: median(point["frequency_hz"] for point in event["ridge"]))
        start, end = min(event["start_s"] for event in members), max(event["end_s"] for event in members)
        center = float(reference.get("cpa_receive_s", (start + end) / 2))
        if not math.isfinite(center):
            raise ValueError("Nonfinite group center")
        centers[identity] = center
    if len(set(centers.values())) != len(centers):
        raise ValueError("Tied group centers do not establish an unambiguous recorded index order")
    return sorted(centers, key=centers.get), centers


def reported_fit_profile(result, refined):
    """Inspect recorded participation; never recompute a score or profile."""
    report = {"leading_row_bound": False, "nominal_diagnostics_complete": False,
        "empirical_leave_one_out_effect_tested": False,
        "scope": "Recorded joint-fit and declared perturbation participation, not calibrated sensitivity or empirical causal contribution."}
    rows, candidates = refined.get("ranked", []), result.get("candidates", [])
    if not rows or not candidates:
        report["unresolved"] = "No leading internal row and returned candidate"
        return report
    row, candidate = rows[0], candidates[0]
    groups = {}
    for event in result.get("events", []):
        groups.setdefault(event.get("harmonic_group_id") or event["event_id"], []).append(event["event_id"])
    try:
        ordered, centers = prepared_group_order(result.get("events", []))
        report["prepared_group_centers_s"] = centers
    except (ValueError, KeyError, TypeError) as exc:
        report["unresolved"] = f"Prepared-group ordering: {exc}"
        return report
    indices = row.get("event_indices", list(range(len(ordered))))
    flights = row.get("flight_ids", [])
    index_ok = (isinstance(indices, list) and len(indices) == len(flights) and len(set(indices)) == len(indices)
                and all(type(index) is int and 0 <= index < len(ordered) for index in indices))
    report["selected_event_indices"] = indices
    report["nominal_event_diagnostics"] = row.get("event_diagnostics", [])
    if not index_ok:
        report["unresolved"] = "Internal selected indices/flight mapping are invalid"
        return report
    expected_ids, expected_flights = [], []
    for index, flight in zip(indices, flights):
        members = groups[ordered[index]]
        expected_ids.extend(members)
        expected_flights.extend([flight] * len(members))
    try:
        internal_clock = datetime.fromtimestamp(row["recording_start_time_s"], timezone.utc)
        public_clock = datetime.fromisoformat(candidate["recording_start_utc"].replace("Z", "+00:00"))
        report["leading_row_bound"] = (all(type(row.get(key)) in (int, float) and math.isfinite(row[key])
            and row[key] == candidate.get(key) for key in ("lat", "lon", "score"))
            and internal_clock == public_clock and candidate.get("event_ids") == expected_ids
            and candidate.get("flight_ids") == expected_flights)
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    nominal_participation(report, row, refined.get("matching_diagnostics", {}), groups, ordered, indices)
    profile_participation(report, row.get("sensitivity", {}), indices, flights)
    return report


def nominal_participation(report, row, exported, groups, ordered, indices):
    diagnostics = row.get("event_diagnostics", [])
    fields = ("score", "rmse_hz", "sample_count", "independent_sample_count", "support_fraction")
    checks = []
    for index, evidence in zip(indices, diagnostics):
        finite = all(type(evidence.get(key)) in (int, float) and math.isfinite(evidence[key]) for key in fields)
        valid = (finite and evidence["sample_count"] > 0 and evidence["independent_sample_count"] > 0
                 and evidence["rmse_hz"] >= 0 and 0 < evidence["support_fraction"] <= 1)
        members = groups[ordered[index]]
        exported_matches = all(member in exported and all(exported[member].get(key) == evidence.get(key)
                                for key in fields) for member in members)
        checks.append({"event_index": index, "group_id": ordered[index], "event_ids": members,
                       "positive_finite_residual_evidence": valid, "exported_diagnostics_match": exported_matches})
    report["nominal_group_checks"] = checks
    report["nominal_diagnostics_complete"] = (bool(indices) and len(diagnostics) == len(indices)
        and all(check["positive_finite_residual_evidence"] and check["exported_diagnostics_match"] for check in checks))


def profile_participation(report, sensitivity, indices, flights):
    profiles, settings = sensitivity.get("profiles", []), sensitivity.get("settings", {})
    frequency = []
    for index in indices:
        expected = [f"event_{index}_{pattern}_{sign:+d}" for pattern in ("offset", "tilt") for sign in (-1, 1)]
        present = {name: [p.get("optimizer_success") for p in profiles
                         if p.get("source") == "frequency" and p.get("scenario") == name] for name in expected}
        frequency.append({"event_index": index, "scenarios": present,
                          "all_declared_scenarios_recorded": all(present.values())})
    altitude, uncertainty = [], settings.get("altitude_uncertainty_m")
    for flight in sorted(set(flights)):
        biases = [p["flight_altitude_bias"]["bias_m"] for p in profiles
            if p.get("source") == "altitude" and isinstance(p.get("flight_altitude_bias"), dict)
            and p["flight_altitude_bias"].get("flight_id") == flight and "bias_m" in p["flight_altitude_bias"]]
        both = (type(uncertainty) in (int, float) and math.isfinite(uncertainty)
                and -uncertainty in biases and uncertainty in biases)
        altitude.append({"flight_id": flight, "recorded_bias_m": biases, "both_declared_signs_recorded": both})
    scales = settings.get("frequency_scale_hz", [])
    report["reported_profile_participation"] = {"settings": settings,
        "frequency_scale_count_matches_selected": isinstance(scales, list) and len(scales) == len(indices),
        "frequency_by_event": frequency, "altitude_by_flight": altitude,
        "producer_complete": sensitivity.get("complete"), "producer_boundary_limited": sensitivity.get("boundary_limited"),
        "producer_failures": sensitivity.get("failures", []),
        "used_as_additional_uncertainty_acceptance_policy": False}


def collect_job(product, audio, operator, wire, expected_sources):
    paths = list((product / "http-jobs").glob("*/result.json"))
    if len(paths) != 1:
        raise ValueError(f"Expected one actual browser-submitted result, found {len(paths)}")
    directory = paths[0].parent
    result = read_json(paths[0])
    checks, errors, discovery_settings, participation = {"evidence_collection_complete": False}, [], {}, {}
    checks["all_stage_artifacts_present"] = all((directory / name).is_file() for name in REQUIRED_ARTIFACTS)
    try:
        uploaded = directory / "input.mp3"
        checks["job_identity_matches"] = result.get("job_id") == directory.name
        checks["normal_request_verified"] = read_json(directory / "request.json") == dict(wire, audio_path=str(uploaded))
        checks["uploaded_bytes_verified"] = (file_record(uploaded)["sha256"] == file_record(audio)["sha256"]
            == result.get("recording", {}).get("source_sha256"))
        checks["operator_verified"] = read_json(directory / "operator.json") == operator
        provenance = read_json(directory / "provenance.json")
        checks["implementation_verified"] = provenance.get("implementation_files") == expected_sources
        decision = read_json(directory / "decision.json")
        checks["decision_consistent"] = ("status" in decision and "candidates" in decision
            and all(decision.get(key) == result.get(key) for key in ("status", "reason_code", "message", "candidates")))
        search = read_json(directory / "search/search-report.json")
        checks["search_consistent"] = search_matches_result(search, result.get("coverage", {}), provenance)
        checks["all_event_groups_considered"] = search.get("all_event_groups_considered", True) is True
        checks["alternative_evidence_consistent"] = (result.get("status") != "succeeded"
            or search.get("alternative_modes_exhaustively_assessed") is True)
        discovery = read_json(directory / "discovery/discovery.json")
        discovery_settings = discovery.get("settings", {})
        expected_events = [event["event_id"] for event in discovery["events"]]
        actual_events = [event["event_id"] for event in result.get("events", [])]
        checks["all_discovered_events_retained"] = (len(set(expected_events)) == len(expected_events)
            and sorted(expected_events) == sorted(actual_events)
            and sorted(discovery["events"], key=lambda event: event["event_id"])
                == sorted(result.get("events", []), key=lambda event: event["event_id"]))
        participation = reported_fit_profile(result, read_json(directory / "refined-candidates.json"))
        checks["leading_refinement_row_bound"] = participation["leading_row_bound"]
        checks["nominal_joint_fit_recorded"] = participation["nominal_diagnostics_complete"]
        checks["evidence_collection_complete"] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    return result, {"directory": str(directory), "checks": checks, "errors": errors,
        "result_file": file_record(paths[0]), "status": result.get("status"),
        "reason_code": result.get("reason_code"), "events": result.get("events", []),
        "candidate_count": len(result.get("candidates", [])), "coverage": result.get("coverage"),
        "recording": result.get("recording"),
        "discovery_settings": discovery_settings, "reported_fit_profile": participation}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-python", required=True, type=Path)
    parser.add_argument("--expect-status", required=True, choices=sorted(TERMINAL))
    parser.add_argument("--events", type=int, choices=(3, 4, 6), default=4)
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--timeout-s", type=float, default=1800)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout_s) or args.timeout_s <= 60:
        parser.error("--timeout-s must be finite and greater than 60")
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error(f"Refusing to overwrite existing output: {args.output}")
    repo = Path(__file__).resolve().parents[1]
    if args.output.is_relative_to(repo / "src"):
        parser.error("Output must be outside src")
    return replay(args, repo)


def matched_groups(result, candidate):
    events = result.get("events", [])
    lookup = {event.get("event_id"): event for event in events}
    used, flights = candidate.get("event_ids", []), candidate.get("flight_ids", [])
    valid = (bool(used) and len(lookup) == len(events) and len(set(used)) == len(used)
        and len(used) == len(flights) and all(key is not None and key in lookup for key in used))
    group_flights = {}
    if valid:
        for key, flight in zip(used, flights):
            group = lookup[key].get("harmonic_group_id") or key
            if group in group_flights and group_flights[group] != flight:
                valid = False
            group_flights[group] = flight
    return {"valid": valid, "independent_groups": len(group_flights), "group_flights": group_flights}


def association_timing(result, candidate, labels, mapping, tolerance_s):
    """Post-search check only; label windows never enter the upload request."""
    record = {"compatible": False, "groups": [], "edge_tolerance_s": tolerance_s,
        "rule": "At least 90% of unique used ridge times inside the mapped true arrival interval; no other true interval has 90% support. Minimum three ridge times per group."}
    if not isinstance(tolerance_s, (int, float)) or not math.isfinite(tolerance_s) or tolerance_s <= 0:
        record["unresolved"] = "Actual discovery window_s was unavailable"
        return record
    grouping = matched_groups(result, candidate)
    if not grouping["valid"]:
        record["unresolved"] = "Invalid or inconsistent event/group ownership"
        return record
    lookup = {event["event_id"]: event for event in result["events"]}
    windows = {mapping[event["flight_id"]]: (event["start_s"], event["end_s"]) for event in labels["events"]}
    times = {group: set() for group in grouping["group_flights"]}
    for key in candidate["event_ids"]:
        event = lookup[key]
        group = event.get("harmonic_group_id") or key
        for point in event.get("ridge", []):
            value = point.get("time_s")
            if isinstance(value, (int, float)) and math.isfinite(value):
                times[group].add(float(value))
    compatible_flights = set()
    for group, flight in grouping["group_flights"].items():
        values = times[group]
        fractions = {identity: (sum(start - tolerance_s <= value <= end + tolerance_s for value in values) / len(values)
            if values else None) for identity, (start, end) in windows.items()}
        target = fractions.get(flight)
        cross = {identity: value for identity, value in fractions.items() if identity != flight}
        compatible = (len(values) >= 3 and target is not None and target >= 0.9
                      and all(value is not None and value < 0.9 for value in cross.values()))
        record["groups"].append({"group_id": group, "flight_id": flight,
            "ridge_times": len(values), "target_interval_fraction": target,
            "other_true_interval_fractions": cross, "compatible": compatible})
        if compatible:
            compatible_flights.add(flight)
    record["compatible_true_flyovers"] = len(compatible_flights)
    record["compatible"] = (bool(record["groups"]) and all(group["compatible"] for group in record["groups"])
        and compatible_flights == set(windows))
    return record


def clock_check(candidate, window, reference_utc):
    record = {"reported_recording_start_utc": candidate.get("recording_start_utc"),
        "within_request_window": False, "clock_error_s": None,
        "comparison": "inclusive trusted request UTC bounds; no additional tolerance"}
    def instant(value):
        if not isinstance(value, str):
            raise ValueError("Recording clock must be an explicit UTC timestamp")
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Recording clock lacks an explicit timezone")
        return moment.astimezone(timezone.utc)
    try:
        start, end = instant(window["start_utc"]), instant(window["end_utc"])
        reported = instant(candidate.get("recording_start_utc"))
        reference = instant(reference_utc)
        record.update(within_request_window=start <= reported <= end,
                      clock_error_s=(reported - reference).total_seconds())
    except (ValueError, KeyError, TypeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def evaluate_candidates(result, labels, mapping, distance, tolerance_s=None, request_window=None):
    reference = labels["location"]
    expected = sorted({mapping[event["flight_id"]] for event in labels["events"]})
    evaluated = []
    for rank, candidate in enumerate(result.get("candidates", []), 1):
        row = {"rank": rank, "flight_ids": candidate.get("flight_ids", []),
               "event_ids": candidate.get("event_ids", []), "error_m": None,
               "matched_groups": matched_groups(result, candidate),
               "association_timing": association_timing(result, candidate, labels, mapping, tolerance_s),
               "clock": clock_check(candidate, request_window, labels.get("recording_start_utc"))}
        try:
            lat, lon = float(candidate["lat"]), float(candidate["lon"])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Invalid candidate coordinate")
            error = abs(float(distance(reference[1], reference[0], lon, lat)))
            if not math.isfinite(error):
                raise ValueError("Nonfinite geodesic distance")
            row.update(error_m=error, full_true_flight_set_correct=sorted(set(row["flight_ids"])) == expected,
                       within_m={str(limit): error <= limit for limit in THRESHOLDS_M}, strict_under_100m=error < 100)
        except (ValueError, KeyError, TypeError) as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        evaluated.append(row)
    return evaluated


def assess(result, evaluations, checks, transport, stopped, required_flyovers):
    top = evaluations[0] if evaluations else {}
    groups = top.get("matched_groups", {})
    coverage = result.get("coverage", {})
    evidence_ok = REQUIRED_CHECKS <= checks.keys() and all(value is True for value in checks.values())
    flyovers_ok = (groups.get("valid") is True and groups.get("independent_groups", 0) >= required_flyovers
        and len(set(groups.get("group_flights", {}).values())) == required_flyovers)
    supported = (result.get("status") == "succeeded" and stopped and evidence_ok and flyovers_ok
        and coverage.get("search_complete") is True and coverage.get("data_status") == "available"
        and top.get("full_true_flight_set_correct") is True and top.get("association_timing", {}).get("compatible") is True
        and top.get("clock", {}).get("within_request_window") is True)
    outcomes = {str(limit): bool(supported and top.get("within_m", {}).get(str(limit)) is True)
                for limit in THRESHOLDS_M}
    localized = outcomes[str(PRIMARY_THRESHOLD_M)]
    return {"transport_ui_passed": bool(transport), "supported_decision": result.get("status") == "succeeded",
        "leading_prediction_error_m": top.get("error_m"), "required_true_flyovers": required_flyovers,
        "leading_prediction_clock": top.get("clock"),
        "matched_groups": groups, "required_group_count_met": flyovers_ok,
        "required_flyovers_explained": (flyovers_ok and top.get("full_true_flight_set_correct") is True
                                        and top.get("association_timing", {}).get("compatible") is True),
        "supported_localization_at_m": outcomes, "supported_localization_passed": localized,
        "primary_threshold_m": PRIMARY_THRESHOLD_M,
        "threshold_comparison": "less than or equal; strict-under-100m also recorded per candidate",
        "passed": bool(transport and localized)}


def evaluation_path(path, output):
    relative = path.relative_to(output)
    return relative.parts[0] == "evaluation" or "truth" in relative.parts or path.name == "generation.json"


def replay(args, repo):
    output = args.output
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    began = time.monotonic()
    receipt = {"schema_version": 1, "scope": "known-clock synthetic multi-event browser development replay",
        "started_utc": utc_now(), "expected_status": args.expect_status, "generated_event_count": args.events,
        "generator_seed": args.seed, "primary_threshold_m": PRIMARY_THRESHOLD_M,
        "total_budget_s": args.timeout_s, "stages": [], "passed": False,
        "transport_ui_passed": False, "supported_localization_passed": False,
        "evaluation_truth_loaded": False, "independent_real_accuracy_verified": False,
        "real_national_coverage_verified": False,
        "limitations": ["One finite synthetic development scene, not an independent real holdout.",
            "The sample-zero clock is supplied from the generator, not inferred from audio.",
            "Only finite generated traffic/terrain completeness is declared; no live acquisition is exercised.",
            "Reference separation is procedural; no operating-system filesystem sandbox is claimed.",
            "Sampled RSS includes verifier/server/browser/worker processes and can miss short peaks.",
            "A close alternative or expected inconclusive result cannot pass supported localization."]}
    def save():
        write_json(output / "acceptance.json", receipt)
    def run(name, command, cap=None):
        remaining = args.timeout_s - (time.monotonic() - began) - 15
        if remaining <= 0:
            raise TimeoutError("Total replay budget exhausted")
        receipt["stage"] = name
        save()
        execution = HELPERS.execute(command, snapshot, output / "logs" / f"{name}.log", env,
                                    min(remaining, cap) if cap else remaining)
        receipt["stages"].append({"stage": name, "execution": execution})
        save()
        return execution
    save()
    try:
        snapshot, receipt["implementation"] = snapshot_sources(repo, output)
        receipt["runtime"] = HELPERS.runtime_record()
        env = dict(os.environ, PYTHONPATH=str(snapshot / "src"), MPLBACKEND="Agg", **HELPERS.THREAD_ENV)
        perform_replay(args, output, snapshot, receipt, run, began)
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        receipt.update(finished_utc=utc_now(), elapsed_s=time.monotonic() - began)
        save()
        inventory_and_print(output, receipt)
    return 0 if receipt["passed"] else 1


def perform_replay(args, output, snapshot, receipt, run, began):
    runner = snapshot / "scripts/ci_upload_replay.py"
    fixture = output / "fixture"
    generation = run("generation", [sys.executable, str(snapshot / "scripts/make_multi_event_case.py"),
        "--output", str(fixture), "--events", str(args.events), "--seed", str(args.seed)], cap=300)
    if generation.get("returncode") != 0 or generation.get("timed_out"):
        raise RuntimeError("Independent fixture generation failed")
    inputs, evaluation = fixture / "inputs", output / "evaluation"
    evaluation.mkdir()
    (fixture / "truth").replace(evaluation / "truth")
    (fixture / "generation.json").replace(evaluation / "generation.json")
    index = inputs / "flights.sqlite"
    indexing = run("indexing", [sys.executable, str(runner), "_index", "--inputs", str(inputs),
        "--evaluation", str(evaluation), "--index", str(index), "--report", str(output / "indexing.json"),
        "--events", str(args.events)], cap=180)
    if indexing.get("returncode") != 0 or indexing.get("timed_out"):
        raise RuntimeError("Complete trajectory indexing failed")
    receipt["indexing"] = read_json(output / "indexing.json")
    receipt["input_files"] = {p.name: file_record(p) for p in sorted(inputs.iterdir()) if p.is_file()}
    wire = normal_wire_request(read_json(inputs / "request.json"))
    wire_path = output / "wire-request.json"
    write_json(wire_path, wire)
    operator = {"flight_indexes": [str(index)], "offline": True,
        "terrain": {"rasters": [str(inputs / "terrain.tif")], "geoid_raster": str(inputs / "geoid.tif")},
        "sound_speed_mps": 343, "max_distance_m": 20000}
    operator_path = output / "operator.json"
    write_json(operator_path, operator)
    receipt["normal_request"] = wire
    receipt["operator_configuration"] = operator
    product, lifecycle_path = output / "product", output / "service-lifecycle.json"
    job_budget = args.timeout_s - (time.monotonic() - began) - 60
    if job_budget <= 30:
        raise TimeoutError("Insufficient budget for upload and cleanup")
    execution = run("browser-upload", [sys.executable, str(runner), "_product", "--audio", str(inputs / "recording.mp3"),
        "--output", str(product), "--request", str(wire_path), "--operator", str(operator_path),
        "--lifecycle", str(lifecycle_path), "--browser-python", str(args.browser_python.absolute()),
        "--expect-status", args.expect_status, "--timeout-s", str(job_budget)])
    finish_evaluation(receipt, output, product, lifecycle_path, inputs, evaluation, operator, wire, execution)


def finish_evaluation(receipt, output, product, lifecycle_path, inputs, evaluation, operator, wire, execution):
    receipt["product_verifier"] = read_json(product / "report.json")
    receipt["service_lifecycle"] = read_json(lifecycle_path)
    result, receipt["job"] = collect_job(product, inputs / "recording.mp3", operator, wire,
        receipt["implementation"]["expected_implementation_files"])
    stopped = ready_for_truth(result, execution, receipt["service_lifecycle"])
    receipt["service_and_workers_stopped"] = stopped
    if not stopped:
        raise RuntimeError("Clean service/worker termination is unproven; evaluation labels remain unopened")
    receipt["analysis_stopped_utc"] = utc_now()
    labels_path = evaluation / "truth/labels.json"
    labels = read_json(labels_path)
    receipt["evaluation_truth_loaded"] = True
    receipt["evaluation_truth_loaded_utc"] = utc_now()
    receipt["evaluation_reference"] = file_record(labels_path)
    if len(labels["events"]) != receipt["generated_event_count"]:
        raise ValueError("Evaluation flyover count differs from the predeclared fixture")
    mapping = read_json(evaluation / "flight-id-mapping.json")["original_to_opaque"]
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    window = receipt["job"]["discovery_settings"].get("window_s")
    tolerance = float(window) / 2 if isinstance(window, (float, int)) else None
    evaluations = evaluate_candidates(result, labels, mapping, lambda *xy: geod.inv(*xy)[2],
                                      tolerance, wire["time_window"])
    receipt["candidate_evaluations"] = evaluations
    receipt["true_event_count"] = len(labels["events"])
    receipt["discovered_event_count"] = len(result.get("events", []))
    receipt["threshold_counts"] = {str(limit): {
        "all_candidates": sum(row.get("within_m", {}).get(str(limit)) is True for row in evaluations),
        "correct_full_flight_set": sum(row.get("within_m", {}).get(str(limit)) is True
            and row.get("full_true_flight_set_correct") is True for row in evaluations)} for limit in THRESHOLDS_M}
    transport = execution.get("returncode") == 0 and receipt["product_verifier"].get("passed") is True
    receipt.update(assess(result, evaluations, receipt["job"]["checks"], transport, stopped, len(labels["events"])))
    receipt["stage"] = "complete"


def inventory_and_print(output, receipt):
    try:
        files = {}
        for path in sorted(output.rglob("*")):
            if (not path.is_file() or path.name in {"acceptance.json", "artifact-manifest.json"}
                    or (not receipt["evaluation_truth_loaded"] and evaluation_path(path, output))):
                continue
            files[path.relative_to(output).as_posix()] = file_record(path)
        write_json(output / "artifact-manifest.json", {"files": files,
            "evaluation_files_included": receipt["evaluation_truth_loaded"]})
    except OSError as exc:
        receipt.update(artifact_inventory_error=str(exc), passed=False)
        write_json(output / "acceptance.json", receipt)
    print("===== BEGIN UPLOAD ACCEPTANCE JSON =====")
    print((output / "acceptance.json").read_text(), end="")
    print("===== END UPLOAD ACCEPTANCE JSON =====")


def child(argv):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="stage", required=True)
    index = sub.add_parser("_index")
    for name in ("inputs", "evaluation", "index", "report"):
        index.add_argument("--" + name, type=Path, required=True)
    index.add_argument("--events", type=int, required=True)
    product = sub.add_parser("_product")
    for name in ("audio", "output", "request", "operator", "lifecycle", "browser-python"):
        product.add_argument("--" + name, type=Path, required=True)
    product.add_argument("--expect-status", required=True)
    product.add_argument("--timeout-s", type=float, required=True)
    args = parser.parse_args(argv)
    if args.stage == "_index":
        index_fixture(args.inputs, args.evaluation, args.index, args.report, args.events)
        return 0
    return run_published_verifier(args)


if __name__ == "__main__":
    raise SystemExit(child(sys.argv[1:]) if len(sys.argv) > 1 and sys.argv[1].startswith("_") else main())
