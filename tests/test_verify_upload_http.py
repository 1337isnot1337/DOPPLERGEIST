"""Real MP3 uploads through the actual HTTP service and analysis subprocess."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from copy import deepcopy
import sqlite3

import numpy as np
import pytest
import soundfile as sf


SPEC = importlib.util.spec_from_file_location("verify_upload_http",
    Path(__file__).parents[1] / "scripts/verify_upload_http.py")
HTTP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HTTP)
CLOCK = "2026-09-21T14:13:20Z"


@pytest.fixture(scope="module")
def mp3(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("The real MP3 test requires ffmpeg and ffprobe")
    root = tmp_path_factory.mktemp("http-audio")
    rate = 8000
    time = np.arange(rate * 8) / rate
    wave = 0.2 * np.sin(2 * np.pi * 200 * time)
    sf.write(root / "stationary.wav", wave, rate)
    target = root / "stationary.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(root / "stationary.wav"),
                    "-codec:a", "libmp3lame", str(target)], check=True)
    return target


def test_actual_mp3_missing_clock_preserves_exact_bytes_and_stops_cleanly(tmp_path, mp3):
    previous_handler = signal.getsignal(signal.SIGTERM)
    receipt = HTTP.verify_http(mp3, tmp_path / "run", expect_status="needs_input",
        expect_reason="recording_time_required", timeout_s=60, poll_interval_s=0.05)
    assert signal.getsignal(signal.SIGTERM) == previous_handler
    assert receipt["interrupted"] is False
    assert receipt["verification_passed"], receipt
    assert receipt["pipeline_evidence_passed"] is True
    assert receipt["full_pipeline_observed"] is False
    assert receipt["status"] == "needs_input"
    assert receipt["supported_decision"] is False
    assert receipt["location_accuracy_evaluated"] is False
    assert receipt["browser_verified"] is False
    assert receipt["service"]["shutdown_signal"] == "SIGINT"
    assert receipt["service"]["returncode"] == 0
    assert receipt["service"]["forced_kill"] is False
    assert (tmp_path / "run/downloaded-original.mp3").read_bytes() == mp3.read_bytes()
    result = json.loads((tmp_path / "run/result.json").read_text())
    assert result["recording"]["source_sha256"] == hashlib.sha256(mp3.read_bytes()).hexdigest()
    manifest = json.loads((tmp_path / "run/job-manifest.json").read_text())
    assert manifest["files"]["input.mp3"]["sha256"] == receipt["source_sha256"]
    assert "intake/recording.json" in manifest["files"]
    assert "discovery/discovery.json" in manifest["files"]
    history = [json.loads(line) for line in (tmp_path / "run/history.jsonl").read_text().splitlines()]
    assert history[-1]["result"] == result


def test_actual_dated_mp3_abstention_remains_inconclusive(tmp_path, mp3):
    request = {"schema_version": 1, "time_window": {
        "start_utc": CLOCK, "end_utc": CLOCK, "source": "user"}}
    receipt = HTTP.verify_http(mp3, tmp_path / "run", request=request,
        expect_status="inconclusive", expect_reason="no_supported_events", timeout_s=60)
    assert receipt["verification_passed"], receipt
    assert receipt["pipeline_evidence_passed"] is True
    assert receipt["full_pipeline_observed"] is False
    assert receipt["status"] == "inconclusive"
    assert receipt["reason_code"] == "no_supported_events"
    assert receipt["supported_decision"] is False
    assert receipt["event_count"] == 0
    directory = tmp_path / "run/jobs" / receipt["job_id"]
    assert not (directory / "search").exists()
    assert json.loads((directory / "result.json").read_text())["status"] == "inconclusive"


def test_unexpected_actual_outcome_fails_verification_without_rewriting_result(tmp_path, mp3):
    receipt = HTTP.verify_http(mp3, tmp_path / "run", expect_status="succeeded", timeout_s=60)
    assert receipt["http_checks_passed"] is True, receipt
    assert receipt["verification_passed"] is False
    assert receipt["expectation_matched"] is False
    assert receipt["status"] == "needs_input"
    assert receipt["supported_decision"] is False
    result = json.loads((tmp_path / "run/result.json").read_text())
    assert result["status"] == "needs_input"
    assert receipt["terminal_result_preserved_after_shutdown"] is True


def test_existing_output_is_not_overwritten(tmp_path, mp3):
    output = tmp_path / "preserved"
    output.mkdir()
    evidence = output / "http-verification.json"
    evidence.write_text("preserve this exact evidence")
    with pytest.raises(FileExistsError):
        HTTP.verify_http(mp3, output, expect_status="needs_input")
    assert evidence.read_text() == "preserve this exact evidence"


def test_manual_event_hints_are_rejected_before_service_start(tmp_path, mp3):
    with pytest.raises(ValueError):
        HTTP.verify_http(mp3, tmp_path / "run", expect_status="needs_input",
                         request={"schema_version": 1, "events": []})
    assert not (tmp_path / "run").exists()


def test_cli_preserves_actual_invalid_media_failure(tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("The real decoder test requires ffmpeg and ffprobe")
    source = tmp_path / "invalid.mp3"
    source.write_bytes(b"This is deliberately not encoded audio.")
    output = tmp_path / "run"
    process = subprocess.run([sys.executable, str(Path(HTTP.__file__)),
        "--audio", str(source), "--output", str(output), "--expect-status", "failed",
        "--expect-reason", "invalid_media", "--timeout-s", "60"],
        capture_output=True, text=True, timeout=75)
    assert process.returncode == 0, (process.stdout, process.stderr)
    summary = json.loads(process.stdout)
    assert summary["verification_passed"] is True
    assert summary["pipeline_evidence_passed"] is True
    assert summary["full_pipeline_observed"] is False
    assert summary["status"] == "failed"
    assert summary["reason_code"] == "invalid_media"
    assert summary["supported_decision"] is False
    assert json.loads((output / "result.json").read_text())["status"] == "failed"
    assert (output / "downloaded-original.mp3").read_bytes() == source.read_bytes()


def test_sigterm_handler_restored_after_launch_failure(tmp_path, monkeypatch):
    source = tmp_path / "input.mp3"
    source.write_bytes(b"No decoder starts in this launch-failure control.")
    previous = signal.getsignal(signal.SIGTERM)
    caller_handler = lambda *_: None
    signal.signal(signal.SIGTERM, caller_handler)
    try:
        def launch_failure(*_, **__):
            raise OSError("deliberate launch failure")
        monkeypatch.setattr(HTTP.subprocess, "Popen", launch_failure)
        receipt = HTTP.verify_http(source, tmp_path / "run", expect_status="needs_input")
        assert signal.getsignal(signal.SIGTERM) is caller_handler
        assert receipt["verification_passed"] is False
        assert receipt["interrupted"] is False
        assert "deliberate launch failure" in receipt["error"]
    finally:
        signal.signal(signal.SIGTERM, previous)


@pytest.mark.skipif(os.name != "posix", reason="The service uses POSIX process groups")
def test_sigterm_during_shutdown_bounds_forced_cleanup_and_ignores_repeats():
    process = subprocess.Popen([sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "print('ready', flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE, text=True, start_new_session=True)
    receipt = {"service": {"forced_kill": False, "returncode": None}, "interrupted": False}
    try:
        assert process.stdout.readline().strip() == "ready"
        with HTTP.TerminationGuard(receipt) as termination:
            timers = [threading.Timer(delay, os.kill, (os.getpid(), signal.SIGTERM))
                      for delay in (0.1, 3.0)]
            began = time.monotonic()
            try:
                for timer in timers:
                    timer.start()
                HTTP.stop_service(process, receipt, termination)
            finally:
                for timer in timers:
                    timer.cancel()
                    timer.join()
            assert time.monotonic() - began < 4.8
            assert receipt["interrupted"] is True
            assert receipt["interruption_signal"] == "SIGTERM"
            assert receipt["service"]["forced_kill"] is True
            assert receipt["service"]["returncode"] == -signal.SIGKILL
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stdout.close()


@pytest.mark.skipif(sys.platform != "linux" or not hasattr(os, "pidfd_open")
                    or not hasattr(signal, "pidfd_send_signal"),
                    reason="This control verifies Linux worker cleanup with stable PID handles")
def test_actual_outer_sigterm_stops_service_worker_and_decoder(tmp_path, mp3):
    decoder_marker, service_marker = tmp_path / "decoder.json", tmp_path / "service.pid"
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    decoder = bin_path / "ffmpeg"
    decoder.write_text(f"#!{sys.executable}\nimport json,os,time\nfrom pathlib import Path\n"
        f"Path({str(decoder_marker)!r}).write_text(json.dumps({{'pid':os.getpid(), 'parent_pid':os.getppid()}}))\n"
        "time.sleep(60)\n")
    decoder.chmod(0o755)
    # Observe the real service handle without replacing its implementation.
    entry = tmp_path / "observed_verifier.py"
    entry.write_text("import importlib.util,sys\nfrom pathlib import Path\n"
        f"spec=importlib.util.spec_from_file_location('verifier', {str(Path(HTTP.__file__).resolve())!r})\n"
        "module=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n"
        "launch=module.subprocess.Popen\n"
        "def observed_launch(*args, **kwargs):\n"
        "    process=launch(*args, **kwargs)\n"
        f"    Path({str(service_marker)!r}).write_text(str(process.pid))\n"
        "    return process\n"
        "module.subprocess.Popen=observed_launch\nraise SystemExit(module.main())\n")
    output = tmp_path / "run"
    env = dict(os.environ, PATH=str(bin_path) + os.pathsep + os.environ.get("PATH", ""))
    process = subprocess.Popen([sys.executable, str(entry), "--audio", str(mp3),
        "--output", str(output), "--expect-status", "needs_input", "--timeout-s", "60"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
    handles = []
    try:
        deadline = time.monotonic() + 20
        while not (decoder_marker.is_file() and (output / "history.jsonl").is_file()):
            if process.poll() is not None or time.monotonic() >= deadline:
                pytest.fail("The actual verifier did not reach the held decoder")
            time.sleep(0.02)
        decoder_state = json.loads(decoder_marker.read_text())
        handles = [os.pidfd_open(pid) for pid in
                   (int(service_marker.read_text()), decoder_state["parent_pid"], decoder_state["pid"])]
        began = time.monotonic()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=4.8)
        assert time.monotonic() - began < 5
        assert process.returncode == 1, (stdout, stderr)
        receipt = json.loads((output / "http-verification.json").read_text())
        assert receipt["interrupted"] is True
        assert receipt["interruption_signal"] == "SIGTERM"
        assert receipt["sigterm_cleanup_handler_installed"] is True
        assert receipt["verification_passed"] is False
        assert receipt["supported_decision"] is False
        assert receipt["finalization_skipped_reason"] == "verification_interrupted"
        assert receipt["service"]["returncode"] == 0
        assert receipt["service"]["forced_kill"] is False
        assert not (output / "pipeline-evidence.json").exists()
        assert not (output / "job-manifest.json").exists()
        for handle in handles:
            poller = select.poll()
            poller.register(handle, select.POLLIN)
            assert poller.poll(1000), "Service, worker, or decoder remained alive after interruption"
    finally:
        if not handles:
            pids = [int(service_marker.read_text())] if service_marker.is_file() else []
            if decoder_marker.is_file():
                state = json.loads(decoder_marker.read_text())
                pids.extend([state["parent_pid"], state["pid"]])
            for pid in pids:
                try:
                    handles.append(os.pidfd_open(pid))
                except ProcessLookupError:
                    pass
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=4.8)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait(timeout=5)
        for handle in handles:
            try:
                signal.pidfd_send_signal(handle, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                os.close(handle)


def test_sigterm_after_terminal_result_skips_finalization(tmp_path, mp3, monkeypatch):
    stop = HTTP.stop_service
    def interrupt_after_shutdown(process, receipt, termination):
        stop(process, receipt, termination)
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(HTTP, "stop_service", interrupt_after_shutdown)
    receipt = HTTP.verify_http(mp3, tmp_path / "run", expect_status="needs_input", timeout_s=60)
    assert receipt["http_checks_passed"] is True
    assert receipt["status"] == "needs_input"
    assert receipt["interrupted"] is True
    assert receipt["verification_passed"] is False
    assert receipt["supported_decision"] is False
    assert receipt["pipeline_evidence_passed"] is False
    assert not (tmp_path / "run/pipeline-evidence.json").exists()
    assert not (tmp_path / "run/job-manifest.json").exists()


def test_sigterm_at_handler_handoff_is_persisted_as_interrupted(tmp_path, mp3, monkeypatch):
    original_exit = HTTP.TerminationGuard.__exit__
    def interrupt_before_restoration(guard, *args):
        os.kill(os.getpid(), signal.SIGTERM)
        return original_exit(guard, *args)
    monkeypatch.setattr(HTTP.TerminationGuard, "__exit__", interrupt_before_restoration)
    receipt = HTTP.verify_http(mp3, tmp_path / "run", expect_status="needs_input", timeout_s=60)
    persisted = json.loads((tmp_path / "run/http-verification.json").read_text())
    assert persisted == receipt
    assert persisted["http_checks_passed"] is True
    assert persisted["interrupted"] is True
    assert persisted["interruption_signal"] == "SIGTERM"
    assert persisted["verification_passed"] is False
    assert persisted["supported_decision"] is False
    assert persisted["finalization_skipped_reason"] == "verification_interrupted"


@pytest.mark.skipif(os.name != "posix", reason="This control requires POSIX signal exit codes")
def test_sigterm_after_serialization_cannot_commit_a_successful_cli_receipt(tmp_path, mp3):
    entry, marker = tmp_path / "interrupt_commit.py", tmp_path / "restored-handler.txt"
    entry.write_text("import importlib.util,os,signal\nfrom pathlib import Path\n"
        f"spec=importlib.util.spec_from_file_location('verifier', {str(Path(HTTP.__file__).resolve())!r})\n"
        "module=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n"
        "from dopplergeist import jobs\nserialize=jobs.json.dumps\n"
        "def interrupt_commit(value, *args, **kwargs):\n"
        "    encoded=serialize(value, *args, **kwargs)\n"
        "    if isinstance(value, dict) and value.get('scope') == 'actual_local_http_upload_verification' and 'finished_utc' in value:\n"
        f"        Path({str(marker)!r}).write_text(str(signal.getsignal(signal.SIGTERM)))\n"
        "        os.kill(os.getpid(), signal.SIGTERM)\n"
        "    return encoded\n"
        "jobs.json.dumps=interrupt_commit\nraise SystemExit(module.main())\n")
    output = tmp_path / "run"
    process = subprocess.run([sys.executable, str(entry), "--audio", str(mp3),
        "--output", str(output), "--expect-status", "needs_input", "--timeout-s", "60"],
        capture_output=True, text=True, timeout=20)
    assert process.returncode == -signal.SIGTERM, (process.stdout, process.stderr)
    assert marker.read_text() == str(signal.SIG_DFL)
    assert not (output / "http-verification.json").exists()
    assert json.loads((output / "result.json").read_text())["status"] == "needs_input"


STAGE_FILES = ["intake/recording.json", "intake/intake.json", "intake/recording.f32",
    "discovery/discovery.json", "data-provenance.json", "search/manifest.json",
    "search/search-report.json", "refined-candidates.json", "decision.json"]


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


@pytest.fixture
def stage_evidence(tmp_path):
    """Small consistency fixture, not generated audio or a localization benchmark."""
    from dopplergeist import confidence
    directory = tmp_path / "job"
    directory.mkdir()
    request = HTTP.validate_request({"schema_version": 1, "audio_path": str(directory / "input.mp3"),
        "time_window": {"start_utc": CLOCK, "end_utc": CLOCK, "source": "user"}})
    wire = {key: value for key, value in request.items() if key != "audio_path"}
    source_hash = hashlib.sha256(b"metadata consistency fixture only").hexdigest()
    implementation = {path.name: HTTP.sha256(path) for path in sorted(Path(HTTP.dopplergeist.__file__).parent.glob("*.py"))}
    recording = {"source_sha256": source_hash, "duration_s": 8.0, "sample_rate_hz": 4000,
                 "channels": 1, "source_format": "mp3", "time_window": wire["time_window"]}
    event = {"event_id": "event-0001", "start_s": 1.0, "end_s": 7.0, "band_hz": [100.0, 200.0],
        "ridge": [{"time_s": t, "frequency_hz": f} for t, f in ((1., 180.), (4., 150.), (7., 120.))]}
    bounds = [-125.0, 24.0, -66.0, 50.0]
    start = HTTP.utc_timestamp(CLOCK).timestamp()
    window = [start, start]
    coverage = {"search_complete": True, "data_status": "available", "limitations": [],
                "requested_area": wire["search"], "missing_data": []}
    flight_coverage = {"bounds": [-180., -90., 180., 90.], "time_range_s": [start-300, start+300],
                       "all_aircraft": True, "synthetic": True}
    flight_index = {"input_hash": "1" * 64, "coverage": flight_coverage}
    terrain = {"terrain_configuration": {"constant_m": 0}}
    configuration = {"code": implementation, "bounds": bounds, "scoring": {"recording_start_window_s": window},
        "events": [dict(event, event_ids=[event["event_id"]])], "time_range_s": [start-30, start+38],
        "indexes": [{"input_hash": flight_index["input_hash"], "file_sha256": "2" * 64}],
        "additional_input_hashes": terrain}
    run_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    candidate = {"lat": 40.0, "lon": -100.0, "score": -1.0, "score_kind": "negative_robust_ridge_loss_hz",
                 "event_ids": [event["event_id"]], "flight_ids": ["fixture-flight"], "recording_start_utc": CLOCK}
    fit = {"rmse_hz": 1.0, "outlier_fraction": 0.0, "support_fraction": 1.0, "drift_at_bound": False}
    row = {key: candidate[key] for key in ("lat", "lon", "score", "score_kind", "flight_ids")}
    row.update(recording_start_time_s=start, event_indices=[0], event_diagnostics=[fit])
    diagnostics = {"recording_start_window_s": window, "clock_locked": True, "sensitivity": {},
                   "unmatched_event_ids": [], event["event_id"]: fit}
    decision = dict(confidence.decide_location([event], [candidate], coverage, matching_diagnostics=diagnostics),
                    candidates=[candidate])
    final = {"schema_version": 1, "job_id": "metadata-consistency-fixture", "recording": recording,
             "events": [event], "coverage": coverage,
             **{key: value for key, value in decision.items() if key != "diagnostics"}}
    values = {
        "input.json": {"sha256": source_hash, "bytes": 33, "path": "input.mp3"},
        "request.json": request,
        "provenance.json": {"source_sha256": source_hash, "request": request, "implementation_files": implementation,
            "operator_configuration_sha256": hashlib.sha256(b"{}").hexdigest(), "ground_truth_used_by_search": False,
            "event_selection": "automatic_whole_recording", "status": final["status"], "coverage": coverage,
            "discovered_events": 1, "search_run_hash": run_hash},
        "intake/recording.json": recording,
        "intake/intake.json": {"sample_count": 32000, "time_status": "ready", "decode": {"sample_format": "f32le"}},
        "discovery/discovery.json": {"source_sha256": source_hash, "events": [event],
                                     "chunks": [{"start_s": 0.0, "duration_s": 8.0}]},
        "data-provenance.json": {"flight_indexes": [flight_index], "terrain": terrain},
        "search/manifest.json": {"run_hash": run_hash, "configuration": configuration},
        "search/search-report.json": {"run_hash": run_hash, "scope": bounds, "scoring_time_is_locked": True,
            "ground_truth_used_by_search": False, "data_coverage": [{"input_hash": flight_index["input_hash"],
                "source": flight_coverage, "requested_bounds": bounds, "requested_time_range_s": configuration["time_range_s"]}],
            "tiles_total": 1, "tiles_completed": 1, "unsearched_tiles": 0, "tile_failures": [],
            "data_scope_complete": True, "all_event_groups_considered": True, "status": "complete", "event_groups_proposed": 1},
        "refined-candidates.json": {"ranked": [row], "matching_diagnostics": diagnostics},
        "decision.json": decision,
    }
    for name, value in values.items():
        save_json(directory / name, value)
    (directory / "intake/recording.f32").write_bytes(b"\0" * (32000 * 4))
    return directory, final, wire, {}


def test_complete_stage_evidence_keeps_inconclusive_decision(stage_evidence):
    directory, final, wire, operator = stage_evidence
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"], report
    assert report["full_pipeline_observed"] is True
    assert report["stages_verified"] == ["automatic_provenance", "intake", "discovery", "acquisition", "search", "refinement", "decision"]
    assert final["status"] == "inconclusive"
    assert report["location_accuracy_evaluated"] is False
    assert all(name in report["artifacts"] for name in STAGE_FILES)


def fixture_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def write_fixture_ledger(path, run_hash, rows):
    """Write the documented retention format without calling the verifier or producer."""
    kind = rows[0]["score_kind"]
    checksums = {}
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE run(identity TEXT, score_kind TEXT);
            CREATE TABLE stages(name TEXT PRIMARY KEY, checksum TEXT,
                occurrences INTEGER, duplicates INTEGER, kept TEXT);
            CREATE TABLE records(stage TEXT, mode_id TEXT, score REAL,
                groups_count INTEGER, kind TEXT, seed TEXT, PRIMARY KEY(stage,mode_id));
        """)
        db.execute("INSERT INTO run VALUES(?,?)", (run_hash, kind))
        for stage, values in (("coarse:0_0", rows), ("global:0_0", rows[:2])):
            records = sorted((row["mode_id"], float(row["score"]), 1, kind,
                json.dumps(row["mode_seed"], sort_keys=True, separators=(",", ":"))) for row in values)
            kept = sorted(row["mode_id"] for row in rows[:2])
            encoded = b"".join(json.dumps(record, separators=(",", ":"), allow_nan=False).encode() + b"\n"
                               for record in records)
            encoded += json.dumps(kept, separators=(",", ":")).encode()
            encoded += json.dumps([len(records), 0]).encode()
            checksums[stage] = hashlib.sha256(encoded).hexdigest()
            db.executemany("INSERT INTO records VALUES(?,?,?,?,?,?)", [(stage, *record) for record in records])
            db.execute("INSERT INTO stages VALUES(?,?,?,?,?)",
                       (stage, checksums[stage], len(records), 0, json.dumps(kept)))
    return checksums


