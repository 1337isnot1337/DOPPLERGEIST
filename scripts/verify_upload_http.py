#!/usr/bin/env python3
"""Verify an actual local MP3 upload without a browser.

Exit zero means HTTP, persistence, stage evidence, and outcome checks passed.
The receipt separately preserves the producer's scientific status. An expected
inconclusive response is never counted as supported localization or accuracy.
The existing browser verifier is independent and remains unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

import aircraft_geoloc
from aircraft_geoloc.contracts import utc_timestamp, validate_recording, validate_request, validate_result
from aircraft_geoloc.jobs import TERMINAL, write_json


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("HTTP verification exceeded its declared time budget")
    return value


class VerificationInterrupted(InterruptedError):
    """An outer termination request must unwind through service cleanup."""


class TerminationGuard:
    def __init__(self, receipt):
        self.receipt = receipt
        self.received_monotonic = None
        self.interruptible = False
        self.previous = None
        self.installed = False

    def __enter__(self):
        # Only the main thread can install handlers. The CLI always uses it.
        if threading.current_thread() is threading.main_thread():
            self.previous = signal.signal(signal.SIGTERM, self.handle)
            self.installed = True
        self.receipt["sigterm_cleanup_handler_installed"] = self.installed
        return self

    def __exit__(self, *_):
        if self.installed:
            signal.signal(signal.SIGTERM, self.previous)

    def handle(self, signum, _frame):
        if self.received_monotonic is not None:
            return  # Repeated signals must not interrupt teardown.
        self.received_monotonic = time.monotonic()
        self.receipt.update(interrupted=True, interruption_signal=signal.Signals(signum).name,
                            interruption_received_utc=now(), verification_passed=False,
                            supported_decision=False)
        if self.interruptible:
            self.raise_if_interrupted()

    def raise_if_interrupted(self):
        if self.received_monotonic is not None:
            raise VerificationInterrupted("HTTP verification interrupted by SIGTERM")


def stop_service(process, receipt, termination):
    """Leave time to write a receipt before the outer helper's 5 s kill grace."""
    if process is None:
        return
    service = receipt["service"]
    if process.poll() is None:
        service.update(shutdown_signal="SIGINT", shutdown_requested_utc=now())
        try:
            process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 10
        while process.poll() is None:
            # JobManager allows 3 s to stop its active worker. A SIGTERM can
            # arrive during ordinary shutdown, so reconsider this bound often.
            if termination.received_monotonic is not None:
                deadline = min(deadline, termination.received_monotonic + 3.5)
            left = deadline - time.monotonic()
            if left <= 0:
                service["forced_kill"] = True
                process.kill()
                killed = time.monotonic()
                reap_deadline = killed + 5
                while process.poll() is None:
                    if termination.received_monotonic is not None:
                        reap_deadline = min(reap_deadline, killed + 0.5,
                                            termination.received_monotonic + 4.0)
                    reap_left = reap_deadline - time.monotonic()
                    if reap_left <= 0:
                        raise subprocess.TimeoutExpired(process.args, max(0, reap_deadline - killed))
                    try:
                        process.wait(timeout=min(0.05, reap_left))
                    except subprocess.TimeoutExpired:
                        pass
                break
            try:
                process.wait(timeout=min(0.05, left))
            except subprocess.TimeoutExpired:
                pass
    service.update(returncode=process.returncode, stopped_utc=now())


class LocalClient:
    """Direct loopback HTTP; proxy environment variables are not consulted."""

    def __init__(self, port, deadline):
        self.port, self.deadline = port, deadline

    def request(self, method, path, *, body=None, headers=None, destination=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port,
                                                timeout=min(30, remaining(self.deadline)))
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            if destination is not None:
                with Path(destination).open("xb") as target:
                    while block := response.read(1024 * 1024):
                        remaining(self.deadline)
                        target.write(block)
                return response.status, None
            payload = response.read(64 * 1024 * 1024 + 1)
            if len(payload) > 64 * 1024 * 1024:
                raise ValueError("HTTP JSON response exceeds the verifier's 64 MiB limit")
            return response.status, json.loads(payload)
        finally:
            connection.close()

    def get(self, path):
        code, value = self.request("GET", path)
        if code != 200:
            raise RuntimeError(f"GET {path} returned HTTP {code}")
        return value


