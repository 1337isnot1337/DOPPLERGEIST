#!/usr/bin/env python3
"""Replay an independent synthetic MP3 through the actual local HTTP service.

Exit zero requires a supported producer decision, complete scientific evidence,
the correct flyovers and clock, and leading error <= 1,000 m. Expected abstention
can pass the HTTP verifier but never this acceptance runner. No browser is used.
Every invocation needs a new output directory; prior receipts are immutable.

Example: .venv/bin/python scripts/ci_http_replay.py --output results/http-new \
    --events 4 --seed 20261103 --timeout-s 1800 --expect-status succeeded
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPLOAD = load_module(Path(__file__).with_name("ci_upload_replay.py"), "http_replay_upload_helpers")
HELPERS = UPLOAD.HELPERS
read_json, write_json = HELPERS.read_json, HELPERS.write_json
file_record, utc_now = HELPERS.file_record, HELPERS.utc_now
CLEANUP_RESERVE_S = 30.0
FINALIZATION_RESERVE_S = 30.0
HTTP_REQUIRED_CHECKS = {"http_result_matches_persisted", "scientific_stage_gate_passed",
                        "scientific_stage_artifacts_unchanged", "source_snapshot_unchanged"}
SEARCH_FIELDS = (
    "status", "tiles_total", "tiles_completed", "tiles_resumed", "unsearched_tiles",
    "grid_points_searched", "refinement_points_searched", "refinement_points_skipped",
    "elapsed_s", "process_peak_rss_mib", "candidate_retention_limit",
    "all_event_groups_considered", "alternative_modes_exhaustively_assessed",
    "data_scope_complete", "tile_failures", "refinement_failure", "run_hash",
)


def remaining_budget(total_s, began, *, reserve_s=FINALIZATION_RESERVE_S, cap=None):
    available = total_s - (time.monotonic() - began) - reserve_s
    if available <= 0:
        raise TimeoutError("Total replay budget exhausted before the next stage")
    return min(available, cap) if cap is not None else available


def snapshot_sources(repo, output):
    """Reuse reviewed lifecycle/fixture checks and freeze the HTTP runner too."""
    snapshot, record = UPLOAD.snapshot_sources(repo, output)
    for name in ("ci_http_replay.py", "verify_upload_http.py"):
        shutil.copy2(repo / "scripts" / name, snapshot / "scripts" / name)
    files, combined = {}, hashlib.sha256()
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            name = path.relative_to(snapshot).as_posix()
            files[name] = file_record(path)
            combined.update(name.encode() + b"\0" + files[name]["sha256"].encode() + b"\0")
    record.update(files=files, snapshot_sha256=combined.hexdigest())
    write_json(output / "source-manifest.json", record)
    return snapshot, record


def snapshot_unchanged(snapshot, record):
    actual = {path.relative_to(snapshot).as_posix(): file_record(path)["sha256"]
              for path in snapshot.rglob("*") if path.is_file()
              and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    return actual == {name: item["sha256"] for name, item in record["files"].items()}


def ready_for_truth(result, execution, http):
    """An expected-status mismatch is diagnostic; unproven shutdown is a stop."""
    service = http.get("service", {})
    return (execution.get("returncode") in (0, 1) and not execution.get("timed_out")
        and not http.get("timed_out") and not http.get("shutdown_error")
        and not http.get("interrupted") and http.get("interruption_signal") is None
        and result.get("status") in UPLOAD.TERMINAL
        and http.get("status") == result.get("status")
        and bool(result.get("job_id")) and http.get("job_id") == result.get("job_id")
        and http.get("terminal_result_preserved_after_shutdown") is True
        and service.get("shutdown_signal") == "SIGINT" and service.get("returncode") == 0
        and service.get("forced_kill") is False and bool(service.get("stopped_utc")))


def pipeline_artifacts_match(directory, evidence):
    """Bind the frozen verifier's stage gate to the artifacts evaluated here."""
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return False
    for name, expected in artifacts.items():
        relative = Path(name)
        path = directory / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or not path.is_file() or not path.resolve().is_relative_to(directory.resolve())):
            return False
        item = file_record(path)
        if expected != {"bytes": item["bytes"], "sha256": item["sha256"]}:
            return False
    return True