@pytest.fixture
def finite_stage_evidence(stage_evidence):
    """A finite metadata contract fixture, not a physical localization benchmark."""
    from dopplergeist import confidence

    directory, final, wire, operator = stage_evidence
    manifest = json.loads((directory / "search/manifest.json").read_text())
    configuration = manifest["configuration"]
    configuration["budget"] = {"spacing_m": 1000.0, "refine_spacing_m": 100.0}
    configuration["scoring"].update(time_step_s=0.5, time_sweep_s=5.0)
    run_hash = fixture_digest(configuration)
    manifest["run_hash"] = run_hash
    save_json(directory / "search/manifest.json", manifest)

    refinement = json.loads((directory / "refined-candidates.json").read_text())
    window = refinement["matching_diagnostics"]["recording_start_window_s"]
    sensitivity = {"complete": True, "boundary_limited": False, "radius_m": 50.0,
        "method": "fixture_full_perturbation", "kind": "sensitivity",
        "sources": ["frequency", "clock", "altitude", "sound_speed"],
        "settings": {"clock_bounds_s": window}}
    rows = []
    for latitude, score in ((40.0, -1.0), (40.003, -1.1), (45.0, -10.0)):
        row = deepcopy(refinement["ranked"][0])
        row.update(lat=latitude, score=score, pass_emission_times_s=[window[0] + 4.0],
            scoring_assessment={"complete": True, "scheduled_trials": 1, "evaluated_trials": 1,
                "rejected_trials": 0, "unknown_trials": 0, "unknown_reasons": {}, "empty_clock_domain": False},
            core_assessment_complete=True)
        row["event_diagnostics"][0]["score"] = score
        seed = {"event_indices": [0], "flight_ids": row["flight_ids"], "pass_emission_times_s": [window[0] + 4.0],
            "position": [0.0, 0.0, latitude, -100.0, 0.0], "recording_start_time_s": window[0]}
        row.update(mode_seed=seed, mode_id="mode-" + fixture_digest(seed))
        rows.append(row)
    rows[0]["sensitivity"] = sensitivity
    ids = [row["mode_id"] for row in rows[:2]]
    checksums = write_fixture_ledger(directory / "search/retention.sqlite", run_hash, rows)
    payload = {"ranked": rows[:2], "counts": {"unclassified_score_candidates": 0},
               "retention_checksum": checksums["coarse:0_0"]}
    save_json(directory / "search/tile-0_0.json",
              {"run_hash": run_hash, "payload": payload, "payload_hash": fixture_digest(payload)})
    finite = {"schema_version": 1, "scope": "evaluated_finite_grid", "ledger_artifact": "retention.sqlite",
        "complete": True, "pruning_accounted_for": True, "score_kind": rows[0]["score_kind"],
        "spacing_m": 1000.0, "refine_spacing_m": 100.0, "max_event_groups": 1,
        "retained_modes": [{"mode_id": row["mode_id"], "score": row["score"], "event_groups": 1} for row in rows[:2]],
        "evaluated_modes": 3, "discarded_count": 1, "best_discarded_score": -10.0,
        "discarded_bound_status": "finite", "unclassified_score_candidates": 0,
        "stages": {
            "coarse": {"stages": 1, "input_occurrences": 3, "exact_duplicates": 0, "retained": 2, "discarded": 1},
            "global": {"stages": 1, "input_occurrences": 2, "exact_duplicates": 0, "retained": 2, "discarded": 0}},
        "optimizer_domain": {"run_hash": run_hash, "source_fit_code_sha256": configuration["code"]["matching.py"],
            "score_code_sha256": configuration["code"]["search.py"], "clock_window_s": window,
            "time_step_s": 0.5, "declared_sweep_s": 5.0},
        "limitations": ["Finite metadata fixture; no physical trials independently reproduced."]}
    search = json.loads((directory / "search/search-report.json").read_text())
    search.update(run_hash=run_hash, ranked=rows[:2], core_assessed_mode_ids=ids,
                  finite_search_evidence=finite, refinement_points_searched=0)
    save_json(directory / "search/search-report.json", search)
    diagnostics = refinement["matching_diagnostics"]
    diagnostics.update(sensitivity=sensitivity, refinement_boundary_limited=False, alternatives_evaluated=False,
        finite_search_evidence=finite, core_assessment_mapping_status="present",
        assessed_mode_ids=sorted(ids), candidate_mode_ids=ids)
    diagnostics[final["events"][0]["event_id"]] = rows[0]["event_diagnostics"][0]
    refinement["ranked"] = rows[:2]
    save_json(directory / "refined-candidates.json", refinement)
    candidates = []
    for row in rows[:2]:
        candidate = dict(final["candidates"][0], lat=row["lat"], score=row["score"])
        if "sensitivity" in row:
            candidate["uncertainty"] = {key: row["sensitivity"][key] for key in ("radius_m", "method", "kind")}
        candidates.append(candidate)
    decision = confidence.decide_location(final["events"], candidates, final["coverage"], matching_diagnostics=diagnostics)
    assert decision["status"] == "succeeded", decision
    final.update({key: value for key, value in decision.items() if key != "diagnostics"})
    save_json(directory / "decision.json", decision)
    provenance = json.loads((directory / "provenance.json").read_text())
    provenance.update(status=final["status"], search_run_hash=run_hash)
    save_json(directory / "provenance.json", provenance)
    return directory, final, wire, operator


