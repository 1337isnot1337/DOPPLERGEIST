"""Source-band controls using complete resamplings of one real piston recording."""
import gzip
import json
from pathlib import Path

import pytest

from dopplergeist.advanced_discovery import verify_tracks
from dopplergeist.discovery import discover_events
from dopplergeist.intake import IntakeRecording, intake_recording


FIXTURES = Path(__file__).parent / "fixtures"


def recorded_input(folder, rate):
    source = folder / "recorded.wav"
    source.write_bytes(gzip.decompress((FIXTURES / f"real_lowrate_piston_{rate}hz.wav.gz").read_bytes()))
    return source


@pytest.fixture(scope="module")
def lowrate_scan(tmp_path_factory):
    folder = tmp_path_factory.mktemp("actual-lowrate-scan")
    source = recorded_input(folder, 1000)
    recording = intake_recording(source, folder / "intake")
    events = discover_events(recording, output_dir=folder / "discovery",
                             plot_summary=False, plot_event_details=False, event_audio=False)
    saved = json.loads((folder / "discovery/discovery.json").read_text())
    return source, folder, recording, events, saved


def test_upsampling_preserves_original_measured_band(lowrate_scan):
    _, _, recording, events, saved = lowrate_scan
    assert recording.metadata["sample_rate_hz"] == 4000
    assert recording.source_nyquist_hz == 500
    assert events and saved["sequence_diagnostics"]
    assert saved["sequence_settings"]["source_nyquist_hz"] == 500
    for event in events:
        assert event["band_hz"][1] <= 500
        assert all(point["frequency_hz"] <= 500 for point in event["ridge"])
    assert all(item["band_hz"][1] <= 500 for item in saved["sequence_diagnostics"])


def test_independent_verification_rejects_actual_interpolation_image(lowrate_scan):
    source, folder, _, _, _ = lowrate_scan
    high = folder / "discovery/intake_high"
    recording = IntakeRecording(high / "recording.f32",
        json.loads((high / "recording.json").read_text()),
        json.loads((high / "intake.json").read_text()), source)
    artifact = json.loads(gzip.decompress((FIXTURES / "real_out_of_band_piston_ridge.json.gz").read_bytes()))
    event = artifact["event"]
    assert len(event["ridge"]) == 34
    assert min(point["frequency_hz"] for point in event["ridge"]) > recording.source_nyquist_hz
    retained, rejected, _ = verify_tracks(recording, [event], "consensus")
    assert retained == []
    assert rejected == [{"event_id": event["event_id"], "reason": "outside_source_band"}]


def test_recorded_source_below_analysis_band_returns_no_events(tmp_path):
    source = recorded_input(tmp_path, 32)
    recording = intake_recording(source, tmp_path / "intake")
    assert recording.source_nyquist_hz == 16
    events = discover_events(recording, output_dir=tmp_path / "discovery",
                             plot_summary=False, plot_event_details=False, event_audio=False)
    saved = json.loads((tmp_path / "discovery/discovery.json").read_text())
    assert events == saved["events"] == []
    assert saved["sequence_settings"]["source_nyquist_hz"] == 16
    assert saved["sequence_diagnostics"] == []