def finite_alternatives_verified(search, refinement, decision, evidence, artifacts_unchanged):
    """Use the independent finite gate only with consistent bound producer/consumer records."""
    if (evidence.get("passed") is not True or evidence.get("full_pipeline_observed") is not True
            or evidence.get("scientific_decision_expected") is not True or evidence.get("errors") != []
            or evidence.get("finite_search_verified") is not True or artifacts_unchanged is not True):
        return False
    finite = search.get("finite_search_evidence")
    matching = refinement.get("matching_diagnostics", {})
    consumer = decision.get("diagnostics", {})
    artifacts = evidence.get("artifacts")
    if (not all(isinstance(value, dict) for value in (finite, matching, consumer, artifacts))
            or search.get("status") != "complete"
            or search.get("data_scope_complete") is not True or search.get("all_event_groups_considered") is not True
            or finite.get("scope") != "evaluated_finite_grid" or finite.get("complete") is not True
            or finite.get("pruning_accounted_for") is not True
            or type(finite.get("unclassified_score_candidates")) is not int or finite["unclassified_score_candidates"] != 0
            or matching.get("finite_search_evidence") != finite or matching.get("core_assessment_mapping_status") != "present"
            or consumer.get("policy_version") != "engineering-v5-finite-envelope"
            or finite.get("ledger_artifact") != "retention.sqlite"
            or "search/retention.sqlite" not in artifacts):
        return False
    modes = finite.get("retained_modes")
    producer, assessed, mapped = (search.get("core_assessed_mode_ids"), matching.get("assessed_mode_ids"),
                                   matching.get("candidate_mode_ids"))
    if (not isinstance(modes, list) or not modes
            or any(not isinstance(mode, dict) for mode in modes)):
        return False
    ids = [mode.get("mode_id") for mode in modes]
    if not all(isinstance(values, list) and values and all(isinstance(value, str) and value.strip() for value in values)
               for values in (ids, producer, assessed, mapped)):
        return False
    rows = refinement.get("ranked")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return False
    if (len(set(ids)) != len(ids) or len(set(producer)) != len(producer) or len(set(assessed)) != len(assessed)
            or set(ids) != set(producer) or set(ids) != set(assessed) or set(ids) != set(mapped)
            or mapped != [row.get("mode_id") for row in rows]):
        return False
    details = consumer.get("finite_search")
    return (isinstance(details, dict) and details.get("scope") == finite["scope"]
        and type(details.get("retained_modes")) is int and details["retained_modes"] == len(ids)
        and all(details.get(key) == finite.get(key) for key in
                ("spacing_m", "refine_spacing_m", "discarded_count", "best_discarded_score")))