def change_fixture_json(directory, name, change):
    path = directory / name
    value = json.loads(path.read_text())
    change(value)
    save_json(path, value)


def change_finite_claim(directory, change):
    change_fixture_json(directory, "search/search-report.json", lambda value: change(value["finite_search_evidence"]))
    change_fixture_json(directory, "refined-candidates.json",
                        lambda value: change(value["matching_diagnostics"]["finite_search_evidence"]))


def test_finite_stage_reconstructs_predecision_union_and_preserves_ledger(finite_stage_evidence):
    directory, final, wire, operator = finite_stage_evidence
    ledger = directory / "search/retention.sqlite"
    before = ledger.read_bytes()
    decision = json.loads((directory / "decision.json").read_text())
    assert decision["diagnostics"]["finite_envelope"]["base_reported_radius_m"] == 50.0
    assert 333.0 < final["candidates"][0]["uncertainty"]["radius_m"] < 334.0
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"], report
    assert report["full_pipeline_observed"] is True
    assert report["finite_search_verified"] is True
    assert report["finite_search"] == {"ledger_verified": True, "complete": True,
        "retained_modes": 2, "evaluated_modes": 3, "discarded_count": 1,
        "best_discarded_score": -10.0, "unclassified_score_candidates": 0,
        "physical_trials_independently_recomputed": False}
    assert "search/retention.sqlite" in report["artifacts"]
    assert ledger.read_bytes() == before


