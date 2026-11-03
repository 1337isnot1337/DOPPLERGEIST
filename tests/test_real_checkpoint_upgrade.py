"""Upgrade real stopped jobs without generating recordings or tracks."""
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
        pytest.skip("Supply an actual stopped checkpoint-compatible job")
    source = Path(location)
    state = json.loads((source / "result.json").read_text())
    if state.get("status") not in {"cancelled", "failed", "inconclusive"}:
        pytest.skip("The real job must be stopped before testing checkpoint upgrade")
    temporary = tempfile.TemporaryDirectory(prefix="checkpoint-upgrade-test-", dir=source.parent.parent)
    request.addfinalizer(temporary.cleanup)
    tmp_path = Path(temporary.name)
    for name in ("request.json", "operator.json", "resume.json", "result.json"):
        shutil.copy2(source / name, tmp_path / name)
    tile_name = os.environ.get("DOPPLERGEIST_REAL_SAVED_TILE", "tile-30_7.json")
    tile = source / "search" / tile_name
    if not tile.exists():
        pytest.skip(f"The saved real scored tile {tile_name} is unavailable")
    original = tile.read_bytes()
    payload = json.loads(original)["payload"]
    assert payload["counts"]["candidates"] > 0
    for directory in ("intake", "discovery"):
        shutil.copytree(source / directory, tmp_path / directory,
                        copy_function=lambda _src, dst: Path(dst).hardlink_to(_src))

    def ignore_search(_path, names):
        return [name for name in names if name == ".tile-workers" or name.endswith(".tmp")
                or name.startswith("retention.sqlite")]

    shutil.copytree(source / "search", tmp_path / "search",
                    copy_function=lambda _src, dst: Path(dst).hardlink_to(_src), ignore=ignore_search)
    (tmp_path / "search" / "retention.sqlite").hardlink_to(source / "search" / "retention.sqlite")
    original_tiles = {path.name for path in (tmp_path / "search").glob("tile-*.json")}
    with sqlite3.connect(source / "search/retention.sqlite") as db:
        counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                  for name in ("stages", "records", "bounds")}
    report = upgrade_legacy_job(tmp_path)
    assert report["tiles_preserved"] == len(original_tiles)
    assert {path.name for path in (tmp_path / "search").glob("tile-*.json")} == original_tiles
    assert {path.name for path in (Path(report["previous_search"]).glob("tile-*.json"))} == original_tiles
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
    tile_id = tile.stem.removeprefix("tile-")
    assert ledger.stage_valid(f"coarse:{tile_id}", payload["retention_checksum"])
    operator = json.loads((tmp_path / "operator.json").read_text())
    if report["compatible_source"] == "legacy-first-batch":
        assert report["legacy_first_batch"] is True
        assert operator["resume_legacy_first_batch"] is True
    else:
        upgraded = json.loads((tmp_path / "search/manifest.json").read_text())
        assert report["compatible_source"] == "combined-cb996dc"
        assert report["legacy_first_batch"] is False
        assert (upgraded["configuration"]["filters"]["min_events"]
                == payload["counts"]["minimum_matched_events"])
        assert "resume_legacy_first_batch" not in operator
    _load_audio_checkpoint(tmp_path, json.loads((tmp_path / "request.json").read_text()), operator)
    assert upgrade_legacy_job(tmp_path) is None


def test_combined_minimum_event_default_matches_real_checkpoint():
    location = os.environ.get("DOPPLERGEIST_REAL_SAVED_JOB")
    if not location:
        pytest.skip("Supply the real cb996dc checkpoint")
    source = Path(location)
    manifest = json.loads((source / "search/manifest.json").read_text())
    from dopplergeist.checkpoint_resume import _combined_min_events, _legacy_source_profile

    configuration = manifest["configuration"]
    assert _legacy_source_profile(configuration) == "combined-cb996dc"
    assert "min_events" not in configuration["filters"]
    assert _combined_min_events(configuration) == 2