def collect_job(product, result, audio, operator, wire, expected_sources, *, helpers=UPLOAD):
    """Use the upload acceptance cross-links for the HTTP verifier's jobs layout."""
    paths = list((product / "jobs").glob("*/result.json"))
    if len(paths) != 1:
        raise ValueError(f"Expected one actual HTTP job, found {len(paths)}")
    directory = paths[0].parent
    checks = {"evidence_collection_complete": False,
        "all_stage_artifacts_present": all((directory / name).is_file()
            and not (directory / name).is_symlink() for name in helpers.REQUIRED_ARTIFACTS)}
    errors, discovery, profile, search, evidence = [], {}, {}, {}, {}
    finite_verified = False
    try:
        checks["job_identity_matches"] = result.get("job_id") == directory.name
        checks["http_result_matches_persisted"] = read_json(paths[0]) == result
        uploaded = directory / "input.mp3"
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
        checks["search_consistent"] = helpers.search_matches_result(search, result.get("coverage", {}), provenance)
        checks["all_event_groups_considered"] = search.get("all_event_groups_considered") is True
        checks["alternative_evidence_consistent"] = (result.get("status") != "succeeded"
            or search.get("alternative_modes_exhaustively_assessed") is True)
        discovery = read_json(directory / "discovery/discovery.json")
        expected_ids = [event["event_id"] for event in discovery["events"]]
        checks["all_discovered_events_retained"] = (len(set(expected_ids)) == len(expected_ids)
            and sorted(discovery["events"], key=lambda event: event["event_id"])
                == sorted(result.get("events", []), key=lambda event: event["event_id"]))
        refinement = read_json(directory / "refined-candidates.json")
        profile = helpers.reported_fit_profile(result, refinement)
        checks["leading_refinement_row_bound"] = profile["leading_row_bound"]
        checks["nominal_joint_fit_recorded"] = profile["nominal_diagnostics_complete"]
        evidence = read_json(product / "pipeline-evidence.json")
        checks["scientific_stage_gate_passed"] = (evidence.get("passed") is True
            and evidence.get("full_pipeline_observed") is True
            and evidence.get("scientific_decision_expected") is True and evidence.get("errors") == [])
        checks["scientific_stage_artifacts_unchanged"] = pipeline_artifacts_match(directory, evidence)
        finite_verified = finite_alternatives_verified(search, refinement, decision, evidence,
            checks["scientific_stage_artifacts_unchanged"])
        if "finite_search_evidence" in search and result.get("status") == "succeeded":
            # Finite evidence takes precedence; a stale legacy flag cannot repair it.
            checks["alternative_evidence_consistent"] = finite_verified
        checks["evidence_collection_complete"] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    return {"directory": str(directory), "checks": checks, "errors": errors,
        "result_file": file_record(paths[0]), "status": result.get("status"),
        "reason_code": result.get("reason_code"), "candidate_count": len(result.get("candidates", [])),
        "event_count": len(result.get("events", [])), "coverage": result.get("coverage"),
        "discovery_settings": discovery.get("settings", {}), "reported_fit_profile": profile,
        "pipeline_evidence": evidence, "finite_search_verified": finite_verified,
        "search": {key: search.get(key) for key in SEARCH_FIELDS},
        "native_search_memory": {"reported_peak_mib": search.get("process_peak_rss_mib"),
            "mechanism": "Producer resource.getrusage(RUSAGE_SELF).ru_maxrss / 1024 on Linux",
            "scope": "Search worker high-water RSS through search completion; no worker-start baseline is subtracted.",
            "whole_pipeline_peak_established": False}}


def assess_http(result, evaluations, checks, execution, http, stopped, required_flyovers, *, helpers=UPLOAD):
    uninterrupted = not http.get("interrupted") and http.get("interruption_signal") is None
    transport = (execution.get("returncode") == 0 and not execution.get("timed_out")
        and http.get("verification_passed") is True and http.get("http_checks_passed") is True
        and http.get("pipeline_evidence_passed") is True and http.get("full_pipeline_observed") is True
        and uninterrupted)
    checks = dict(checks, http_replay_evidence_complete=HTTP_REQUIRED_CHECKS <= checks.keys()
                  and all(checks[name] is True for name in HTTP_REQUIRED_CHECKS),
                  http_pipeline_verification_complete=transport,
                  verification_completed_without_interruption=uninterrupted,
                  producer_decision_verification_consistent=result.get("status") != "succeeded"
                  or http.get("supported_decision") is True)
    assessment = helpers.assess(result, evaluations, checks, transport, stopped, required_flyovers)
    assessment["http_transport_passed"] = assessment.pop("transport_ui_passed")
    assessment["http_checks_passed"] = http.get("http_checks_passed") is True
    assessment["http_expectation_matched"] = http.get("expectation_matched") is True
    assessment["http_verification_passed"] = http.get("verification_passed") is True
    assessment["producer_reported_success"] = assessment.pop("supported_decision")
    evidence_complete = helpers.REQUIRED_CHECKS <= checks.keys() and all(value is True for value in checks.values())
    assessment["supported_decision"] = (assessment["producer_reported_success"]
        and http.get("supported_decision") is True and transport and stopped is True and evidence_complete)
    return assessment