def wait_for_service(process, log_path, deadline):
    while True:
        if process.poll() is not None:
            raise RuntimeError("Upload service exited during startup; inspect service.log")
        match = re.search(r"DOPPLERGEIST: http://127\.0\.0\.1:(\d+) ", log_path.read_text())
        if match:
            return LocalClient(int(match.group(1)), deadline)
        time.sleep(min(0.05, remaining(deadline)))


def poll_job(client, job_id, history_path, *, interval_s):
    with history_path.open("x") as history:
        previous = None
        while True:
            value = client.get(f"/api/jobs/{job_id}")
            validate_result(value)
            if value["job_id"] != job_id:
                raise ValueError("Polled result belongs to a different job")
            if value != previous:
                history.write(json.dumps({"observed_utc": now(), "result": value}, allow_nan=False) + "\n")
                history.flush()
                previous = value
            if value["status"] in TERMINAL:
                return value
            time.sleep(min(interval_s, remaining(client.deadline)))


def inspect_job(directory, final, wire, operator, original, implementation):
    """Check actual persisted evidence without changing it or opening truth."""
    read = lambda path: json.loads((directory / path).read_text())
    input_record, stored_request = read("input.json"), read("request.json")
    if input_record != {"sha256": sha256(original), "bytes": original.stat().st_size, "path": "input.mp3"}:
        raise ValueError("Persisted input receipt does not describe the submitted bytes")
    if sha256(directory / "input.mp3") != input_record["sha256"]:
        raise ValueError("Persisted original differs from the submitted MP3")
    uploaded = Path(stored_request.pop("audio_path"))
    if uploaded != directory / "input.mp3" or stored_request != wire:
        raise ValueError("Persisted request differs from the submitted request")
    if read("operator.json") != operator:
        raise ValueError("Persisted operator configuration differs from the submitted configuration")
    if read("result.json") != final:
        raise ValueError("Persisted terminal result differs from the HTTP result")
    provenance = read("provenance.json")
    if (provenance.get("source_sha256") != input_record["sha256"]
            or provenance.get("implementation_files") != implementation):
        raise ValueError("Automatic provenance does not identify the submitted input and executed source")
    if final.get("recording", {}).get("source_sha256", input_record["sha256"]) != input_record["sha256"]:
        raise ValueError("Decoded recording identifies a different source")
    return {"original_preserved": True, "request_preserved": True,
            "operator_preserved": True, "result_preserved": True,
            "automatic_provenance_verified": True}


