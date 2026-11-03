"""Upgrade a subset of an actual stopped job; no recording or tracks generated."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

import pytest

from dopplergeist.automatic import _load_audio_checkpoint
from dopplergeist.checkpoint_resume import compatible_checkpoint_runs, upgrade_legacy_job
from dopplergeist.finite_search import RetentionLedger


def test_saved_scored_tile_and_ledger_survive_upgrade(request):
    location = os.environ.get("DOPPLERGEIST_REAL_SAVED_JOB")
    if not location:
        pytest.skip("Supply the actual stopped pre-batching job")
    source = Path(location)
    temporary = tempfile.TemporaryDirectory(prefix="checkpoint-upgrade-test-", dir=source.parent.parent)
    request.addfinalizer(temporary.cleanup)
    tmp_path = Path(temporary.name)
    for name in ("request.json", "operator.json", "resume.json", "result.json"):
        shutil.copy2(source / name, tmp_path / name)
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
    assert compatible_checkpoint_runs(tmp_path / "search", report["new_run_hash"]) == {
        report["old_run_hash"], report["new_run_hash"]}
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