def finish_evaluation(receipt, output, inputs, evaluation, operator, wire, execution, *, helpers=UPLOAD):
    product = output / "http"
    http, result = read_json(product / "http-verification.json"), read_json(product / "result.json")
    receipt["http_verification"] = http
    receipt["http_checks_passed"] = http.get("http_checks_passed") is True
    receipt["http_expectation_matched"] = http.get("expectation_matched") is True
    receipt["http_verification_passed"] = http.get("verification_passed") is True
    stopped = ready_for_truth(result, execution, http)
    receipt["service_and_workers_stopped"] = stopped
    if not stopped:
        raise RuntimeError("Clean service and worker shutdown is unproven; evaluation labels remain unopened")
    receipt["analysis_stopped_utc"] = utc_now()
    job = collect_job(product, result, inputs / "recording.mp3", operator, wire,
        receipt["implementation"]["expected_implementation_files"], helpers=helpers)
    receipt["job"] = job
    job["checks"]["source_snapshot_unchanged"] = snapshot_unchanged(output / "implementation", receipt["implementation"])
    receipt["evaluation_truth_load_started_utc"] = utc_now()
    receipt["evaluation_truth_opened"] = True
    labels = read_json(evaluation / "truth/labels.json")
    mapping = read_json(evaluation / "flight-id-mapping.json")["original_to_opaque"]
    receipt["evaluation_truth_loaded"] = True
    receipt["evaluation_truth_loaded_utc"] = utc_now()
    receipt["evaluation_reference"] = file_record(evaluation / "truth/labels.json")
    if len(labels["events"]) != receipt["generated_event_count"]:
        raise ValueError("Evaluation flyover count differs from the predeclared fixture")
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    window = job["discovery_settings"].get("window_s")
    tolerance = float(window) / 2 if type(window) in (int, float) else None
    evaluations = helpers.evaluate_candidates(result, labels, mapping, lambda *xy: geod.inv(*xy)[2],
        tolerance_s=tolerance, request_window=wire["time_window"])
    write_json(output / "candidate-evaluations.json", evaluations)
    receipt["candidate_evaluations"] = evaluations
    receipt["true_event_count"] = len(labels["events"])
    receipt["threshold_counts"] = {str(limit): {
        "all_candidates": sum(row.get("within_m", {}).get(str(limit)) is True for row in evaluations),
        "correct_full_flight_set": sum(row.get("within_m", {}).get(str(limit)) is True
            and row.get("full_true_flight_set_correct") is True for row in evaluations)} for limit in helpers.THRESHOLDS_M}
    receipt.update(assess_http(result, evaluations, job["checks"], execution, http, stopped,
                              len(labels["events"]), helpers=helpers))
    receipt["stage"] = "complete"


def write_inventory(output, *, include_evaluation):
    files = {}
    for path in sorted(output.rglob("*")):
        if (not path.is_file() or path.name in {"acceptance.json", "artifact-manifest.json"}
                or "__pycache__" in path.parts or path.suffix == ".pyc"
                or (not include_evaluation and UPLOAD.evaluation_path(path, output))):
            continue
        if path.is_symlink():
            raise ValueError(f"Unexpected symlink in replay evidence: {path.relative_to(output)}")
        files[path.relative_to(output).as_posix()] = file_record(path)
    manifest = output / "artifact-manifest.json"
    write_json(manifest, {"files": files, "evaluation_files_included": include_evaluation,
                         "acceptance_receipt_excluded_to_avoid_hash_cycle": True})
    return file_record(manifest)


