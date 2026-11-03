"""Fail-closed controls for orchestration; these are not localization replays."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("ci_http_replay", ROOT / "scripts/ci_http_replay.py")
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)
# Reuse the existing independent acceptance controls and recorded-fit examples.
SUPPORT = REPLAY.load_module(ROOT / "tests/test_ci_upload_replay.py", "http_acceptance_test_support")


def http_receipt(result, **changes):
    value = {"job_id": result["job_id"], "status": result["status"], "verification_passed": True,
        "http_checks_passed": True, "pipeline_evidence_passed": True, "full_pipeline_observed": True,
        "interrupted": False, "interruption_signal": None,
        "supported_decision": result["status"] == "succeeded", "terminal_result_preserved_after_shutdown": True,
        "service": {"shutdown_signal": "SIGINT", "returncode": 0, "forced_kill": False,
                    "stopped_utc": "2026-11-03T03:00:00Z"}}
    value.update(changes)
    return value


def complete_checks():
    return {name: True for name in REPLAY.UPLOAD.REQUIRED_CHECKS | REPLAY.HTTP_REQUIRED_CHECKS}


@pytest.fixture
def recorded_job(tmp_path):
    """Small artifact controls, with no claim that their placeholder audio ran."""
    result, labels, mapping = SUPPORT.scene()
    result["job_id"] = "1" * 32
    product, inputs = tmp_path / "http", tmp_path / "inputs"
    directory = product / "jobs" / result["job_id"]
    directory.mkdir(parents=True)
    inputs.mkdir()
    audio = inputs / "recording.mp3"
    audio.write_bytes(b"artifact-control-only")
    (directory / "input.mp3").write_bytes(audio.read_bytes())
    result["recording"] = {"source_sha256": REPLAY.file_record(audio)["sha256"]}
    wire = {"schema_version": 1, "search": {"coverage": "conus"},
            "time_window": {"start_utc": SUPPORT.CLOCK, "end_utc": SUPPORT.CLOCK}}
    operator, sources = {"offline": True}, {"confidence.py": "frozen-source-control"}
    search = {"tiles_total": 10, "tiles_completed": 10, "unsearched_tiles": 0,
        "tile_failures": [], "refinement_failure": None, "data_scope_complete": True,
        "all_event_groups_considered": True, "status": "complete", "scope": REPLAY.UPLOAD.SCOPE,
        "run_hash": "recorded", "alternative_modes_exhaustively_assessed": True,
        "grid_points_searched": 400, "refinement_points_searched": 25,
        "refinement_points_skipped": 75, "process_peak_rss_mib": 123}
    records = {"input.json": {}, "request.json": dict(wire, audio_path=str(directory / "input.mp3")),
        "operator.json": operator, "provenance.json": {"implementation_files": sources, "search_run_hash": "recorded"},
        "intake/recording.json": result["recording"],
        "discovery/discovery.json": {"events": result["events"], "settings": {"window_s": 2}},
        "data-provenance.json": {}, "search/search-report.json": search,
        "refined-candidates.json": SUPPORT.recorded_fit(result), "decision.json": result, "result.json": result}
    for name, value in records.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        REPLAY.write_json(path, value)
    (directory / "worker.log").write_text("control\n")
    artifacts = {name: {key: REPLAY.file_record(directory / name)[key] for key in ("bytes", "sha256")}
                 for name in REPLAY.UPLOAD.REQUIRED_ARTIFACTS}
    evidence = {"passed": True, "full_pipeline_observed": True, "scientific_decision_expected": True,
                "errors": [], "artifacts": artifacts}
    REPLAY.write_json(product / "pipeline-evidence.json", evidence)
    return SimpleNamespace(product=product, directory=directory, result=result, labels=labels, mapping=mapping,
        audio=audio, wire=wire, operator=operator, sources=sources, evidence=evidence)


def collect(job):
    return REPLAY.collect_job(job.product, job.result, job.audio, job.operator, job.wire, job.sources)


def test_actual_layout_cross_links_include_gate_and_native_search_fields(recorded_job):
    report = collect(recorded_job)
    assert report["errors"] == []
    assert all(report["checks"].values()), report["checks"]
    assert report["search"]["grid_points_searched"] == 400
    assert report["search"]["refinement_points_searched"] == 25
    assert report["search"]["refinement_points_skipped"] == 75
    assert report["native_search_memory"]["reported_peak_mib"] == 123
    assert report["native_search_memory"]["whole_pipeline_peak_established"] is False


@pytest.mark.parametrize("change", ("missing_gate", "partial_gate", "changed_artifact", "changed_http_result"))
def test_complete_http_reply_cannot_mask_unbound_scientific_evidence(recorded_job, change):
    job = recorded_job
    if change == "missing_gate":
        (job.product / "pipeline-evidence.json").unlink()
    elif change == "partial_gate":
        REPLAY.write_json(job.product / "pipeline-evidence.json", dict(job.evidence, full_pipeline_observed=False))
    elif change == "changed_artifact":
        (job.directory / "data-provenance.json").write_text('{"changed": true}\n')
    else:
        job.result = dict(job.result, reason_code="changed-after-poll")
    report = collect(job)
    checks = dict(report["checks"], source_snapshot_unchanged=True)
    rows = SUPPORT.evaluate(job.result, job.labels, job.mapping)
    outcome = REPLAY.assess_http(job.result, rows, checks, {"returncode": 0}, http_receipt(job.result), True, 4)
    assert outcome["passed"] is False
    assert outcome["supported_decision"] is False
    assert outcome["supported_localization_passed"] is False


def test_expected_inconclusive_remains_failure_at_every_distance_tier(recorded_job):
    result = dict(recorded_job.result, status="inconclusive", reason_code="ambiguous_locations")
    original = deepcopy(result)
    rows = SUPPORT.evaluate(result, recorded_job.labels, recorded_job.mapping, error=0.01)
    outcome = REPLAY.assess_http(result, rows, complete_checks(), {"returncode": 0}, http_receipt(result), True, 4)
    assert outcome["http_transport_passed"] is True
    assert outcome["producer_reported_success"] is False
    assert outcome["supported_decision"] is False
    assert outcome["supported_localization_at_m"] == {"100": False, "500": False, "1000": False}
    assert outcome["passed"] is False
    assert result == original


def test_complete_supported_control_passes_only_the_leading_distance_tiers(recorded_job):
    job = recorded_job
    rows = SUPPORT.evaluate(job.result, job.labels, job.mapping, error=1000)
    outcome = REPLAY.assess_http(job.result, rows, complete_checks(), {"returncode": 0}, http_receipt(job.result), True, 4)
    assert outcome["passed"] is True
    assert outcome["supported_localization_at_m"] == {"100": False, "500": False, "1000": True}
    rows[0]["within_m"]["1000"] = False
    rows.extend(SUPPORT.evaluate(job.result, job.labels, job.mapping, error=0.01))
    assert REPLAY.assess_http(job.result, rows, complete_checks(), {"returncode": 0},
                             http_receipt(job.result), True, 4)["passed"] is False


@pytest.mark.parametrize("key", sorted(REPLAY.HTTP_REQUIRED_CHECKS))
def test_missing_runner_gate_cannot_reuse_legacy_acceptance(recorded_job, key):
    checks = complete_checks()
    del checks[key]
    job = recorded_job
    outcome = REPLAY.assess_http(job.result, SUPPORT.evaluate(job.result, job.labels, job.mapping), checks,
                                {"returncode": 0}, http_receipt(job.result), True, 4)
    assert outcome["passed"] is False
    assert outcome["supported_decision"] is False


def test_unproven_stop_cannot_keep_supported_decision_true(recorded_job):
    job = recorded_job
    outcome = REPLAY.assess_http(job.result, SUPPORT.evaluate(job.result, job.labels, job.mapping), complete_checks(),
                                {"returncode": 0}, http_receipt(job.result), False, 4)
    assert outcome["producer_reported_success"] is True
    assert outcome["supported_decision"] is False
    assert outcome["supported_localization_passed"] is False
    assert outcome["passed"] is False


@pytest.mark.parametrize("key", ("verification_passed", "http_checks_passed", "pipeline_evidence_passed", "full_pipeline_observed"))
def test_http_and_stage_receipts_are_required_for_acceptance(recorded_job, key):
    job = recorded_job
    receipt = http_receipt(job.result, **{key: False})
    outcome = REPLAY.assess_http(job.result, SUPPORT.evaluate(job.result, job.labels, job.mapping), complete_checks(),
                                {"returncode": 0}, receipt, True, 4)
    assert outcome["http_transport_passed"] is False
    assert outcome["supported_decision"] is False
    assert outcome["supported_localization_at_m"] == {"100": False, "500": False, "1000": False}
    assert outcome["supported_localization_passed"] is False
    assert outcome["passed"] is False


@pytest.mark.parametrize("value", (False, None))
def test_unverified_producer_success_cannot_pass_any_localization_tier(recorded_job, value):
    job = recorded_job
    receipt = http_receipt(job.result)
    if value is None:
        del receipt["supported_decision"]
    else:
        receipt["supported_decision"] = value
    outcome = REPLAY.assess_http(job.result, SUPPORT.evaluate(job.result, job.labels, job.mapping), complete_checks(),
                                {"returncode": 0}, receipt, True, 4)
    assert outcome["producer_reported_success"] is True
    assert outcome["supported_decision"] is False
    assert outcome["supported_localization_at_m"] == {"100": False, "500": False, "1000": False}
    assert outcome["supported_localization_passed"] is False
    assert outcome["passed"] is False


@pytest.mark.parametrize("defect", ("outer_timeout", "forced_kill", "wrong_signal", "service_failed",
    "different_job", "not_preserved", "interrupted", "interruption_signal"))
def test_unproven_shutdown_keeps_truth_unopened(tmp_path, monkeypatch, defect):
    product = tmp_path / "http"
    product.mkdir()
    result = {"job_id": "1" * 32, "status": "inconclusive"}
    http = http_receipt(result)
    execution = {"returncode": 1}
    if defect == "outer_timeout":
        execution["timed_out"] = True
    elif defect == "forced_kill":
        http["service"]["forced_kill"] = True
    elif defect == "wrong_signal":
        http["service"]["shutdown_signal"] = "SIGTERM"
    elif defect == "service_failed":
        http["service"]["returncode"] = -9
    elif defect == "different_job":
        http["job_id"] = "2" * 32
    elif defect == "interrupted":
        http["interrupted"] = True
    elif defect == "interruption_signal":
        http["interruption_signal"] = "SIGTERM"
    else:
        http["terminal_result_preserved_after_shutdown"] = False
    REPLAY.write_json(product / "http-verification.json", http)
    REPLAY.write_json(product / "result.json", result)
    evaluation = tmp_path / "evaluation"
    (evaluation / "truth").mkdir(parents=True)
    (evaluation / "truth/labels.json").write_text("must never be parsed or hashed")
    receipt = {"evaluation_truth_opened": False, "evaluation_truth_loaded": False}
    actual_read, opened = REPLAY.read_json, []
    def read(path):
        opened.append(Path(path))
        assert not Path(path).is_relative_to(evaluation)
        return actual_read(path)
    monkeypatch.setattr(REPLAY, "read_json", read)
    with pytest.raises(RuntimeError, match="labels remain unopened"):
        REPLAY.finish_evaluation(receipt, tmp_path, tmp_path / "inputs", evaluation, {}, {}, execution)
    assert receipt["evaluation_truth_opened"] is False
    assert receipt["evaluation_truth_loaded"] is False
    assert len(opened) == 2


def test_expected_status_mismatch_allows_post_shutdown_diagnostics():
    result = {"job_id": "1" * 32, "status": "inconclusive"}
    receipt = http_receipt(result, verification_passed=False, expectation_matched=False)
    assert REPLAY.ready_for_truth(result, {"returncode": 1}, receipt) is True


@pytest.mark.parametrize("change", ({"interrupted": True}, {"interruption_signal": "SIGTERM"}))
def test_interrupted_verification_cannot_pass_even_with_success_flags(recorded_job, change):
    job = recorded_job
    receipt = http_receipt(job.result, **change)
    outcome = REPLAY.assess_http(job.result, SUPPORT.evaluate(job.result, job.labels, job.mapping), complete_checks(),
                                {"returncode": 0}, receipt, True, 4)
    assert outcome["http_transport_passed"] is False
    assert outcome["supported_decision"] is False
    assert outcome["supported_localization_at_m"] == {"100": False, "500": False, "1000": False}
    assert outcome["passed"] is False


def test_failed_run_inventory_never_reads_evaluation_files(tmp_path, monkeypatch):
    for name in ("evaluation/truth/labels.json", "evaluation/flight-id-mapping.json", "fixture/generation.json"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unopened evaluation file")
    (tmp_path / "worker.log").write_text("preserved diagnostic")
    original = REPLAY.file_record
    def record(path):
        assert not REPLAY.UPLOAD.evaluation_path(Path(path), tmp_path)
        return original(path)
    monkeypatch.setattr(REPLAY, "file_record", record)
    REPLAY.write_inventory(tmp_path, include_evaluation=False)
    manifest = REPLAY.read_json(tmp_path / "artifact-manifest.json")
    assert set(manifest["files"]) == {"worker.log"}
    assert manifest["evaluation_files_included"] is False


def test_stage_artifact_hashes_reject_escape_and_changed_bytes(tmp_path):
    directory = tmp_path / "job"
    directory.mkdir()
    path = directory / "decision.json"
    path.write_text("{}")
    evidence = {"artifacts": {"decision.json": {key: REPLAY.file_record(path)[key] for key in ("bytes", "sha256")}}}
    assert REPLAY.pipeline_artifacts_match(directory, evidence)
    path.write_text('{"changed": true}')
    assert not REPLAY.pipeline_artifacts_match(directory, evidence)
    for name in ("../outside.json", str(tmp_path / "outside.json")):
        assert not REPLAY.pipeline_artifacts_match(directory, {"artifacts": {name: {}}})
    assert not REPLAY.pipeline_artifacts_match(directory, {"artifacts": {}})


def test_snapshot_includes_executed_verifier_and_detects_post_snapshot_edits(tmp_path):
    snapshot, record = REPLAY.snapshot_sources(ROOT, tmp_path)
    assert "scripts/ci_http_replay.py" in record["files"]
    assert "scripts/verify_upload_http.py" in record["files"]
    assert REPLAY.snapshot_unchanged(snapshot, record)
    path = snapshot / "scripts/verify_upload_http.py"
    path.write_text(path.read_text() + "\n# changed control\n")
    assert not REPLAY.snapshot_unchanged(snapshot, record)


def test_total_budget_reserves_cleanup_and_never_resets_per_stage(monkeypatch):
    monkeypatch.setattr(REPLAY.time, "monotonic", lambda: 120)
    assert REPLAY.remaining_budget(100, 100, cap=300) == 50
    assert REPLAY.remaining_budget(100, 100, reserve_s=60) == 20
    monkeypatch.setattr(REPLAY.time, "monotonic", lambda: 175)
    with pytest.raises(TimeoutError, match="Total replay budget"):
        REPLAY.remaining_budget(100, 100)


@pytest.mark.parametrize("failure", ("source_snapshot_changed", "artifact_inventory_failed", "time_budget_exceeded"))
def test_finalization_failure_clears_all_acceptance_without_rewriting_producer(tmp_path, monkeypatch, failure):
    output = tmp_path / "run"
    snapshot = output / "implementation"
    snapshot.mkdir(parents=True)
    source = snapshot / "source.py"
    source.write_text("original source\n")
    receipt = {"passed": True, "supported_decision": True, "supported_localization_passed": True,
        "supported_localization_at_m": {"100": True, "500": True, "1000": True},
        "producer_reported_success": True, "job": {"status": "succeeded"}, "http_transport_passed": True,
        "leading_prediction_error_m": 0.01, "evaluation_truth_opened": True,
        "implementation": {"files": {"source.py": REPLAY.file_record(source)}}}
    if failure == "source_snapshot_changed":
        source.write_text("changed source\n")
    elif failure == "artifact_inventory_failed":
        outside = tmp_path / "outside.txt"
        outside.write_text("not contained evidence")
        (output / "unexpected-link.txt").symlink_to(outside)
    monkeypatch.setattr(REPLAY.time, "monotonic", lambda: 121 if failure == "time_budget_exceeded" else 1)
    REPLAY.finalize_receipt(receipt, output, 0, 120)
    saved = REPLAY.read_json(output / "acceptance.json")
    assert saved["acceptance_invalidations"] == [failure]
    assert saved["passed"] is False
    assert saved["supported_decision"] is False
    assert saved["supported_localization_passed"] is False
    assert saved["supported_localization_at_m"] == {"100": False, "500": False, "1000": False}
    assert saved["producer_reported_success"] is True
    assert saved["job"]["status"] == "succeeded"
    assert saved["http_transport_passed"] is True
    assert saved["leading_prediction_error_m"] == 0.01


def test_existing_output_receipt_is_never_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "acceptance.json"
    sentinel.write_bytes(b"immutable historical receipt")
    with pytest.raises(SystemExit) as error:
        REPLAY.main(["--output", str(output)])
    assert error.value.code == 2
    assert sentinel.read_bytes() == b"immutable historical receipt"
    assert list(output.iterdir()) == [sentinel]


@pytest.mark.parametrize("argument,value", (("--timeout-s", "nan"), ("--timeout-s", "60"),
    ("--timeout-s", "inf"), ("--seed", "-1"), ("--events", "2")))
def test_invalid_protocol_is_rejected_before_output_creation(tmp_path, argument, value):
    output = tmp_path / "unused"
    with pytest.raises(SystemExit) as error:
        REPLAY.main(["--output", str(output), argument, value])
    assert error.value.code == 2
    assert not output.exists()


def test_cli_predeclares_strict_success_and_exposes_replay_parameters(tmp_path, monkeypatch):
    captured = {}
    def replay(args, repo):
        captured.update(vars(args))
        return 1
    monkeypatch.setattr(REPLAY, "replay", replay)
    assert REPLAY.main(["--output", str(tmp_path / "new"), "--events", "6", "--seed", "23",
                        "--time-budget-s", "120"]) == 1
    assert captured["expect_status"] == "succeeded"
    assert (captured["events"], captured["seed"], captured["timeout_s"]) == (6, 23, 120)
