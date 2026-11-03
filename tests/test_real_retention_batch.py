"""Transaction checks against recorded empty tiles from the real reference run."""
import json
from pathlib import Path
import sqlite3

import pytest

from dopplergeist.data_access import DataUnavailable, write_json
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.tiled_search import merge_candidates


@pytest.fixture
def real_tiles():
    path = Path(__file__).parent / "data/reference-empty-tiles-real.json"
    fixture = json.loads(path.read_text())
    assert fixture["tiles"]
    for tile in fixture["tiles"]:
        payload = tile["checkpoint"]["payload"]
        assert payload["tracks"] == 0 and payload["ranked"] == [] and payload["counts"] == {}
    return fixture


def ledger(path, fixture):
    return RetentionLedger(path, fixture["tiles"][0]["checkpoint"]["run_hash"], fixture["score_kind"])


def record_tile(target, tile):
    checksum = tile["checkpoint"]["payload"]["retention_checksum"]
    for phase in ("coarse", "global"):
        stage = f"{phase}:{tile['tile_id']}"
        assert target.record(stage, [], [], 0) == checksum
        assert target.checksum(stage) == checksum


def contents(target):
    with target.connect() as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                for table in ("run", "stages", "records", "bounds")}


def test_recorded_empty_stage_rows_and_checksums_match_in_batches(real_tiles, tmp_path):
    serial = ledger(tmp_path / "serial.sqlite", real_tiles)
    batched = ledger(tmp_path / "batched.sqlite", real_tiles)
    for tile in real_tiles["tiles"]:
        record_tile(serial, tile)
    for first in range(0, len(real_tiles["tiles"]), 3):
        with batched.batch():
            for tile in real_tiles["tiles"][first:first + 3]:
                record_tile(batched, tile)
    assert contents(batched) == contents(serial)
    for tile in real_tiles["tiles"]:
        expected = tile["checkpoint"]["payload"]["retention_checksum"]
        for phase in ("coarse", "global"):
            assert batched.stage_valid(f"{phase}:{tile['tile_id']}", expected)


def test_empty_tile_batches_preserve_previous_real_retained_modes(real_tiles, tmp_path):
    # Empty tiles can still write nonempty global stages after a supported tile.
    # These are archived fits from the original recording, not invented scores.
    rows = json.loads((Path(__file__).parent / "data/reference-retention-real.json").read_text())["rows"]
    serial = ledger(tmp_path / "retained-serial.sqlite", real_tiles)
    batched = ledger(tmp_path / "retained-batched.sqlite", real_tiles)

    def replay(target):
        ranked = merge_candidates(rows, 3, ledger=target, stage="recorded-fits")
        for tile in real_tiles["tiles"]:
            target.record(f"coarse:{tile['tile_id']}", [], [], 0)
            ranked = merge_candidates(ranked, 3, ledger=target, stage=f"global:{tile['tile_id']}")
        return ranked

    expected = replay(serial)
    with batched.batch():
        actual = replay(batched)
    assert actual == expected
    assert contents(batched) == contents(serial)
    for tile in real_tiles["tiles"]:
        stage = f"global:{tile['tile_id']}"
        assert batched.stage_valid(stage, serial.checksum(stage))


def test_interrupted_batch_invalidates_checkpoint_until_replayed(real_tiles, tmp_path):
    writer = ledger(tmp_path / "resume.sqlite", real_tiles)
    reader = ledger(writer.path, real_tiles)
    tile = real_tiles["tiles"][0]
    stage = f"coarse:{tile['tile_id']}"
    expected = tile["checkpoint"]["payload"]["retention_checksum"]
    checkpoint = tmp_path / f"tile-{tile['tile_id']}.json"
    with pytest.raises(RuntimeError, match="interrupted"):
        with writer.batch():
            record_tile(writer, tile)
            write_json(checkpoint, tile["checkpoint"])
            assert writer.stage_valid(stage, expected)
            assert not reader.stage_valid(stage, expected)
            raise RuntimeError("interrupted batch")
    assert checkpoint.exists()
    assert not reader.stage_valid(stage, expected)
    with writer.batch():
        record_tile(writer, tile)
    assert reader.stage_valid(stage, expected)


def test_caught_connection_error_does_not_commit_partial_batch(real_tiles, tmp_path):
    target = ledger(tmp_path / "caught.sqlite", real_tiles)
    tile = real_tiles["tiles"][0]
    with pytest.raises(DataUnavailable, match="not committed"):
        with target.batch():
            record_tile(target, tile)
            try:
                with target.connect() as db:
                    db.execute("SELECT * FROM nonexistent_batch_test_table")
            except sqlite3.OperationalError:
                pass
    assert not target.stage_valid(f"coarse:{tile['tile_id']}", tile["checkpoint"]["payload"]["retention_checksum"])


def test_nested_batch_is_rejected_and_outer_work_rolls_back(real_tiles, tmp_path):
    target = ledger(tmp_path / "nested.sqlite", real_tiles)
    tile = real_tiles["tiles"][0]
    with pytest.raises(RuntimeError, match="Nested retention batches"):
        with target.batch():
            record_tile(target, tile)
            with target.batch():
                pass
    assert not target.stage_valid(f"coarse:{tile['tile_id']}", tile["checkpoint"]["payload"]["retention_checksum"])