def inspect_pipeline_evidence(directory, final, wire, operator):
    """Check stage receipts, separately from HTTP success or location accuracy.

    A completed scientific decision needs every upstream stage. Early exits need
    the stages they reached; a work limit must not pretend to be a complete run.
    This checks persisted evidence and repeats the decision policy, not decoding,
    trajectory fitting, data acquisition, or comparison with withheld truth.
    """
    directory = Path(directory).resolve()
    scientific = (final.get("status") == "succeeded" or "candidates" in final
        or (final.get("status") == "inconclusive" and final.get("reason_code")
            not in {"no_supported_events", "data_unavailable", "work_limit"}))
    report = {"schema_version": 1, "passed": False, "full_pipeline_observed": False,
        "scientific_decision_expected": scientific, "stages_verified": [], "artifacts": {},
        "errors": [], "location_accuracy_evaluated": False,
        "limitations": ["Stage consistency does not independently reproduce decoding or scientific fitting.",
                        "No withheld-location comparison or accuracy evaluation is performed."]}

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def artifact(name):
        path = directory / name
        require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)
                if p != directory and directory in p.parents), f"Missing or unsafe stage artifact: {name}")
        require(path.resolve().is_relative_to(directory), f"Stage artifact leaves the job: {name}")
        report["artifacts"][name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        return path

    def read(name):
        def reject_constant(value):
            raise ValueError(f"Nonfinite JSON constant in {name}: {value}")
        value = json.loads(artifact(name).read_text(), parse_constant=reject_constant)
        require(isinstance(value, dict), f"Stage artifact must be a JSON object: {name}")
        return value

    try:
        validate_result(final)
        provenance, input_record = read("provenance.json"), read("input.json")
        request = dict(wire, audio_path=str(directory / "input.mp3"))
        require(read("request.json") == request and provenance.get("request") == request,
                "Automatic provenance does not preserve the submitted request")
        operator_hash = hashlib.sha256(json.dumps(operator, sort_keys=True, allow_nan=False).encode()).hexdigest()
        require(provenance.get("operator_configuration_sha256") == operator_hash,
                "Automatic provenance has a different operator configuration")
        require(provenance.get("source_sha256") == input_record.get("sha256"),
                "Automatic provenance has a different source hash")
        require(provenance.get("ground_truth_used_by_search") is False
                and provenance.get("event_selection") == "automatic_whole_recording",
                "Automatic event selection and truth separation are not recorded")
        interrupted = (final["status"] == "cancelled" or final.get("reason_code") in
                       {"work_limit", "worker_exit", "worker_launch", "processing_error"})
        if not interrupted:
            require(provenance.get("status") == final["status"]
                    and provenance.get("coverage") == final.get("coverage"),
                    "Automatic provenance does not match the terminal status and coverage")
        report["stages_verified"].append("automatic_provenance")

        recording = None
        if scientific or "recording" in final:
            recording = validate_recording(read("intake/recording.json"))
            intake = read("intake/intake.json")
            require(recording == final.get("recording"), "Intake recording differs from the terminal recording")
            require(recording["source_sha256"] == input_record["sha256"], "Intake identifies a different source")
            require(recording.get("time_window") == wire.get("time_window"), "Intake changed the recording clock")
            count = intake.get("sample_count")
            require(type(count) is int and count > 0 and recording["channels"] == 1,
                    "Intake sample count or mono channel evidence is invalid")
            require(artifact("intake/recording.f32").stat().st_size == 4 * count,
                    "Decoded cache size does not match the intake sample count")
            require(math.isclose(recording["duration_s"], count / recording["sample_rate_hz"],
                                 rel_tol=1e-12, abs_tol=1e-12), "Intake duration does not match its sample count")
            require(intake.get("time_status") == ("ready" if wire.get("time_window") else "needs_input"),
                    "Intake time status does not match the submitted clock")
            require(intake.get("decode", {}).get("sample_format") == "f32le", "Decoded cache format is unrecorded")
            report["stages_verified"].append("intake")

        events = final.get("events")
        if scientific or events is not None:
            require(recording is not None, "Discovery has no completed intake evidence")
            discovery = read("discovery/discovery.json")
            require(discovery.get("source_sha256") == input_record["sha256"]
                    and discovery.get("events") == events, "Discovery source or events differ from the terminal result")
            if not interrupted:
                require(provenance.get("discovered_events") == len(events), "Provenance has a different discovered-event count")
            chunks = discovery.get("chunks")
            require(isinstance(chunks, list) and chunks, "Discovery has no whole-recording chunk evidence")
            covered = 0.0
            tolerance = 1 / recording["sample_rate_hz"]
            for chunk in sorted(chunks, key=lambda item: item["start_s"]):
                start, duration = chunk["start_s"], chunk["duration_s"]
                require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                            for v in (start, duration)) and start >= 0 and duration > 0,
                        "Discovery chunk bounds are invalid")
                require(start <= covered + tolerance and start + duration <= recording["duration_s"] + tolerance,
                        "Discovery chunk evidence has a gap or exceeds the recording")
                covered = max(covered, start + duration)
            require(covered >= recording["duration_s"] - tolerance, "Discovery did not cover the complete recording")
            report["stages_verified"].append("discovery")

        if final.get("reason_code") == "recording_time_required":
            require(recording is not None and events is not None and not wire.get("time_window")
                    and final["status"] == "needs_input" and final.get("required_fields") == ["time_window"],
                    "Recording-time early exit contradicts its intake evidence")
        if final.get("reason_code") == "no_supported_events":
            require(recording is not None and events == [] and wire.get("time_window") is not None,
                    "No-event early exit contradicts its discovery evidence")

        if scientific:
            require(recording.get("time_window") is not None, "Scientific decision has no recording clock")
            acquisition = read("data-provenance.json")
            manifest, search = read("search/manifest.json"), read("search/search-report.json")
            configuration = manifest["configuration"]
            run_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True, allow_nan=False).encode()).hexdigest()
            require(manifest.get("run_hash") == search.get("run_hash") == provenance.get("search_run_hash") == run_hash,
                    "Search manifest, report, and automatic provenance have different run identities")
            require(configuration.get("code") == provenance.get("implementation_files"),
                    "Search manifest identifies a different implementation")
            bounds = wire["search"].get("bounds_wsen", [-125.0, 24.0, -66.0, 50.0])
            require(configuration.get("bounds") == search.get("scope") == bounds,
                    "Search scope differs from the submitted request")
            window = [utc_timestamp(wire["time_window"][key]).timestamp() for key in ("start_utc", "end_utc")]
            require(configuration.get("scoring", {}).get("recording_start_window_s") == window
                    and search.get("scoring_time_is_locked") is True
                    and search.get("ground_truth_used_by_search") is False,
                    "Search does not preserve one truth-separated recording clock")
            indexes = acquisition.get("flight_indexes")
            require(isinstance(indexes, list) and indexes and isinstance(acquisition.get("terrain"), dict)
                    and acquisition["terrain"], "Acquisition lacks flight-index or terrain evidence")
            require([index["input_hash"] for index in indexes] ==
                    [index["input_hash"] for index in configuration["indexes"]] ==
                    [item["input_hash"] for item in search["data_coverage"]],
                    "Acquisition and search use different flight inputs")
            require([index["coverage"] for index in indexes] ==
                    [item["source"] for item in search["data_coverage"]],
                    "Acquisition and search disagree about flight coverage")
            require(all(item.get("requested_bounds") == bounds and item.get("requested_time_range_s") ==
                        configuration.get("time_range_s") for item in search["data_coverage"]),
                    "Flight-coverage receipts describe another search area or time interval")
            if "terrain_configuration" in acquisition["terrain"]:
                require(acquisition["terrain"] == configuration.get("additional_input_hashes"),
                        "Acquisition and search use different terrain inputs")
            report["stages_verified"].append("acquisition")

            total, completed = search["tiles_total"], search["tiles_completed"]
            require(type(total) is int and type(completed) is int and 0 <= completed <= total and total > 0,
                    "Search tile counts are invalid")
            require(search.get("unsearched_tiles") == total - completed, "Search unsearched-tile count is inconsistent")
            work_complete = completed == total and not search["tile_failures"] and not search.get("refinement_failure")
            coverage = final["coverage"]
            require(coverage["search_complete"] == work_complete
                    and coverage["data_status"] == ("available" if search["data_scope_complete"] else "partial")
                    and coverage.get("requested_area") == wire["search"],
                    "Terminal coverage differs from the search report")
            expected_complete = work_complete and search["data_scope_complete"] and search["all_event_groups_considered"]
            require(search["status"] == ("complete" if expected_complete else "partial"),
                    "Search completion status contradicts its work and coverage evidence")
            prepared = configuration["events"]
            groups = [event.get("event_ids", [event["event_id"]]) for event in prepared]
            flattened = [event_id for group in groups for event_id in group]
            require(len(flattened) == len(set(flattened)) and set(flattened) == {event["event_id"] for event in events},
                    "Search grouping omits or duplicates discovered events")
            require(search.get("event_groups_proposed") == len(groups), "Search reports a different event-group count")
            report["stages_verified"].append("search")

            refinement = read("refined-candidates.json")
            candidates, rows = final.get("candidates"), refinement.get("ranked")
            require(isinstance(candidates, list) and isinstance(rows, list) and len(rows) == len(candidates),
                    "Refinement and terminal candidate counts differ")
            for row, candidate in zip(rows, candidates):
                require(all(row.get(key) == candidate[key] for key in ("lat", "lon", "score"))
                        and row.get("score_kind", "negative_robust_ridge_loss_hz") == candidate["score_kind"],
                        "Refinement and terminal candidate coordinates or scores differ")
                require(math.isclose(row["recording_start_time_s"], utc_timestamp(candidate["recording_start_utc"]).timestamp(),
                                     rel_tol=0, abs_tol=1e-6), "Refinement and terminal candidate clocks differ")
                indices = row.get("event_indices", list(range(len(groups))))
                require(isinstance(indices, list) and all(type(i) is int and 0 <= i < len(groups) for i in indices)
                        and len(indices) == len(set(indices)) == len(row["flight_ids"]),
                        "Refinement event-to-flight association is invalid")
                associated = [(event_id, flight) for i, flight in zip(indices, row["flight_ids"]) for event_id in groups[i]]
                require(associated == list(zip(candidate["event_ids"], candidate["flight_ids"])),
                        "Refinement and terminal event-to-flight associations differ")
                sensitivity = row.get("sensitivity", {})
                uncertainty = ({key: sensitivity[key] for key in ("radius_m", "method", "kind")}
                               if sensitivity.get("complete") and not sensitivity.get("boundary_limited") else None)
                require(candidate.get("uncertainty") == uncertainty, "Candidate uncertainty differs from its sensitivity evidence")
            diagnostics = refinement["matching_diagnostics"]
            require(diagnostics.get("recording_start_window_s") == window
                    and diagnostics.get("clock_locked") == search["scoring_time_is_locked"],
                    "Refinement changed the shared recording clock")
            require(diagnostics.get("sensitivity") == (rows[0].get("sensitivity", {}) if rows else {}),
                    "Leading matching diagnostics use another candidate's sensitivity")
            if rows:
                best = rows[0]
                selected = best.get("event_indices", list(range(len(groups))))
                fits = best.get("event_diagnostics", [])
                require(len(fits) == len(selected), "Leading refinement lacks per-event fit evidence")
                require(all(diagnostics.get(event_id) == fit for i, fit in zip(selected, fits) for event_id in groups[i]),
                        "Matching diagnostics differ from the leading candidate's event fits")
                require(set(diagnostics.get("unmatched_event_ids", [])) ==
                        {event["event_id"] for event in events} - set(candidates[0]["event_ids"]),
                        "Matching diagnostics do not account for unmatched acoustic proposals")
            report["stages_verified"].append("refinement")

            decision = read("decision.json")
            require(all(decision.get(key) == final.get(key) for key in ("status", "reason_code", "message", "candidates")),
                    "Persisted scientific decision differs from the terminal result")
            from aircraft_geoloc import confidence
            require(sha256(confidence.__file__) == provenance["implementation_files"].get("confidence.py"),
                    "Cannot recheck the decision with a different confidence implementation")
            expected = confidence.decide_location(events, candidates, coverage, matching_diagnostics=diagnostics)
            require(decision == dict(expected, candidates=candidates),
                    "Saved scientific evidence does not reproduce the persisted decision")
            report["stages_verified"].append("decision")
            report["full_pipeline_observed"] = True
        report["passed"] = True
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    return report


