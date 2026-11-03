"""Upgrade a subset of an actual stopped job; no recording or tracks generated."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

import pytest

import dopplergeist.checkpoint_resume as checkpoint_resume
from dopplergeist.automatic import _load_audio_checkpoint
from dopplergeist.checkpoint_resume import (BATCHED_REFERENCE_RUN, ORIGINAL_REFERENCE_RUN,
    compatible_checkpoint_runs, upgrade_legacy_job)
from dopplergeist.finite_search import RetentionLedger


@pytest.mark.parametrize("source_variable", ["DOPPLERGEIST_REAL_SAVED_JOB", "DOPPLERGEIST_REAL_BATCHED_JOB"])
def test_saved_scored_tile_and_ledger_survive_upgrade(request, source_variable):
    location = os.environ.get(source_variable)
    if not location:
        pytest.skip("Supply the actual stopped pre-batching job")
    source = Path(location)
    temporary = tempfile.TemporaryDirectory(prefix="checkpoint-upgrade-test-", dir=source.parent.parent)
    request.addfinalizer(temporary.cleanup)
    tmp_path = Path(temporary.name)
    for name in ("request.json", "operator.json", "resume.json", "result.json"):
        shutil.copy2(source / name, tmp_path / name)
    if (source / "checkpoint-upgrade.json").exists():
        shutil.copy2(source / "checkpoint-upgrade.json", tmp_path / "checkpoint-upgrade.json")
    for name in ("intake/recording.f32", "intake/recording.json", "intake/intake.json",
                 "discovery/discovery.json", "search/manifest.json", "search/retention.sqlite"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.hardlink_to(source / name)
    tile = source / "search/tile-30_7.json"
    if not tile.exists():
        pytest.skip("The saved real scored tile is unavailable")
    original = tile.read_bytes()
    payload = json.loads(original)["payload"]
    assert payload["counts"]["candidates"] > 0
    (tmp_path / "search" / tile.name).hardlink_to(tile)
    with sqlite3.connect(source / "search/retention.sqlite") as db:
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                  for name in ("stages", "records", "bounds")}
    report = upgrade_legacy_job(tmp_path)
    assert report["tiles_preserved"] == 1
    assert (tmp_path / "search" / tile.name).read_bytes() == original
    accepted = {report["old_run_hash"], report["new_run_hash"]}
    if source_variable == "DOPPLERGEIST_REAL_BATCHED_JOB":
        assert report["version"] == 2
        accepted.update([ORIGINAL_REFERENCE_RUN, BATCHED_REFERENCE_RUN])
        assert json.loads(Path(report["previous_upgrade_report"]).read_text()) == json.loads(
            (source / "checkpoint-upgrade.json").read_text())
    assert compatible_checkpoint_runs(tmp_path / "search", report["new_run_hash"]) == accepted
    assert compatible_checkpoint_runs(tmp_path / "search", report["old_run_hash"]) == {report["old_run_hash"]}
    assert json.loads((tmp_path / "search" / tile.name).read_text())["payload"] == payload
    assert (Path(report["previous_search"]) / tile.name).read_bytes() == original
    assert tile.read_bytes() == original
    with sqlite3.connect(tmp_path / "search/retention.sqlite") as db:
        assert db.execute("SELECT identity FROM run").fetchone() == (report["new_run_hash"],)
        assert {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in counts} == counts
    ledger = RetentionLedger(tmp_path / "search/retention.sqlite", report["new_run_hash"],
                             "matched_group_support_minus_normalized_residual")
    assert ledger.stage_valid("coarse:30_7", payload["retention_checksum"])
    operator = json.loads((tmp_path / "operator.json").read_text())
    assert operator["resume_legacy_first_batch"] is True
    _load_audio_checkpoint(tmp_path, json.loads((tmp_path / "request.json").read_text()), operator)
    assert upgrade_legacy_job(tmp_path) is None


@pytest.mark.parametrize("change", ["parent_report", "scoring_source"])
def test_batched_upgrade_requires_known_parent_and_target(tmp_path, monkeypatch, change):
    location = os.environ.get("DOPPLERGEIST_REAL_BATCHED_JOB")
    if not location:
        pytest.skip("Supply an actual saved batched job")
    source = Path(location)
    (tmp_path / "search").mkdir()
    for name in ("search/manifest.json", "checkpoint-upgrade.json"):
        shutil.copy2(source / name, tmp_path / name)
    if change == "parent_report":
        path = tmp_path / "checkpoint-upgrade.json"
        report = json.loads(path.read_text())
        report["legacy_first_batch"] = False
        path.write_text(json.dumps(report))
    else:
        monkeypatch.setitem(checkpoint_resume.THROUGHPUT_SOURCES, "search.py", "0" * 64)
    before = (tmp_path / "search/manifest.json").read_bytes()
    assert upgrade_legacy_job(tmp_path) is None
    assert (tmp_path / "search/manifest.json").read_bytes() == before


def test_batched_upgrade_restores_parent_binding_on_failure(tmp_path, monkeypatch):
    location = os.environ.get("DOPPLERGEIST_REAL_BATCHED_JOB")
    if not location:
        pytest.skip("Supply an actual saved batched job")
    source = Path(location)
    job = tmp_path / "job"
    shutil.copytree(source, job)
    names = ("checkpoint-upgrade.json", "resume.json", "operator.json", "search/manifest.json")
    before = {name: (job / name).read_bytes() for name in names}
    original = checkpoint_resume.write_json

    def fail_operator(path, value):
        if Path(path) == job / "operator.json":
            raise OSError("interrupted upgrade")
        return original(path, value)

    monkeypatch.setattr(checkpoint_resume, "write_json", fail_operator)
    with pytest.raises(OSError, match="interrupted upgrade"):
        upgrade_legacy_job(job)
    assert {name: (job / name).read_bytes() for name in names} == before
    with sqlite3.connect(job / "search/retention.sqlite") as db:
        assert db.execute("SELECT identity FROM run").fetchone() == (BATCHED_REFERENCE_RUN,)