@pytest.mark.parametrize("change,expected", [
    ({}, True),
    ({"scheduled_trials": 2}, False),
    ({"evaluated_trials": 0, "rejected_trials": 3}, False),
    ({"unknown_trials": 1, "scheduled_trials": 4}, False),
    ({"evaluated_trials": True}, False),
    ({"trial_count_semantics": "unknown_convention"}, False),
])
def test_finite_stage_checks_explicit_disjoint_trial_counts(finite_stage_evidence, change, expected):
    directory, final, wire, operator = finite_stage_evidence
    def change_assessment(search):
        assessment = search["ranked"][0]["scoring_assessment"]
        assessment.pop("unknown_reasons")
        assessment.update({"trial_count_semantics": "disjoint_evaluated_rejected_unknown",
            "scheduled_trials": 3, "evaluated_trials": 2, "rejected_trials": 1,
            "reasons": ["acoustic_loss_exceeds_limit"], **change})
    change_fixture_json(directory, "search/search-report.json", change_assessment)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is expected, report
    if not expected:
        assert "winner masks missing or unknown clock trials" in " ".join(report["errors"])


@pytest.mark.parametrize("kind,error", [
    ("missing", "search/retention.sqlite"), ("corrupt", "DatabaseError"),
    ("wrong_run", "another run"), ("checksum", "stage checksum"),
    ("groups", "group or association"), ("units", "mixed units"),
])
def test_finite_stage_rejects_unusable_or_inconsistent_ledger(finite_stage_evidence, kind, error):
    directory, final, wire, operator = finite_stage_evidence
    path = directory / "search/retention.sqlite"
    if kind == "missing":
        path.unlink()
    elif kind == "corrupt":
        path.write_bytes(b"not a sqlite retention database")
    else:
        statements = {"wrong_run": ("UPDATE run SET identity=?", ("0" * 64,)),
            "checksum": ("UPDATE stages SET checksum=?", ("0" * 64,)),
            "groups": ("UPDATE records SET groups_count=2", ()),
            "units": ("UPDATE records SET kind=?", ("incompatible_score_units",))}
        with sqlite3.connect(path) as db:
            db.execute(*statements[kind])
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert report["full_pipeline_observed"] is False
    assert error in " ".join(report["errors"])