def verify_http(audio, output, *, request=None, operator=None, expect_status,
                expect_reason=None, timeout_s=600.0, poll_interval_s=0.25):
    if expect_status not in TERMINAL:
        raise ValueError("Declare an expected terminal status before execution")
    for name, value in (("timeout_s", timeout_s), ("poll_interval_s", poll_interval_s)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    audio = Path(audio).resolve(strict=True)
    if audio.suffix.lower() != ".mp3" or not audio.is_file():
        raise ValueError("Supply a local MP3 file")
    wire = dict(validate_request(dict(request or {"schema_version": 1}, audio_path=str(audio))))
    wire.pop("audio_path")
    operator = {} if operator is None else operator
    if not isinstance(operator, dict):
        raise ValueError("Operator configuration must be a JSON object")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "upload-request.json", wire)
    write_json(output / "operator.json", operator)
    package = Path(aircraft_geoloc.__file__).resolve().parent
    implementation = {path.name: sha256(path) for path in sorted(package.glob("*.py"))}
    began, process, final, log = time.monotonic(), None, None, None
    deadline = began + timeout_s
    receipt = {"schema_version": 1, "scope": "actual_local_http_upload_verification",
        "started_utc": now(), "expected_status": expect_status, "expected_reason": expect_reason,
        "timeout_s": timeout_s, "source_sha256": sha256(audio), "source_bytes": audio.stat().st_size,
        "request": wire, "implementation_files": implementation, "verifier_sha256": sha256(__file__),
        "python_executable": sys.executable, "python_version": sys.version,
        "verification_passed": False, "http_checks_passed": False, "pipeline_evidence_passed": False,
        "full_pipeline_observed": False, "supported_decision": False,
        "location_accuracy_evaluated": False, "browser_verified": False,
        "interrupted": False, "interruption_signal": None,
        "limitations": ["HTTP verification does not establish location accuracy or browser behavior.",
                       "Expected inconclusive or failed responses are preserved, not promoted to localization success.",
                       "This verifier accepts no evaluation labels and performs no ground-truth comparison."],
        "service": {"shutdown_signal": None, "forced_kill": False, "returncode": None}}
    with TerminationGuard(receipt) as termination:
        try:
            termination.interruptible = True
            termination.raise_if_interrupted()
            command = [sys.executable, "-m", "aircraft_geoloc.cli", "serve", "--port", "0",
                       "--jobs", str(output / "jobs"), "--config", str(output / "operator.json"),
                       "--max-runtime", str(timeout_s)]
            receipt["service"]["command"] = command
            env = dict(os.environ, PYTHONPATH=str(package.parent) + os.pathsep + os.environ.get("PYTHONPATH", ""),
                       MPLBACKEND="Agg")
            log = (output / "service.log").open("wb")
            termination.interruptible = False
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            receipt["service"]["pid"] = process.pid
            termination.interruptible = True
            termination.raise_if_interrupted()
            client = wait_for_service(process, output / "service.log", deadline)
            receipt["service"]["port"] = client.port
            write_json(output / "capabilities.json", client.get("/api/capabilities"))
            with audio.open("rb") as stream:
                code, queued = client.request("POST", "/api/jobs", body=stream, headers={
                    "Content-Type": "application/octet-stream", "Content-Length": str(audio.stat().st_size),
                    "X-Filename": "input.mp3", "X-Dopplergeist-Request": json.dumps(wire)})
            write_json(output / "submission.json", {"http_status": code, "response": queued})
            if code != 202:
                raise RuntimeError(f"Upload returned HTTP {code}")
            validate_result(queued)
            job_id = queued["job_id"]
            if uuid.UUID(job_id).hex != job_id:
                raise ValueError("Service returned an invalid job identifier")
            receipt["job_id"] = job_id
            final = poll_job(client, job_id, output / "history.jsonl", interval_s=poll_interval_s)
            write_json(output / "result.json", final)
            receipt.update(status=final["status"], reason_code=final.get("reason_code"),
                           producer_reported_success=final["status"] == "succeeded",
                           candidate_count=len(final.get("candidates", [])), event_count=len(final.get("events", [])))
            listing = client.get(f"/api/jobs/{job_id}/artifacts")
            write_json(output / "artifacts.json", listing)
            if sum(item["path"] == "input.mp3" for item in listing["artifacts"]) != 1:
                raise ValueError("Artifact listing does not expose exactly one original MP3")
            code, _ = client.request("GET", f"/api/jobs/{job_id}/artifacts/input.mp3",
                                     destination=output / "downloaded-original.mp3")
            if code != 200 or sha256(output / "downloaded-original.mp3") != receipt["source_sha256"]:
                raise ValueError("Downloaded original differs from the submitted MP3")
            if client.get(f"/api/jobs/{job_id}/artifacts/result.json") != final:
                raise ValueError("Downloaded result artifact differs from the terminal HTTP result")
            receipt["checks"] = inspect_job(output / "jobs" / job_id, final, wire, operator, audio, implementation)
            receipt["checks"].update(downloaded_original_verified=True, downloaded_result_verified=True)
            receipt["http_checks_passed"] = True
            receipt["expectation_matched"] = (final["status"] == expect_status
                and (expect_reason is None or final.get("reason_code") == expect_reason))
        except Exception as exc:
            receipt["error"] = f"{type(exc).__name__}: {exc}"
            receipt["timed_out"] = isinstance(exc, TimeoutError)
        finally:
            termination.interruptible = False
            try:
                stop_service(process, receipt, termination)
            except Exception as exc:
                receipt["shutdown_error"] = f"{type(exc).__name__}: {exc}"
            finally:
                if log is not None:
                    log.close()
            try:
                if not receipt["interrupted"]:
                    termination.interruptible = True
                    termination.raise_if_interrupted()
                    receipt["implementation_unchanged"] = implementation == {
                        path.name: sha256(path) for path in sorted(package.glob("*.py"))}
                    if final is not None:
                        directory = output / "jobs" / final["job_id"]
                        receipt["terminal_result_preserved_after_shutdown"] = json.loads((directory / "result.json").read_text()) == final
                        evidence = inspect_pipeline_evidence(directory, final, wire, operator)
                        termination.raise_if_interrupted()
                        write_json(output / "pipeline-evidence.json", evidence)
                        receipt["pipeline_evidence_passed"] = evidence["passed"]
                        receipt["full_pipeline_observed"] = evidence["full_pipeline_observed"]
                        receipt["pipeline_evidence_errors"] = evidence["errors"]
                        files = {path.relative_to(directory).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
                                 for path in sorted(directory.rglob("*")) if path.is_file() and not path.is_symlink()}
                        receipt["pipeline_evidence_preserved_after_inspection"] = all(
                            files.get(name) == record for name, record in evidence["artifacts"].items())
                        write_json(output / "job-manifest.json", {"job_id": final["job_id"], "files": files})
                    verified = bool(receipt["http_checks_passed"] and receipt["pipeline_evidence_passed"]
                        and receipt.get("pipeline_evidence_preserved_after_inspection") and receipt["implementation_unchanged"]
                        and receipt.get("terminal_result_preserved_after_shutdown")
                        and receipt["service"]["returncode"] == 0 and not receipt["service"]["forced_kill"]
                        and not receipt.get("shutdown_error") and not receipt["interrupted"])
                    receipt["verification_passed"] = verified and bool(receipt.get("expectation_matched"))
                    receipt["supported_decision"] = (verified and receipt["full_pipeline_observed"]
                                                     and receipt.get("status") == "succeeded")
            except Exception as exc:
                receipt["finalization_error"] = f"{type(exc).__name__}: {exc}"
            termination.interruptible = False
    # The bounded cleanup attempt precedes this handler handoff. Signals handled
    # above are committed below; later signals use the caller's disposition.
    # In the CLI, a later default SIGTERM cannot yield a successful process exit.
    if receipt["interrupted"]:
        receipt.update(verification_passed=False, supported_decision=False,
                       finalization_skipped_reason="verification_interrupted")
        receipt.setdefault("error", "VerificationInterrupted: HTTP verification interrupted by SIGTERM")
    receipt.update(finished_utc=now(), elapsed_s=time.monotonic() - began)
    write_json(output / "http-verification.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing evidence is never overwritten")
    parser.add_argument("--operator-config", type=Path)
    parser.add_argument("--start-utc")
    parser.add_argument("--end-utc")
    parser.add_argument("--time-source", default="Explicit verification recording-start window")
    parser.add_argument("--expect-status", choices=sorted(TERMINAL), required=True)
    parser.add_argument("--expect-reason")
    parser.add_argument("--timeout-s", type=float, default=600)
    parser.add_argument("--poll-interval-s", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.end_utc and not args.start_utc:
        parser.error("--end-utc requires --start-utc")
    request = {"schema_version": 1, "search": {"coverage": "conus"}}
    if args.start_utc:
        request["time_window"] = {"start_utc": args.start_utc, "end_utc": args.end_utc or args.start_utc,
                                  "source": "user", "source_detail": args.time_source}
    try:
        operator = json.loads(args.operator_config.read_text()) if args.operator_config else {}
        receipt = verify_http(args.audio, args.output, request=request, operator=operator,
            expect_status=args.expect_status, expect_reason=args.expect_reason,
            timeout_s=args.timeout_s, poll_interval_s=args.poll_interval_s)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"report": str(args.output.resolve() / "http-verification.json"),
                      "verification_passed": receipt["verification_passed"], "status": receipt.get("status"),
                      "http_checks_passed": receipt["http_checks_passed"],
                      "pipeline_evidence_passed": receipt["pipeline_evidence_passed"],
                      "full_pipeline_observed": receipt["full_pipeline_observed"],
                      "reason_code": receipt.get("reason_code"), "supported_decision": receipt["supported_decision"],
                      "location_accuracy_evaluated": False, "interrupted": receipt["interrupted"],
                      "interruption_signal": receipt["interruption_signal"], "error": receipt.get("error")}))
    return 0 if receipt["verification_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
