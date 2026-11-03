#!/usr/bin/env python3
"""Run the real automatic CLI on the complete independently rendered fixture.

This is a synthetic integration check. It does not validate the HTTP/browser
upload surface, live data acquisition, or independent real-recording accuracy.
Evaluation truth is opened only after the actual automatic CLI has terminated.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import sys
import threading
import time


# Reuse the already reviewed subprocess/resource recorder; it imports no DSP.
_HELPER_SPEC = importlib.util.spec_from_file_location(
    "automatic_replay_helpers", Path(__file__).with_name("ci_checkpoint_replay.py"))
_HELPERS = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(_HELPERS)
file_record = _HELPERS.file_record
read_json = _HELPERS.read_json
write_json = _HELPERS.write_json
utc_now = _HELPERS.utc_now

RECORDING_EPOCH = 1790000000.0
EXPECTED_FLIGHT_COUNT = 7
SYNTHETIC_BOUNDS = [-125.0, 24.0, -66.0, 50.0]
# Receiver scope remains CONUS. The complete simulated aircraft universe is
# declared across this fixed envelope, including W2's 20 km acoustic support
# margin (about 0.665 degrees longitude and 0.428 degrees latitude).
SYNTHETIC_SOURCE_BOUNDS = [-126.0, 23.0, -65.0, 51.0]
TIME_SOURCE = "Known sample-zero clock of the independent synthetic generator"
REQUIRED_MODULES = (
    "contracts", "intake", "discovery", "data_access", "tiled_search",
    "matching", "confidence", "automatic", "jobs", "cli",
)
REQUIRED_ARTIFACTS = (
    "request.json", "operator.json", "input.json", "provenance.json",
    "intake/intake.json", "intake/recording.json", "discovery/discovery.json",
    "search/search-report.json", "data-provenance.json", "refined-candidates.json", "decision.json",
    "result.json", "worker.log",
)
LIMITATIONS = [
    "This is the complete generated synthetic fixture, not independent real audio.",
    "The offline trajectory index describes the generated universe only; real ADS-B receiver completeness is not established.",
    "The fixed 120 m synthetic terrain model does not establish real elevation or vertical-datum accuracy.",
    "The real automatic CLI and job subprocesses are exercised; HTTP upload and browser display are not exercised.",
    "Data are prepared offline; live historical flight and terrain acquisition are not exercised.",
    "Truth and legacy event settings are not pipeline inputs. Filesystem access to generator source and evaluation artifacts is not sandboxed.",
    "Candidate error below 100 m is diagnostic unless the actual decision also reports succeeded.",
]


def recording_start_utc():
    return datetime.fromtimestamp(RECORDING_EPOCH, timezone.utc).isoformat().replace("+00:00", "Z")


def normal_request(audio_path):
    """Only the observed normal request fields; no event or location hints."""
    instant = recording_start_utc()
    return {"schema_version": 1, "audio_path": str(Path(audio_path).resolve()),
            "search": {"coverage": "conus"},
            "time_window": {"start_utc": instant, "end_utc": instant,
                            "source": "user", "source_detail": TIME_SOURCE}}


def synthetic_coverage():
    return {"bounds": list(SYNTHETIC_SOURCE_BOUNDS),
            "time_range_s": [RECORDING_EPOCH - 600, RECORDING_EPOCH + 1780],
            "all_aircraft": True, "synthetic": True,
            "source_note": "Complete seven-track generated simulation only, including every distractor and aircraft class. No additional aircraft exist in this declared synthetic source envelope; this is not real receiver coverage."}


def operator_configuration(index_path):
    # These are observed W5 keys. No unpublished SearchBudget fields are guessed.
    return {"flight_indexes": [str(Path(index_path).resolve())], "offline": True,
            "terrain": {"constant_m": 120}, "sound_speed_mps": 343,
            "max_distance_m": 20000}


def require_components(snapshot):
    package = Path(snapshot) / "src/aircraft_geoloc"
    missing = [name for name in REQUIRED_MODULES if not (package / f"{name}.py").is_file()]
    if missing:
        raise RuntimeError("Required automatic producers are absent: " + ", ".join(missing))


def snapshot_implementation(repo, output):
    snapshot, record = _HELPERS.code_snapshot(repo, output)
    shutil.copy2(Path(__file__), snapshot / "ci_automatic_replay.py")
    (snapshot / "scripts").mkdir()
    shutil.copy2(repo / "scripts/make_synthetic_cases.py", snapshot / "scripts/make_synthetic_cases.py")
    combined, files = hashlib.sha256(), {}
    for path in sorted(snapshot.rglob("*")):
        if path.is_file():
            relative = path.relative_to(snapshot).as_posix()
            files[relative] = file_record(path)
            combined.update(relative.encode() + b"\0" + files[relative]["sha256"].encode() + b"\0")
    record.update(files=files, snapshot_sha256=combined.hexdigest(), snapshot_copy_atomic=False,
                  expected_automatic_files={path.name: file_record(path)["sha256"]
                      for path in sorted((snapshot / "src/aircraft_geoloc").glob("*.py"))})
    return snapshot, record


def trajectory_inventory(csv_path):
    """Read the entire trajectory table, without selecting any flight or region."""
    counts, typecodes = Counter(), Counter()
    with Path(csv_path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        required = {"flight_id", "time_s", "lat", "lon", "alt_m", "typecode"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("Synthetic trajectory CSV lacks canonical columns")
        for row in reader:
            if not row["flight_id"]:
                raise ValueError("Synthetic trajectory has no flight ID")
            values = {key: float(row[key]) for key in ("time_s", "lat", "lon", "alt_m")}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError("Synthetic trajectory has non-finite data")
            if not (SYNTHETIC_BOUNDS[0] <= values["lon"] <= SYNTHETIC_BOUNDS[2]
                    and SYNTHETIC_BOUNDS[1] <= values["lat"] <= SYNTHETIC_BOUNDS[3]):
                raise ValueError("Synthetic trajectory leaves the declared simulation bounds")
            counts[row["flight_id"]] += 1
            typecodes[row["typecode"]] += 1
    if len(counts) != EXPECTED_FLIGHT_COUNT:
        raise ValueError(f"Expected all {EXPECTED_FLIGHT_COUNT} generated tracks, found {len(counts)}")
    if "A320" not in typecodes or "C172" not in typecodes:
        raise ValueError("Generated aircraft classes were filtered or the fixture changed")
    return {"rows": sum(counts.values()), "flight_count": len(counts),
            "samples_per_flight": dict(sorted(counts.items())), "typecode_rows": dict(sorted(typecodes.items()))}


def anonymize_trajectories(source_csv, target_csv, mapping_path):
    """Remove semantic IDs without opening truth or selecting any trajectories."""
    original = trajectory_inventory(source_csv)
    with Path(source_csv).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or ())
        if set(fields) != {"flight_id", "time_s", "lat", "lon", "alt_m", "typecode"}:
            raise ValueError("Unexpected generator columns; refuse to copy potential label fields into the index")
        rows = list(reader)
    # IDs and trajectory order both use system randomness. Neither depends on
    # label meanings, recording content, coordinates, or evaluation truth.
    mapping = {}
    for original_id in original["samples_per_flight"]:
        opaque = "flight-" + secrets.token_hex(16)
        while opaque in mapping.values():
            opaque = "flight-" + secrets.token_hex(16)
        mapping[original_id] = opaque
    order = list(mapping)
    secrets.SystemRandom().shuffle(order)
    with Path(target_csv).open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for original_id in order:
            for row in rows:
                if row["flight_id"] == original_id:
                    writer.writerow(dict(row, flight_id=mapping[original_id]))
    opaque = trajectory_inventory(target_csv)
    expected = {mapping[key]: count for key, count in original["samples_per_flight"].items()}
    expected_rows = Counter(tuple(mapping[row[field]] if field == "flight_id" else row[field]
                                  for field in fields) for row in rows)
    with Path(target_csv).open(newline="", encoding="utf-8") as stream:
        actual_rows = Counter(tuple(row[field] for field in fields) for row in csv.DictReader(stream))
    if (opaque["samples_per_flight"] != expected or opaque["rows"] != original["rows"]
            or opaque["typecode_rows"] != original["typecode_rows"] or actual_rows != expected_rows):
        raise ValueError("Opaque-ID conversion did not preserve all trajectory rows and aircraft classes")
    write_json(mapping_path, {"schema_version": 1, "original_to_opaque": mapping,
        "method": "Independent random opaque IDs and random trajectory order; no truth file read",
        "source": file_record(source_csv), "target": file_record(target_csv),
        "source_inventory": original, "opaque_inventory": opaque})
    return opaque


def evaluation_flight_ids(truth, mapping_record):
    """Translate evaluation-only labels after the real automatic job has ended."""
    mapping = mapping_record["original_to_opaque"]
    if (len(mapping) != EXPECTED_FLIGHT_COUNT or len(set(mapping.values())) != EXPECTED_FLIGHT_COUNT
            or not all(value.startswith("flight-") and len(value) == 39 for value in mapping.values())):
        raise ValueError("Evaluation identity mapping is incomplete or invalid")
    return [mapping[identifier] for identifier in truth["flight_ids"]]


def prepare_index(csv_path, parquet_path, index_path, report_path):
    """Subprocess stage: preserve all CSV rows and index the complete fixture."""
    inventory = trajectory_inventory(csv_path)
    if not all(identifier.startswith("flight-") and len(identifier) == 39
               for identifier in inventory["samples_per_flight"]):
        raise ValueError("Only opaque trajectory identifiers may enter the search index")
    import pandas as pd
    from aircraft_geoloc.data_access import FlightIndex

    frame = pd.read_csv(csv_path)
    if len(frame) != inventory["rows"]:
        raise ValueError("CSV conversion changed the trajectory row count")
    # The inspected generator uses ellipsoidal geodetic heights. This label is
    # fixture provenance, not recorder coordinates or evaluation truth.
    frame["altitude_basis"] = "ellipsoidal"
    frame.to_parquet(parquet_path, index=False)
    coverage = synthetic_coverage()
    index = FlightIndex.from_parquet(index_path, parquet_path, coverage=coverage)
    returned = {track.id: len(track.time) for track in index.query(SYNTHETIC_BOUNDS, coverage["time_range_s"])}
    if returned != inventory["samples_per_flight"]:
        raise ValueError("The flight index did not preserve every complete generated trajectory")
    if index.report["rows"] != inventory["rows"] or index.report["segments"] != EXPECTED_FLIGHT_COUNT:
        raise ValueError("The flight index did not retain all generated rows and seven tracks")
    if index.report.get("jets_excluded") is not False:
        raise ValueError("The automatic fixture index must retain jets")
    write_json(report_path, {"status": "passed", "inventory": inventory, "coverage": coverage,
        "index_report": index.report, "sources": [file_record(csv_path), file_record(parquet_path), file_record(index_path)],
        "all_generated_tracks_retained": True, "evaluation_truth_read": False})


def preflight(snapshot, report_path):
    """Import actual producers in a fresh process and verify their source paths."""
    snapshot = Path(snapshot).resolve()
    require_components(snapshot)
    modules, signatures = {}, {}
    for name in REQUIRED_MODULES:
        module = importlib.import_module(f"aircraft_geoloc.{name}")
        expected = snapshot / f"src/aircraft_geoloc/{name}.py"
        if Path(module.__file__).resolve() != expected:
            raise RuntimeError(f"{name} imported outside the frozen source snapshot")
        modules[name] = file_record(expected)
    hooks = {"intake": ("intake_recording",), "discovery": ("discover_events",),
             "data_access": ("FlightIndex", "acquire_inputs"),
             "tiled_search": ("SearchBudget", "search_national"),
             "matching": ("prepare_events", "refine_candidate"),
             "confidence": ("decide_location",), "jobs": ("JobManager",)}
    for name, attributes in hooks.items():
        module = importlib.import_module(f"aircraft_geoloc.{name}")
        for attribute in attributes:
            hook = getattr(module, attribute)
            if not callable(hook):
                raise TypeError(f"Required producer hook is not callable: {name}.{attribute}")
            signatures[f"{name}.{attribute}"] = str(inspect.signature(hook))
    write_json(report_path, {"status": "passed", "modules": modules, "signatures": signatures,
                             "numerical_stages_executed": False})


def verify_normal_request(actual, expected_audio):
    """Reject extra scientific hints in the request persisted by the real CLI."""
    expected = normal_request(expected_audio)
    if actual != expected:
        raise ValueError("The persisted request differs from audio + fixed recording clock + declared CONUS coverage")
    return True


def stage_consistency(directory, result, provenance):
    """Cross-check persisted outputs, without inferring scientific success."""
    decision = read_json(Path(directory) / "decision.json")
    search = read_json(Path(directory) / "search/search-report.json")
    decision_matches = ("status" in decision and "candidates" in decision
        and all(decision.get(key) == result.get(key)
                for key in ("status", "reason_code", "message", "candidates")))
    coverage = result.get("coverage", {})
    total, completed = search.get("tiles_total"), search.get("tiles_completed")
    counts_valid = (type(total) is int and type(completed) is int and total > 0
                    and 0 <= completed <= total and search.get("unsearched_tiles") == total - completed)
    complete = search.get("status") == "complete"
    complete_evidence = (not complete or (counts_valid and completed == total
        and not search.get("tile_failures") and search.get("refinement_failure") is None
        and search.get("data_scope_complete") is True))
    search_matches = (search.get("status") in {"complete", "partial"}
        and counts_valid and complete_evidence and search.get("scope") == SYNTHETIC_BOUNDS
        and coverage.get("search_complete") is complete
        and coverage.get("data_status") == ("available" if search.get("data_scope_complete") else "partial")
        and isinstance(search.get("run_hash"), str) and bool(search["run_hash"])
        and provenance.get("search_run_hash") == search["run_hash"])
    alternatives_consistent = (result.get("status") != "succeeded"
        or search.get("alternative_modes_exhaustively_assessed") is not False)
    return {"decision_artifact_consistent": decision_matches,
            "search_artifact_consistent": search_matches,
            "alternative_mode_evidence_consistent": alternatives_consistent}


def collect_job(jobs, source_mp3, expected_operator, expected_sources):
    paths = sorted(Path(jobs).glob("*/result.json"))
    if len(paths) != 1:
        raise RuntimeError(f"Expected one actual automatic JobResult, found {len(paths)}")
    directory = paths[0].parent
    result = read_json(paths[0])
    if result.get("job_id") != directory.name:
        raise ValueError("JobResult ID does not match its persisted directory")
    uploaded = directory / "input.mp3"
    checks = {"normal_request_verified": False, "uploaded_bytes_verified": False,
              "operator_configuration_verified": False, "implementation_verified": False,
              "all_stage_artifacts_present": False, "decision_artifact_consistent": False,
              "search_artifact_consistent": False, "alternative_mode_evidence_consistent": False}
    diagnostics = []
    try:
        checks["normal_request_verified"] = verify_normal_request(read_json(directory / "request.json"), uploaded)
        checks["operator_configuration_verified"] = read_json(directory / "operator.json") == expected_operator
        checks["uploaded_bytes_verified"] = (file_record(uploaded)["sha256"] == file_record(source_mp3)["sha256"]
            == result.get("recording", {}).get("source_sha256"))
        provenance = read_json(directory / "provenance.json")
        checks["implementation_verified"] = provenance.get("implementation_files") == expected_sources
        checks.update(stage_consistency(directory, result, provenance))
    except (OSError, ValueError, TypeError) as exc:
        diagnostics.append(f"{type(exc).__name__}: {exc}")
    missing = [name for name in REQUIRED_ARTIFACTS if not (directory / name).is_file()]
    checks["all_stage_artifacts_present"] = not missing
    return result, {"directory": str(directory), "result": file_record(paths[0]),
                    "status": result.get("status"), "reason_code": result.get("reason_code"),
                    "coverage": result.get("coverage"), "checks": checks,
                    "missing_stage_artifacts": missing, "diagnostics": diagnostics}


def evaluate_candidates(result, truth, *, deadline=None):
    """Evaluation-only stage; never called until the actual CLI has terminated."""
    evaluated = []
    for index, candidate in enumerate(result.get("candidates", [])):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Candidate evaluation exceeded the total replay budget")
        distance = _HELPERS.evaluate_best(candidate, truth)
        expected = sorted(set(truth["flight_ids"]))
        observed = sorted(set(candidate.get("flight_ids", [])))
        evaluated.append({"rank": index + 1, "error_m": distance["error_m"],
                          "distance_metric": distance["distance_metric"],
                          "threshold_m": distance["threshold_m"],
                          "meets_threshold": distance["meets_threshold"],
                          "distinct_flights_correct": observed == expected,
                          "flight_ids": candidate.get("flight_ids", [])})
    return evaluated


def ready_for_evaluation(result, execution):
    """A clean CLI exit joins its worker; forced exits do not prove completion."""
    return (execution.get("returncode") == 0 and not execution.get("timed_out")
            and result.get("status") in {"succeeded", "inconclusive", "failed", "needs_input", "cancelled"})


def assess_outcome(result, evaluations, checks, execution):
    """A close hypothesis cannot promote an inconclusive decision into success."""
    best = evaluations[0] if evaluations else {}
    supported = result.get("status") == "succeeded"
    close = best.get("meets_threshold") is True
    flights = best.get("distinct_flights_correct") is True
    coverage = result.get("coverage", {})
    complete = coverage.get("search_complete") is True and coverage.get("data_status") == "available"
    events = result.get("events", [])
    event_lookup = {event.get("event_id"): event for event in events}
    candidates = result.get("candidates", [])
    matched_ids = candidates[0].get("event_ids", []) if candidates else []
    matched_valid = (bool(matched_ids) and len(event_lookup) == len(events)
        and len(set(matched_ids)) == len(matched_ids)
        and all(identifier is not None and identifier in event_lookup for identifier in matched_ids))
    groups = {event_lookup[identifier].get("harmonic_group_id") or identifier
              for identifier in matched_ids} if matched_valid else set()
    execution_ok = execution.get("returncode") == 0 and not execution.get("timed_out")
    checks_ok = bool(checks) and all(value is True for value in checks.values())
    return {"supported_decision": supported, "top_candidate_within_100m": close,
            "top_candidate_flights_correct": flights, "declared_synthetic_coverage_complete": complete,
            "independent_event_groups": len(groups), "matched_event_ids_valid": matched_valid,
            "execution_succeeded": execution_ok,
            "provenance_checks_passed": checks_ok,
            "passed": bool(supported and close and flights and complete and matched_valid and len(groups) >= 2
                           and execution_ok and checks_ok)}


def artifact_inventory(output, truth_loaded):
    records = {}
    for path in sorted(Path(output).rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output)
        if relative.as_posix() in {"acceptance.json", "artifact-manifest.json"}:
            continue
        # Failed preparation must not open labels before any automatic run.
        if not truth_loaded and ("evaluation" in relative.parts or path.name == "truth.json"):
            continue
        records[relative.as_posix()] = file_record(path)
    return records


def observe_job_states(jobs, path, stop, warnings):
    """Record observed status/stage changes; sub-poll-duration states may be missed."""
    previous = {}
    with Path(path).open("x", encoding="utf-8") as stream:
        def sample():
            for result_path in sorted(Path(jobs).glob("*/result.json")):
                try:
                    data = result_path.read_bytes()
                    result = json.loads(data)
                    state = {key: result[key] for key in ("job_id", "status", "stage", "progress", "reason_code")
                             if key in result}
                    if previous.get(str(result_path)) == state:
                        continue
                    previous[str(result_path)] = state
                    stream.write(json.dumps({"observed_utc": utc_now(), "result_path": str(result_path),
                        "result_sha256": hashlib.sha256(data).hexdigest(), "state": state}, allow_nan=False) + "\n")
                    stream.flush()
                except (OSError, ValueError, TypeError) as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    if message not in warnings:
                        warnings.append(message)
        sample()
        while not stop.wait(0.2):
            sample()
        sample()  # Preserve the final observable state even after a fast exit.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New output directory; existing paths are refused")
    parser.add_argument("--timeout-s", type=float, default=1800, help="Total replay budget, including preparation (default: 1800)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout_s) or args.timeout_s <= 30:
        parser.error("--timeout-s must be finite and greater than 30 seconds")
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Refusing to overwrite existing output: {output}")
    if output.is_relative_to(repo / "src"):
        parser.error("Output must be outside src so the source snapshot cannot copy itself")
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    began = time.monotonic()
    deadline = began + args.timeout_s
    receipt = {"schema_version": 1, "scope": "automatic_synthetic_cli_integration",
        "started_utc": utc_now(), "stage": "preparation", "total_budget_s": args.timeout_s,
        "limitations": list(LIMITATIONS), "stages": [], "passed": False,
        "supported_decision": False, "top_candidate_within_100m": None,
        "automatic_cli_verified": False, "http_upload_verified": False,
        "independent_real_accuracy_verified": False, "national_real_coverage_verified": False,
        "evaluation_truth_loaded_after_analysis": False}

    def save():
        write_json(output / "acceptance.json", receipt)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 15:
            raise TimeoutError("Total automatic replay budget exhausted; preserving partial evidence")
        return seconds

    def run_stage(name, command, *, cap=None, allow_failure=False):
        receipt["stage"] = name
        save()
        limit = min(remaining() - 10, cap) if cap is not None else remaining() - 10
        execution = _HELPERS.execute(command, snapshot, output / "logs" / f"{name}.log", env, limit)
        receipt["stages"].append({"stage": name, "execution": execution})
        save()
        if not allow_failure and (execution.get("returncode") != 0 or execution.get("timed_out")):
            raise RuntimeError(f"{name} failed; inspect logs/{name}.log")
        return execution

    save()
    try:
        snapshot, receipt["implementation"] = snapshot_implementation(repo, output)
        require_components(snapshot)
        receipt["runtime"] = _HELPERS.runtime_record()
        env = os.environ.copy()
        env.update(_HELPERS.THREAD_ENV)
        env["PYTHONPATH"] = str(snapshot / "src")
        env["MPLBACKEND"] = "Agg"
        runner = snapshot / "ci_automatic_replay.py"
        run_stage("producer-preflight", [sys.executable, str(runner), "_preflight", "--snapshot", str(snapshot),
                    "--report", str(output / "preflight.json")], cap=90)

        generator = output / "generated/scripts/make_synthetic_cases.py"
        generator.parent.mkdir(parents=True)
        shutil.copy2(snapshot / "scripts/make_synthetic_cases.py", generator)
        receipt["generator_source"] = file_record(generator)
        run_stage("generation", [sys.executable, str(generator)], cap=240)
        fixture = generator.parent.parent / "data/synthetic"
        evaluation = output / "evaluation"
        evaluation.mkdir()
        truth_path = evaluation / "truth.json"
        # Relocate truth and manual settings without parsing or hashing them.
        (fixture / "truth.json").replace(truth_path)
        for name in ("two-events.json", "known-time-minute.json", "types.csv"):
            (fixture / name).replace(evaluation / name)
        csv_path = fixture / "tracks.csv"
        labeled_csv = evaluation / "labeled-tracks.csv"
        csv_path.replace(labeled_csv)
        mapping_path = evaluation / "flight-id-mapping.json"
        receipt["complete_trajectory_inventory"] = anonymize_trajectories(labeled_csv, csv_path, mapping_path)
        receipt["trajectory_ids_anonymized"] = True
        receipt["all_trajectory_rows_preserved"] = True
        parquet = fixture / "tracks.parquet"
        index = fixture / "synthetic.sqlite"
        run_stage("indexing", [sys.executable, str(runner), "_index", "--csv", str(csv_path),
                    "--parquet", str(parquet), "--index", str(index), "--report", str(output / "indexing.json")], cap=240)
        receipt["indexing"] = read_json(output / "indexing.json")

        mp3 = fixture / "recording.mp3"
        run_stage("mp3-encoding", ["ffmpeg", "-nostdin", "-v", "error", "-i", str(fixture / "recording.wav"),
                    "-codec:a", "libmp3lame", "-ar", "8000", "-b:a", "32k", str(mp3)], cap=240)
        receipt["audio_sources"] = [file_record(fixture / "recording.wav"), file_record(mp3)]
        operator = operator_configuration(index)
        operator_path = output / "operator-synthetic.json"
        write_json(operator_path, operator)
        write_json(output / "normal-request.json", normal_request(mp3))
        receipt["operator_configuration"] = file_record(operator_path)
        jobs = output / "jobs"
        job_budget = remaining() - 30
        if job_budget <= 0:
            raise TimeoutError("Insufficient remaining budget for an automatic job and cleanup")
        stop_observer = threading.Event()
        observation_warnings = []
        observer_path = output / "job-status-history.jsonl"
        observer = threading.Thread(target=observe_job_states,
            args=(jobs, observer_path, stop_observer, observation_warnings), daemon=True)
        observer.start()
        try:
            analysis = run_stage("automatic-cli", [sys.executable, "-m", "aircraft_geoloc.cli", "analyze", str(mp3),
                "--jobs", str(jobs), "--config", str(operator_path), "--start-utc", recording_start_utc(),
                "--end-utc", recording_start_utc(), "--time-source", TIME_SOURCE,
                "--max-runtime", str(job_budget)], cap=job_budget + 10, allow_failure=True)
        finally:
            stop_observer.set()
            observer.join(timeout=5)
            receipt["job_status_observation"] = {"path": str(observer_path), "interval_s": 0.2,
                "may_miss_short_stages": True, "observer_stopped": not observer.is_alive(),
                "warnings": observation_warnings}
        receipt["analysis_terminated_utc"] = utc_now()
        result, receipt["job"] = collect_job(jobs, mp3, operator, receipt["implementation"]["expected_automatic_files"])
        receipt["supported_decision"] = result.get("status") == "succeeded"
        save()
        if not ready_for_evaluation(result, analysis):
            raise RuntimeError("The automatic CLI did not exit cleanly with a terminal job; evaluation truth remains unopened")

        # The pipeline has terminated. Only now can the evaluator open truth.
        receipt["stage"] = "evaluation"
        truth = read_json(truth_path)
        receipt["evaluation_truth_loaded_after_analysis"] = True
        receipt["evaluation_truth_loaded_utc"] = utc_now()
        receipt["evaluation_reference"] = file_record(truth_path)
        mapping_record = read_json(mapping_path)
        mapped_truth = dict(truth, flight_ids=evaluation_flight_ids(truth, mapping_record))
        receipt["evaluation_identity_mapping"] = file_record(mapping_path)
        evaluations = evaluate_candidates(result, mapped_truth, deadline=deadline - 5)
        receipt["candidate_evaluations"] = evaluations
        outcome = assess_outcome(result, evaluations, receipt["job"]["checks"], analysis)
        receipt.update(outcome)
        receipt["automatic_cli_verified"] = outcome["passed"]
        receipt["stage"] = "complete"
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        receipt.update(finished_utc=utc_now(), elapsed_s=time.monotonic() - began)
        save()
        try:
            manifest = artifact_inventory(output, receipt["evaluation_truth_loaded_after_analysis"])
            write_json(output / "artifact-manifest.json", {"files": manifest,
                "excludes": ["acceptance.json", "artifact-manifest.json"],
                "evaluation_files_included": receipt["evaluation_truth_loaded_after_analysis"]})
        except OSError as exc:
            receipt["artifact_inventory_error"] = f"{type(exc).__name__}: {exc}"
            receipt["passed"] = False
            save()
    print(json.dumps({"acceptance": str(output / "acceptance.json"), "passed": receipt["passed"],
        "status": receipt.get("job", {}).get("status"), "supported_decision": receipt["supported_decision"],
        "top_candidate_within_100m": receipt["top_candidate_within_100m"], "error": receipt.get("error")}, indent=2))
    return 0 if receipt["passed"] else 1


def child_stage(argv):
    parser = argparse.ArgumentParser(description="Internal real preflight/index stage")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("_preflight")
    check.add_argument("--snapshot", required=True, type=Path)
    check.add_argument("--report", required=True, type=Path)
    index = sub.add_parser("_index")
    for name in ("csv", "parquet", "index", "report"):
        index.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "_preflight":
            preflight(args.snapshot, args.report)
        else:
            prepare_index(args.csv, args.parquet, args.index, args.report)
    except Exception as exc:
        write_json(args.report, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    return 0


if __name__ == "__main__":
    arguments = sys.argv[1:]
    raise SystemExit(child_stage(arguments) if arguments and arguments[0].startswith("_") else main(arguments))
