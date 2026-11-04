"""Continue a real cb996dc job; never generate audio, tracks or scored modes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

import pytest

from dopplergeist import checkpoint_resume, data_access, native_cpa
from dopplergeist.automatic import _load_audio_checkpoint, _search
from dopplergeist.data_access import content_hash
from dopplergeist.finite_search import RetentionLedger


@pytest.fixture(scope="module")
def real_job():
    location = os.environ.get("DOPPLERGEIST_REAL_CB996DC_JOB")
    if not location:
        pytest.skip("Supply an actual stopped cb996dc job with nonempty coarse checkpoints")
    source = Path(location)
    manifest = json.loads((source / "search/manifest.json").read_text())
    assert content_hash(manifest["configuration"]) == manifest["run_hash"]
    assert content_hash(manifest["configuration"]["code"]) == checkpoint_resume.CB996DC_CODE_FINGERPRINT
    assert json.loads((source / "result.json").read_text())["status"] in {"cancelled", "failed", "inconclusive"}
    tiles = [path for path in sorted((source / "search").glob("tile-*.json"))
             if json.loads(path.read_text())["payload"].get("ranked")]
    assert tiles, "The recorded job must include actual scored candidates"
    return source, manifest, tiles


def _copy_job(source, destination):
    # request.json continues to identify the unchanged original input.mp3.
    # Copy metadata/ledgers independently so fault injection cannot alter source.
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("input.mp3"))
    return destination


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def test_real_nonempty_tiles_resume_after_pinned_upgrade(real_job, tmp_path):
    source, original, tiles = real_job
    original_files = {path: _digest(path) for path in [source / "search/manifest.json",
        source / "search/retention.sqlite", source / "resume.json", source / "operator.json", *tiles]}
    job = _copy_job(source, tmp_path / "job")
    saved = {path.name: path.read_bytes() for path in tiles}
    expected_ranked = json.loads((source / "search/search-report.json").read_text())["ranked"]
    report = checkpoint_resume.upgrade_legacy_job(job)
    assert report["version"] == 3
    assert report["upgrade_kind"] == "exact_python_cb996dc_v1"
    assert report["legacy_first_batch"] is False
    assert report["old_run_hash"] == original["run_hash"]
    assert report["target_code_fingerprint"] == checkpoint_resume.CB996DC_TARGET_FINGERPRINT
    manifest = json.loads((job / "search/manifest.json").read_text())
    operator = json.loads((job / "operator.json").read_text())
    assert operator["filters"] == manifest["configuration"]["filters"]
    assert operator["filters"]["min_events"] == checkpoint_resume._combined_min_events(original["configuration"])
    assert not operator.get("resume_legacy_first_batch")
    assert checkpoint_resume.compatible_checkpoint_runs(job / "search", report["new_run_hash"]) == {
        report["new_run_hash"], report["old_run_hash"]}
    assert checkpoint_resume.compatible_checkpoint_runs(job / "search", report["old_run_hash"]) == {report["old_run_hash"]}
    for name, data in saved.items():
        assert (job / "search" / name).read_bytes() == data
        assert (Path(report["previous_search"]) / name).read_bytes() == data
    assert checkpoint_resume.upgrade_legacy_job(job) is None
    request = json.loads((job / "request.json").read_text())
    recording, events = _load_audio_checkpoint(job, request, operator)
    result, *_ = _search(request, recording, events, job, operator, lambda *args, **kwargs: None)
    assert result["run_hash"] == report["new_run_hash"]
    assert result["tiles_resumed"] == result["tiles_completed"] > 0
    assert result["tile_failures"] == []
    assert result["ranked"] == expected_ranked
    ledger = RetentionLedger(job / "search/retention.sqlite", report["new_run_hash"],
                             "matched_group_support_minus_normalized_residual")
    for name, data in saved.items():
        assert (job / "search" / name).read_bytes() == data
        payload = json.loads(data)["payload"]
        stage = "coarse:" + Path(name).stem.removeprefix("tile-")
        assert ledger.stage_valid(stage, payload["retention_checksum"])
    assert {path: _digest(path) for path in original_files} == original_files


@pytest.mark.parametrize("change", ["producer", "consumer", "manifest", "runtime", "native_cpa", "native_index", "active"])
def test_unverified_continuations_leave_real_checkpoint_unchanged(real_job, tmp_path, monkeypatch, change):
    source, original, _ = real_job
    job = tmp_path / "job"
    (job / "search").mkdir(parents=True)
    shutil.copy2(source / "search/manifest.json", job / "search/manifest.json")
    shutil.copy2(source / "result.json", job / "result.json")
    manifest = json.loads((job / "search/manifest.json").read_text())
    if change == "producer":
        manifest["configuration"]["code"]["matching.py"] = "0" * 64
    elif change == "consumer":
        # A later geometry change must invalidate the measured consumer even
        # when its checkpoint format and all other source files stay unchanged.
        from dopplergeist import automatic
        digest = automatic._digest
        monkeypatch.setattr(automatic, "_digest",
                            lambda path: "0" * 64 if Path(path).name == "geometry.py" else digest(path))
    elif change == "manifest":
        manifest["run_hash"] = "0" * 64
    elif change == "runtime":
        manifest["configuration"]["runtime"]["python"] += ".changed"
    elif change == "native_cpa":
        monkeypatch.setattr(native_cpa, "CPA_BACKEND", "native-c-cpa-v1")
    elif change == "native_index":
        monkeypatch.setattr(data_access, "_native_payload_columns", object())
    elif change == "active":
        state = json.loads((job / "result.json").read_text())
        state["status"] = "running"
        (job / "result.json").write_text(json.dumps(state))
    if change in {"producer", "runtime"}:
        manifest["run_hash"] = content_hash(manifest["configuration"])
    (job / "search/manifest.json").write_text(json.dumps(manifest))
    before = (job / "search/manifest.json").read_bytes()
    if change in {"producer", "consumer", "manifest"}:
        assert checkpoint_resume.upgrade_legacy_job(job) is None
    else:
        with pytest.raises(ValueError, match={"runtime": "runtime changed", "native_cpa": "Python closest-approach", "native_index": "Python flight decoder", "active": "Stop the previous job"}[change]):
            checkpoint_resume.upgrade_legacy_job(job)
    assert (job / "search/manifest.json").read_bytes() == before
    assert not list(job.glob("checkpoint-upgrade*"))


def test_real_upgrade_rolls_back_operator_and_producer_binding(real_job, tmp_path, monkeypatch):
    source, manifest, tiles = real_job
    job = _copy_job(source, tmp_path / "job")
    names = ("search/manifest.json", "resume.json", "operator.json")
    before = {name: (job / name).read_bytes() for name in names}
    write_json = checkpoint_resume.write_json

    def fail_operator(path, value):
        if Path(path) == job / "operator.json":
            raise OSError("interrupted real checkpoint upgrade")
        return write_json(path, value)

    monkeypatch.setattr(checkpoint_resume, "write_json", fail_operator)
    with pytest.raises(OSError, match="interrupted real checkpoint"):
        checkpoint_resume.upgrade_legacy_job(job)
    assert {name: (job / name).read_bytes() for name in names} == before
    assert not (job / "checkpoint-upgrade.json").exists()
    with sqlite3.connect((job / "search/retention.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT identity FROM run").fetchone() == (manifest["run_hash"],)
    assert (job / "search" / tiles[0].name).read_bytes() == tiles[0].read_bytes()


def test_cb996dc_report_cannot_authorize_an_unverified_target(real_job, tmp_path):
    source, _, _ = real_job
    job = _copy_job(source, tmp_path / "job")
    report = checkpoint_resume.upgrade_legacy_job(job)
    report["target_code_fingerprint"] = "0" * 64
    (job / "checkpoint-upgrade.json").write_text(json.dumps(report))
    assert checkpoint_resume.compatible_checkpoint_runs(job / "search", report["new_run_hash"]) == {report["new_run_hash"]}
