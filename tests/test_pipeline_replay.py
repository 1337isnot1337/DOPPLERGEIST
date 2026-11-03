"""Failure and provenance boundaries for the independent replay runner."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest


spec = importlib.util.spec_from_file_location(
    "verify_pipeline_replay", Path(__file__).resolve().parents[1] / "scripts/verify_pipeline_replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_real_child_failure_keeps_output_and_exit_status(tmp_path):
    result = replay.execute([sys.executable, "-c", "print('failure evidence'); raise SystemExit(7)"],
                            tmp_path, 10)
    assert result["exit_code"] == 7
    assert result["timed_out"] is False
    assert "failure evidence" in (tmp_path / "pipeline.log").read_text()


def test_real_child_timeout_cannot_be_reported_as_success(tmp_path):
    result = replay.execute([sys.executable, "-u", "-c",
                             "import time; print('started'); time.sleep(60)"], tmp_path, 0.25)
    assert result["timed_out"] is True
    assert result["exit_code"] != 0
    assert "started" in (tmp_path / "pipeline.log").read_text()
    assert result["elapsed_s"] < 10


def test_missing_case_is_recorded_and_later_cases_still_run(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "ROOT", tmp_path)
    monkeypatch.setattr(replay, "runtime", lambda: {})
    output = tmp_path / "receipts"
    status = replay.main(["--case", "synthetic-two-events", "--case", "reference-local",
                          "--output", str(output)])
    summary = json.loads((output / "verification.json").read_text())
    assert status == 1
    assert len(summary["cases"]) == 2
    assert all(case["status"] == "failed" for case in summary["cases"])
    assert summary["automatic_upload_goal_verified"] is False
    with pytest.raises(FileExistsError):
        replay.main(["--output", str(output)])


def test_evaluation_failure_preserves_successful_child_receipt(tmp_path, monkeypatch):
    config_dir = tmp_path / "data/synthetic"
    config_dir.mkdir(parents=True)
    config = config_dir / "two-events.json"
    config.write_text(json.dumps({"audio": "recording.wav", "tracks": [], "terrain": {}, "events": []}))
    (config_dir / "recording.wav").write_bytes(b"source fixture")
    monkeypatch.setattr(replay, "ROOT", tmp_path)

    def completed(command, output, timeout_s):
        report = output / "pipeline/report.json"
        report.parent.mkdir()
        report.write_text('{"best":{}}')
        return {"exit_code": 0, "command": command, "timed_out": False}

    monkeypatch.setattr(replay, "execute", completed)
    result = replay.verify_case("synthetic-two-events", tmp_path / "case", 10)
    assert result["exit_code"] == 0
    assert result["status"] == "failed"
    assert result["report"]["sha256"] == replay.digest(tmp_path / "case/pipeline/report.json")["sha256"]
    assert "FileNotFoundError" in result["error"]


def test_updated_error_thresholds_preserve_the_historical_faint_receipt():
    reference = replay.ROOT / replay.CASES["reference-faint"]["baseline"]
    original = reference.read_bytes()
    report = json.loads(original)
    evaluation = replay.evaluate("reference-faint", report)
    assert evaluation["within_100_m"] is False
    assert evaluation["within_500_m"] is True
    assert evaluation["within_1000_m"] is True
    assert evaluation["baseline_reproduced"] is True
    assert reference.read_bytes() == original