def invalidate_acceptance(receipt, reason):
    """Clear acceptance claims while retaining the producer and error diagnostics."""
    receipt.update(passed=False, supported_decision=False, supported_localization_passed=False,
                   supported_localization_at_m={str(limit): False for limit in UPLOAD.THRESHOLDS_M})
    reasons = receipt.setdefault("acceptance_invalidations", [])
    if reason not in reasons:
        reasons.append(reason)


def finalize_receipt(receipt, output, began, timeout_s):
    try:
        if "implementation" in receipt:
            receipt["source_snapshot_unchanged"] = snapshot_unchanged(output / "implementation", receipt["implementation"])
            if not receipt["source_snapshot_unchanged"]:
                invalidate_acceptance(receipt, "source_snapshot_changed")
    except (OSError, ValueError, KeyError) as exc:
        receipt["source_verification_error"] = f"{type(exc).__name__}: {exc}"
        invalidate_acceptance(receipt, "source_verification_failed")
    try:
        receipt["artifact_manifest"] = write_inventory(output, include_evaluation=receipt["evaluation_truth_opened"])
    except (OSError, ValueError, KeyError) as exc:
        receipt["artifact_inventory_error"] = f"{type(exc).__name__}: {exc}"
        invalidate_acceptance(receipt, "artifact_inventory_failed")
    receipt.update(finished_utc=utc_now(), elapsed_s=time.monotonic() - began)
    receipt["time_budget_respected"] = receipt["elapsed_s"] <= timeout_s
    if not receipt["time_budget_respected"]:
        invalidate_acceptance(receipt, "time_budget_exceeded")
    write_json(output / "acceptance.json", receipt)