@pytest.mark.parametrize("kind,error", [
    ("extra_field", "invalid physical fields"),
    ("nonfinite_position", "invalid physical fields"),
    ("boolean_clock", "invalid physical fields"),
    ("empty_flight", "invalid physical fields"),
    ("missing_pass", "group or association counts"),
])
def test_finite_stage_validates_discarded_physical_seeds(finite_stage_evidence, kind, error):
    directory, final, wire, operator = finite_stage_evidence
    with sqlite3.connect(directory / "search/retention.sqlite") as db:
        identity, encoded = db.execute(
            "SELECT mode_id,seed FROM records WHERE stage='coarse:0_0' ORDER BY score LIMIT 1").fetchone()
        seed = json.loads(encoded)
        if kind == "extra_field":
            seed["undeclared_origin"] = "not part of the seed contract"
        elif kind == "nonfinite_position":
            seed["position"][2] = float("inf")
        elif kind == "boolean_clock":
            seed["recording_start_time_s"] = True
        elif kind == "empty_flight":
            seed["flight_ids"] = [""]
        else:
            seed["pass_emission_times_s"] = []
        db.execute("UPDATE records SET seed=? WHERE mode_id=?", (json.dumps(seed), identity))
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert error in " ".join(report["errors"])


@pytest.mark.parametrize("kind", ["score", "score_kind", "physical_point", "copied_seed"])
def test_finite_coarse_payload_cannot_disagree_with_its_ledger(finite_stage_evidence, kind):
    directory, final, wire, operator = finite_stage_evidence
    def corrupt_payload(tile):
        row = tile["payload"]["ranked"][0]
        if kind == "score":
            row["score"] += 0.25
        elif kind == "score_kind":
            row["score_kind"] = "matched_group_support_minus_normalized_residual"
        elif kind == "physical_point":
            row["lat"] += 0.001
        else:
            row["mode_seed"]["position"][2] += 0.001
        tile["payload_hash"] = fixture_digest(tile["payload"])
    change_fixture_json(directory, "search/tile-0_0.json", corrupt_payload)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "Coarse checkpoint score or physical seed differs from its ledger" in " ".join(report["errors"])


