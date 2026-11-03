"""Checkpoint encoding parity on completed real search evidence."""
import json
import os
from pathlib import Path

import pytest

from dopplergeist.data_access import content_hash, write_json
from dopplergeist.tiled_search import _record_support


@pytest.fixture(scope="module")
def recorded_tile():
    source = os.environ.get("DOPPLERGEIST_REAL_TILE_CHECKPOINT")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_TILE_CHECKPOINT to a completed real tile JSON")
    path = Path(source)
    assert path.name.startswith("tile-"), "Supply the original completed tile filename"
    value = json.loads(path.read_text())
    assert value["payload"]["counts"]["candidates"] > 0
    assert content_hash(value["payload"]) == value["payload_hash"]
    return path, value


def test_compact_real_checkpoint_preserves_payload_and_resume_identifiers(recorded_tile, tmp_path):
    source, expected = recorded_tile
    destination = tmp_path / source.name
    write_json(destination, expected)
    readable = destination.read_text()
    assert readable.count("\n") > 1
    assert json.loads(readable) == expected

    # Replace the same checkpoint atomically; filenames and reader inputs stay
    # unchanged. The payload hash also detects signed-zero or number-type changes.
    write_json(destination, expected, compact=True)
    compact = destination.read_text()
    actual = json.loads(compact)
    assert actual == expected
    assert actual["run_hash"] == expected["run_hash"]
    assert content_hash(actual["payload"]) == actual["payload_hash"] == expected["payload_hash"]
    assert actual["payload"]["retention_checksum"] == expected["payload"]["retention_checksum"]
    assert compact.count("\n") == 1
    assert len(compact) < len(readable)
    assert not destination.with_name(destination.name + ".tmp").exists()


def test_compact_real_support_file_matches_existing_accounting(recorded_tile, tmp_path):
    source, tile = recorded_tile
    stage = "coarse:" + source.stem.removeprefix("tile-")
    relative = Path("support") / (stage.replace(":", "-") + ".json")
    previous = source.parent / relative
    if not previous.is_file():
        pytest.skip("The selected recorded tile has no saved support-accounting sidecar")
    expected = json.loads(previous.read_text())
    summary = dict.fromkeys(("unsupported_cpa_track_evaluations", "unclassified_score_candidates",
                             "bounded_score_candidates", "unbounded_score_candidates", "evaluated_trials",
                             "rejected_trials", "unknown_trials", "unreported_trial_envelopes"), 0)
    _record_support(tmp_path, stage, tile["payload"]["counts"], summary)
    compact = (tmp_path / relative).read_text()
    actual = json.loads(compact)
    assert actual == expected
    assert content_hash(actual) == content_hash(expected)
    assert compact.count("\n") == 1
