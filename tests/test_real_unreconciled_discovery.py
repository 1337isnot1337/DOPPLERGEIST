"""Opt-in regression using an existing real discovery checkpoint, not audio synthesis."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dopplergeist import automatic
from dopplergeist.matching import UnreconciledHarmonicGroup, prepare_events


def test_unreconciled_real_group_is_inconclusive(tmp_path, monkeypatch):
    checkpoint = os.environ.get("DOPPLERGEIST_UNRECONCILED_CHECKPOINT")
    if not checkpoint:
        pytest.skip("Set DOPPLERGEIST_UNRECONCILED_CHECKPOINT to a real saved job")
    checkpoint = Path(checkpoint)
    request = json.loads((checkpoint / "request.json").read_text())
    metadata = json.loads((checkpoint / "intake/recording.json").read_text())
    discovery = (checkpoint / "discovery/discovery.json").read_bytes()
    events = json.loads(discovery)["events"]
    with pytest.raises(UnreconciledHarmonicGroup):
        prepare_events(events)

    # Exercise the orchestration path using the saved measured ridges. The
    # bypassed clock gate is a software control; no flight search is performed.
    recording = SimpleNamespace(metadata=metadata, time_status="ready")
    monkeypatch.setattr(automatic, "_load_audio_checkpoint", lambda *args: (recording, events))
    (tmp_path / "discovery").mkdir()
    (tmp_path / "discovery/discovery.json").write_bytes(discovery)
    result = automatic.analyze(request, tmp_path, resume=True)
    assert result["status"] == "inconclusive"
    assert result["reason_code"] == "unreconciled_discovery_group"
    assert "no location search was performed" in result["message"]
    assert result["events"] == events
    assert result["coverage"]["search_complete"] is False
    assert (tmp_path / result["artifacts"]["discovery"]).read_bytes() == discovery
    assert not (tmp_path / "search").exists()