def test_finite_refinement_work_requires_recorded_fine_stages(finite_stage_evidence):
    directory, final, wire, operator = finite_stage_evidence
    change_fixture_json(directory, "search/search-report.json", lambda search: search.update(refinement_points_searched=1))
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "fine" in " ".join(report["errors"]).lower()


@pytest.mark.parametrize("key,value,error", [
    ("best_discarded_score", -11.0, "discarded score bound"),
    ("discarded_count", 0, "distinct retention counts"),
    ("evaluated_modes", 2, "distinct retention counts"),
    ("max_event_groups", 2, "Finite group bound"),
    ("score_kind", "matched_group_support_minus_normalized_residual", "another run or score kind"),
    ("unclassified_score_candidates", 1, "discarded score bound"),
])
def test_finite_stage_recomputes_claims_from_recorded_modes(finite_stage_evidence, key, value, error):
    directory, final, wire, operator = finite_stage_evidence
    change_finite_claim(directory, lambda finite: finite.__setitem__(key, value))
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert error in " ".join(report["errors"])


@pytest.mark.parametrize("kind,error", [
    ("retained", "retained original scores or groups"),
    ("candidate", "wire candidates omit or invent"),
    ("assessed", "assessed IDs differ"),
    ("core", "assessed IDs differ"),
])
def test_finite_stage_rejects_omitted_mode_identities(finite_stage_evidence, kind, error):
    directory, final, wire, operator = finite_stage_evidence
    if kind == "retained":
        change_finite_claim(directory, lambda finite: finite["retained_modes"].pop())
    elif kind == "core":
        change_fixture_json(directory, "search/search-report.json", lambda search: search["core_assessed_mode_ids"].pop())
    else:
        key = "candidate_mode_ids" if kind == "candidate" else "assessed_mode_ids"
        change_fixture_json(directory, "refined-candidates.json",
                            lambda refinement: refinement["matching_diagnostics"][key].pop())
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert error in " ".join(report["errors"])


@pytest.mark.parametrize("kind", ["swap_same_association_ids", "change_pass_emission_times"])
def test_finite_refinement_preserves_its_original_mode_lineage(finite_stage_evidence, kind):
    directory, final, wire, operator = finite_stage_evidence
    def change_lineage(refinement):
        first, second = refinement["ranked"]
        assert first["flight_ids"] == second["flight_ids"]
        assert first["event_indices"] == second["event_indices"]
        if kind == "swap_same_association_ids":
            first["mode_id"], second["mode_id"] = second["mode_id"], first["mode_id"]
            refinement["matching_diagnostics"]["candidate_mode_ids"] = [first["mode_id"], second["mode_id"]]
        else:
            first["pass_emission_times_s"] = [first["recording_start_time_s"] + 2.0]
    change_fixture_json(directory, "refined-candidates.json", change_lineage)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "borrowed another mode's event-to-flight identity" in " ".join(report["errors"])