def replay(args, repo):
    output = Path(args.output).resolve()
    if output.is_relative_to(repo / "src"):
        raise ValueError("Output cannot be inside the source tree being snapshotted")
    output.mkdir(parents=True, exist_ok=False)
    (output / "logs").mkdir()
    began = time.monotonic()
    receipt = {"schema_version": 1, "scope": "known-clock synthetic multi-event actual HTTP development replay",
        "started_utc": utc_now(), "expected_status": args.expect_status, "generated_event_count": args.events,
        "generator_seed": args.seed, "primary_threshold_m": UPLOAD.PRIMARY_THRESHOLD_M,
        "thresholds_m": list(UPLOAD.THRESHOLDS_M), "total_budget_s": args.timeout_s,
        "stages": [], "passed": False, "http_transport_passed": False, "supported_decision": False,
        "supported_localization_passed": False,
        "supported_localization_at_m": {str(limit): False for limit in UPLOAD.THRESHOLDS_M},
        "evaluation_truth_opened": False, "evaluation_truth_loaded": False, "browser_verified": False,
        "independent_real_accuracy_verified": False, "live_acquisition_verified": False,
        "real_national_coverage_verified": False,
        "limitations": ["One finite synthetic development scene; no independent real holdout is evaluated.",
            "The generator supplies the sample-zero clock; it is not inferred from audio.",
            "All generated traffic is retained; completeness describes only this finite synthetic population.",
            "Truth separation is procedural; no operating-system isolation of evaluation files is claimed.",
            "An expected inconclusive response never passes supported-localization acceptance.",
            "Process-tree RSS is unavailable when /proc PIDs do not match the process namespace; valid samples may miss peaks.",
            "Native search-worker RSS does not establish the whole-pipeline peak."]}
    write_json(output / "protocol.json", receipt)

    def save():
        write_json(output / "acceptance.json", receipt)

    def run(name, command, *, cap=None):
        timeout = remaining_budget(args.timeout_s, began, cap=cap)
        receipt["stage"] = name
        save()
        print(json.dumps({"stage": name, "started_utc": utc_now(), "timeout_s": timeout}), flush=True)
        execution = helpers.HELPERS.execute(command, snapshot, output / "logs" / f"{name}.log", env, timeout)
        receipt["stages"].append({"stage": name, "execution": execution})
        save()
        print(json.dumps({"stage": name, "returncode": execution.get("returncode"),
            "elapsed_s": execution["elapsed_s"], "timed_out": execution.get("timed_out", False)}), flush=True)
        return execution

    try:
        snapshot, receipt["implementation"] = snapshot_sources(repo, output)
        helpers = load_module(snapshot / "scripts/ci_upload_replay.py", "frozen_http_upload_helpers")
        receipt["runtime"] = helpers.HELPERS.runtime_record()
        env = dict(os.environ, PYTHONPATH=str(snapshot / "src"), MPLBACKEND="Agg", **helpers.HELPERS.THREAD_ENV)
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
        indexing = run("indexing", [sys.executable, str(snapshot / "scripts/ci_upload_replay.py"), "_index",
            "--inputs", str(inputs), "--evaluation", str(evaluation), "--index", str(index),
            "--report", str(output / "indexing.json"), "--events", str(args.events)], cap=180)
        if indexing.get("returncode") != 0 or indexing.get("timed_out"):
            raise RuntimeError("Complete generated traffic indexing failed")
        receipt["indexing"] = read_json(output / "indexing.json")
        receipt["input_files"] = {path.name: file_record(path) for path in sorted(inputs.iterdir()) if path.is_file()}
        wire = helpers.normal_wire_request(read_json(inputs / "request.json"))
        write_json(output / "wire-request.json", wire)
        operator = {"flight_indexes": [str(index)], "offline": True,
            "terrain": {"rasters": [str(inputs / "terrain.tif")], "geoid_raster": str(inputs / "geoid.tif")},
            "sound_speed_mps": 343, "max_distance_m": 20000}
        write_json(output / "operator.json", operator)
        receipt["normal_request"], receipt["operator_configuration"] = wire, operator
        job_budget = remaining_budget(args.timeout_s, began,
            reserve_s=CLEANUP_RESERVE_S + FINALIZATION_RESERVE_S)
        execution = run("http-upload", [sys.executable, str(snapshot / "scripts/verify_upload_http.py"),
            "--audio", str(inputs / "recording.mp3"), "--operator-config", str(output / "operator.json"),
            "--output", str(output / "http"), "--start-utc", wire["time_window"]["start_utc"],
            "--end-utc", wire["time_window"]["end_utc"], "--time-source", helpers.TIME_SOURCE,
            "--expect-status", args.expect_status, "--timeout-s", str(job_budget)])
        finish_evaluation(receipt, output, inputs, evaluation, operator, wire, execution, helpers=helpers)
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        invalidate_acceptance(receipt, "replay_error")
    finally:
        finalize_receipt(receipt, output, began, args.timeout_s)
        print(json.dumps({"report": str(output / "acceptance.json"), "stage": receipt.get("stage"),
            "http_transport_passed": receipt["http_transport_passed"], "passed": receipt["passed"],
            "scientific_status": receipt.get("job", {}).get("status"),
            "scientific_reason": receipt.get("job", {}).get("reason_code"),
            "leading_error_m": receipt.get("leading_prediction_error_m"), "elapsed_s": receipt["elapsed_s"],
            "error": receipt.get("error")}), flush=True)
    return 0 if receipt["passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing evidence is refused")
    parser.add_argument("--events", type=int, choices=(3, 4, 6), default=4)
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--timeout-s", "--time-budget-s", dest="timeout_s", type=float, default=1800,
        help="Total replay budget in seconds, including preparation and evaluation (default: 1800)")
    parser.add_argument("--expect-status", choices=sorted(UPLOAD.TERMINAL), default="succeeded",
        help="Predeclared HTTP expectation; inconclusive/failed expectations still cannot pass overall acceptance")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout_s) or args.timeout_s <= CLEANUP_RESERVE_S + FINALIZATION_RESERVE_S:
        parser.error("--timeout-s must be finite and greater than 60 seconds")
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    try:
        return replay(args, Path(__file__).resolve().parents[1])
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