def test_finite_refinement_cannot_replace_an_original_point_with_a_shifted_copy(finite_stage_evidence):
    from dopplergeist import confidence

    directory, final, wire, operator = finite_stage_evidence
    refinement = json.loads((directory / "refined-candidates.json").read_text())
    shifted = refinement["ranked"][1]
    assert shifted["mode_seed"]["position"][2] == 40.003
    shifted["lat"] = 40.0001
    save_json(directory / "refined-candidates.json", refinement)
    candidates = deepcopy(final["candidates"])
    candidates[1]["lat"] = shifted["lat"]
    diagnostics = refinement["matching_diagnostics"]
    candidates[0]["uncertainty"] = {key: diagnostics["sensitivity"][key] for key in ("radius_m", "method", "kind")}
    decision = confidence.decide_location(final["events"], candidates, final["coverage"], matching_diagnostics=diagnostics)
    assert decision["status"] == "succeeded", decision
    assert decision["candidates"][0]["uncertainty"]["radius_m"] == 50.0
    final.update({key: value for key, value in decision.items() if key != "diagnostics"})
    save_json(directory / "decision.json", decision)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "omitted an original retained physical point" in " ".join(report["errors"])


def test_finite_winner_cannot_mask_an_unknown_scheduled_trial(finite_stage_evidence):
    directory, final, wire, operator = finite_stage_evidence
    def add_unknown(search):
        search["ranked"][0]["scoring_assessment"].update(complete=False, scheduled_trials=2,
            unknown_trials=1, unknown_reasons={"insufficient_track_support": 1})
        assert search["ranked"][0]["core_assessment_complete"] is True
    change_fixture_json(directory, "search/search-report.json", add_unknown)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "winner masks missing or unknown clock trials" in " ".join(report["errors"])


def test_finite_aggregate_cannot_omit_an_explicitly_unclassified_retained_mode(finite_stage_evidence):
    directory, final, wire, operator = finite_stage_evidence
    def hide_unknown_from_aggregate(search):
        search["ranked"][0]["scoring_assessment"].update(complete=False, scheduled_trials=2,
            unknown_trials=1, unknown_reasons={"insufficient_track_support": 1})
        search["ranked"][0]["core_assessment_complete"] = False
        search["core_assessed_mode_ids"] = [search["ranked"][1]["mode_id"]]
        assert search["finite_search_evidence"]["complete"] is True
        assert search["finite_search_evidence"]["unclassified_score_candidates"] == 0
    change_fixture_json(directory, "search/search-report.json", hide_unknown_from_aggregate)
    change_fixture_json(directory, "refined-candidates.json", lambda refinement:
        refinement["matching_diagnostics"].update(assessed_mode_ids=[refinement["ranked"][1]["mode_id"]]))
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "aggregate omits unclassified retained clock trials" in " ".join(report["errors"])


@pytest.mark.parametrize("change", [
    {"scheduled_trials": 2},
    {"evaluated_trials": True},
    {"rejected_trials": 2},
    {"unknown_reasons": {"unavailable_model": 1}},
    {"empty_clock_domain": True},
])
def test_finite_known_claim_requires_accounted_nonempty_clock_trials(finite_stage_evidence, change):
    directory, final, wire, operator = finite_stage_evidence
    change_fixture_json(directory, "search/search-report.json",
        lambda search: search["ranked"][0]["scoring_assessment"].update(change))
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "winner masks missing or unknown clock trials" in " ".join(report["errors"])


def test_honest_unknown_finite_trial_preserves_an_inconclusive_decision(finite_stage_evidence):
    from dopplergeist import confidence

    directory, final, wire, operator = finite_stage_evidence
    change_finite_claim(directory, lambda finite: finite.update(complete=False, unclassified_score_candidates=1,
        best_discarded_score=None, discarded_bound_status="unknown_model_or_trial_support"))
    search = json.loads((directory / "search/search-report.json").read_text())
    best = search["ranked"][0]
    best["scoring_assessment"].update(complete=False, scheduled_trials=2, unknown_trials=1,
        unknown_reasons={"insufficient_track_support": 1})
    best["core_assessment_complete"] = False
    search["core_assessed_mode_ids"] = [search["ranked"][1]["mode_id"]]
    save_json(directory / "search/search-report.json", search)
    refinement = json.loads((directory / "refined-candidates.json").read_text())
    refinement["ranked"][0].update(scoring_assessment=best["scoring_assessment"], core_assessment_complete=False)
    diagnostics = refinement["matching_diagnostics"]
    diagnostics["assessed_mode_ids"] = search["core_assessed_mode_ids"]
    save_json(directory / "refined-candidates.json", refinement)
    tile = json.loads((directory / "search/tile-0_0.json").read_text())
    tile["payload"]["ranked"] = search["ranked"]
    tile["payload"]["counts"]["unclassified_score_candidates"] = 1
    tile["payload_hash"] = fixture_digest(tile["payload"])
    save_json(directory / "search/tile-0_0.json", tile)
    candidates = deepcopy(final["candidates"])
    candidates[0]["uncertainty"] = {key: diagnostics["sensitivity"][key] for key in ("radius_m", "method", "kind")}
    decision = confidence.decide_location(final["events"], candidates, final["coverage"], matching_diagnostics=diagnostics)
    decision.setdefault("candidates", candidates)
    assert decision["status"] == "inconclusive"
    assert decision["reason_code"] == "finite_search_incomplete"
    final.update({key: value for key, value in decision.items() if key != "diagnostics"})
    save_json(directory / "decision.json", decision)
    change_fixture_json(directory, "provenance.json", lambda provenance: provenance.update(status=final["status"]))
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"], report
    assert report["full_pipeline_observed"] is True
    assert report["finite_search_verified"] is False
    assert report["finite_search"]["ledger_verified"] is True
    assert report["finite_search"]["best_discarded_score"] is None
    assert report["finite_search"]["unclassified_score_candidates"] == 1


def test_finite_completeness_cannot_erase_a_coarse_unknown_trial(finite_stage_evidence):
    directory, final, wire, operator = finite_stage_evidence
    def add_unknown(tile):
        tile["payload"]["counts"]["unclassified_score_candidates"] = 1
        tile["payload_hash"] = fixture_digest(tile["payload"])
    change_fixture_json(directory, "search/tile-0_0.json", add_unknown)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "unknown-trial count is inconsistent" in " ".join(report["errors"])


@pytest.mark.parametrize("forged_radius", [50.0, 999.0])
def test_finite_stage_rejects_forged_union_in_consistent_terminal_copies(finite_stage_evidence, forged_radius):
    directory, final, wire, operator = finite_stage_evidence
    final["candidates"][0]["uncertainty"]["radius_m"] = forged_radius
    def forge(decision):
        decision["candidates"] = deepcopy(final["candidates"])
        decision["diagnostics"]["radius_m"] = forged_radius
        decision["diagnostics"]["finite_envelope"]["radius_m"] = forged_radius
    change_fixture_json(directory, "decision.json", forge)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "does not reproduce the persisted decision" in " ".join(report["errors"])


@pytest.mark.parametrize("null_finite", [False, True])
def test_legacy_supported_stage_evidence_requires_absent_finite_field(finite_stage_evidence, null_finite):
    from dopplergeist import confidence

    directory, final, wire, operator = finite_stage_evidence
    search = json.loads((directory / "search/search-report.json").read_text())
    search.pop("finite_search_evidence")
    search["alternative_modes_exhaustively_assessed"] = True
    if null_finite:
        search["finite_search_evidence"] = None
    search.pop("core_assessed_mode_ids")
    search["ranked"] = search["ranked"][:1]
    save_json(directory / "search/search-report.json", search)
    refinement = json.loads((directory / "refined-candidates.json").read_text())
    refinement["ranked"] = refinement["ranked"][:1]
    diagnostics = refinement["matching_diagnostics"]
    for key in ("finite_search_evidence", "core_assessment_mapping_status", "candidate_mode_ids", "assessed_mode_ids"):
        diagnostics.pop(key)
    diagnostics["alternatives_evaluated"] = True
    save_json(directory / "refined-candidates.json", refinement)
    candidate = deepcopy(final["candidates"][0])
    candidate["uncertainty"] = {key: diagnostics["sensitivity"][key] for key in ("radius_m", "method", "kind")}
    decision = confidence.decide_location(final["events"], [candidate], final["coverage"], matching_diagnostics=diagnostics)
    decision.setdefault("candidates", [candidate])
    assert decision["status"] == "succeeded", decision
    final.update({key: value for key, value in decision.items() if key != "diagnostics"})
    save_json(directory / "decision.json", decision)
    (directory / "search/retention.sqlite").unlink()
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    if null_finite:
        assert report["passed"] is False
        assert "Search and refinement finite evidence differ" in " ".join(report["errors"])
        return
    assert report["passed"], report
    assert report["full_pipeline_observed"] is True
    assert "finite_search" not in report
    assert "finite_search_verified" not in report


@pytest.mark.parametrize("name", STAGE_FILES)
def test_scientific_result_requires_each_stage_artifact(stage_evidence, name):
    directory, final, wire, operator = stage_evidence
    (directory / name).unlink()
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert report["full_pipeline_observed"] is False
    assert name in " ".join(report["errors"])


@pytest.mark.parametrize("name", [name for name in STAGE_FILES if name.endswith(".json")])
def test_corrupt_stage_json_fails_closed(stage_evidence, name):
    directory, final, wire, operator = stage_evidence
    (directory / name).write_text('{"unfinished":')
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert any("JSONDecodeError" in error for error in report["errors"])


@pytest.mark.parametrize("name,key,value,error", [
    ("provenance.json", "operator_configuration_sha256", "0" * 64, "operator configuration"),
    ("intake/recording.json", "source_sha256", "0" * 64, "terminal recording"),
    ("intake/intake.json", "sample_count", 31999, "cache size"),
    ("discovery/discovery.json", "events", [], "source or events"),
    ("discovery/discovery.json", "chunks", [{"start_s": 1.0, "duration_s": 7.0}], "gap"),
    ("data-provenance.json", "flight_indexes", [{"input_hash": "0" * 64, "coverage": {}}], "flight inputs"),
    ("search/manifest.json", "run_hash", "0" * 64, "run identities"),
    ("search/search-report.json", "tiles_completed", 0, "unsearched-tile"),
    ("refined-candidates.json", "ranked", [], "candidate counts"),
    ("decision.json", "status", "succeeded", "terminal result"),
])
def test_stage_cross_links_reject_valid_but_inconsistent_json(stage_evidence, name, key, value, error):
    directory, final, wire, operator = stage_evidence
    path = directory / name
    changed = json.loads(path.read_text())
    changed[key] = value
    save_json(path, changed)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert error in " ".join(report["errors"])


def test_forged_success_cannot_reuse_an_inconclusive_scientific_decision(stage_evidence):
    directory, final, wire, operator = stage_evidence
    final["status"] = "succeeded"
    final["reason_code"] = "supported_by_evidence_checks"
    for name in ("provenance.json", "decision.json"):
        path = directory / name
        changed = json.loads(path.read_text())
        changed["status"] = final["status"]
        if name == "decision.json":
            changed["reason_code"] = final["reason_code"]
        save_json(path, changed)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "does not reproduce" in " ".join(report["errors"])


def test_symlinked_stage_artifact_is_rejected(stage_evidence, tmp_path):
    directory, final, wire, operator = stage_evidence
    target = directory / "decision.json"
    other = tmp_path / "outside-decision.json"
    target.rename(other)
    target.symlink_to(other)
    report = HTTP.inspect_pipeline_evidence(directory, final, wire, operator)
    assert report["passed"] is False
    assert "unsafe stage artifact" in " ".join(report["errors"])


def test_actual_http_success_does_not_mask_missing_pipeline_evidence(tmp_path, mp3, monkeypatch):
    inspect = HTTP.inspect_pipeline_evidence
    def remove_discovery_before_inspection(directory, final, wire, operator):
        (directory / "discovery/discovery.json").unlink()
        return inspect(directory, final, wire, operator)
    monkeypatch.setattr(HTTP, "inspect_pipeline_evidence", remove_discovery_before_inspection)
    receipt = HTTP.verify_http(mp3, tmp_path / "run", expect_status="needs_input",
        expect_reason="recording_time_required", timeout_s=60)
    assert receipt["http_checks_passed"] is True
    assert receipt["expectation_matched"] is True
    assert receipt["pipeline_evidence_passed"] is False
    assert receipt["verification_passed"] is False
    assert receipt["supported_decision"] is False
    assert receipt["service"]["returncode"] == 0
    report = json.loads((tmp_path / "run/pipeline-evidence.json").read_text())
    assert "discovery/discovery.json" in " ".join(report["errors"])
