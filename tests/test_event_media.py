"""Focused checks for per-event listening/viewing media generation."""
import json
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from dopplergeist import discovery
from dopplergeist.discovery import DiscoverySettings, _event_clip_bounds, _write_event_media


def recording(tmp_path, duration_s=3.0, sample_rate_hz=24000):
    samples = (0.2 * np.sin(2 * np.pi * 440 * np.arange(int(duration_s * sample_rate_hz)) / sample_rate_hz)).astype("<f4")
    path = tmp_path / "recording.f32"
    samples.tofile(path)
    return SimpleNamespace(
        samples_path=path,
        metadata={"sample_rate_hz": sample_rate_hz, "duration_s": duration_s,
                  "source_sha256": "0" * 64},
    )


def event(event_id="event-0001", start_s=0.5, end_s=2.5, band_hz=(400.0, 480.0)):
    return {
        "event_id": event_id, "start_s": start_s, "end_s": end_s,
        "band_hz": list(band_hz), "harmonic_group_id": "harmonics-0001",
        "ridge": [
            {"time_s": start_s, "frequency_hz": band_hz[0], "weight": 3.0},
            {"time_s": (start_s + end_s) / 2, "frequency_hz": sum(band_hz) / 2, "weight": 3.5},
            {"time_s": end_s, "frequency_hz": band_hz[1], "weight": 3.0},
        ],
        "quality": {"median_contrast": 3.2, "support_fraction": 0.9},
    }


def test_event_media_writes_plot_ridge_audio_and_index(tmp_path):
    source = recording(tmp_path)
    output = tmp_path / "discovery"
    output.mkdir()
    media = _write_event_media(source, [event()], output, DiscoverySettings(),
                               plot_event_details=True, event_audio=True)
    entry = media["events"]["event-0001"]
    assert entry["image"] == "event-0001.png"
    assert entry["ridge_csv"] == "event-0001.csv"
    assert entry["audio"]["raw"] == "event-0001-audio.wav"
    assert entry["audio"]["band_limited"] == "event-0001-band.wav"
    assert entry["audio"]["truncated"] is False
    assert (output / "event-0001.png").stat().st_size > 0
    assert (output / "event-0001.csv").read_text().startswith("time_s,frequency_hz,weight")
    for name in ("event-0001-audio.wav", "event-0001-band.wav"):
        info = sf.info(output / name)
        assert info.samplerate == 24000
        assert info.frames > 0
    assert media["groups"]["harmonics-0001"]["image"].startswith("group-")
    assert (output / media["groups"]["harmonics-0001"]["image"]).is_file()
    assert media["groups"]["harmonics-0001"]["plot"]["ridges"] == 1
    assert json.loads((output / "event-media.json").read_text()) == media


def test_media_generation_failure_is_reported_without_stopping_discovery(tmp_path, monkeypatch):
    source = recording(tmp_path)
    output = tmp_path / "discovery"
    output.mkdir()

    def fail(*args, **kwargs):
        raise OSError("no audio device")

    monkeypatch.setattr(discovery, "_write_event_audio", fail)
    media = _write_event_media(source, [event()], output, DiscoverySettings(),
                               plot_event_details=False, event_audio=True)
    entry = media["events"]["event-0001"]
    assert "audio" not in entry
    assert any("audio" in error for error in entry["errors"])


def test_media_index_write_failure_does_not_stop_discovery(tmp_path, caplog):
    source = recording(tmp_path)
    output = tmp_path / "discovery"
    output.mkdir()
    (output / "event-media.json").mkdir()

    media = _write_event_media(source, [event()], output, DiscoverySettings(),
                               plot_event_details=False, event_audio=False)

    assert media["events"]["event-0001"]["ridge_csv"] == "event-0001.csv"
    assert (output / "event-0001.csv").is_file()
    assert "Could not write event-media index" in caplog.text


def test_audio_excerpt_is_bounded_around_long_events():
    start, end, truncated = _event_clip_bounds({"start_s": 10.0, "end_s": 90.0}, 100.0)
    assert end - start == pytest.approx(discovery._EVENT_AUDIO_MAX_S)
    assert truncated is True
    assert 0 <= start < end <= 100.0


def test_audio_excerpt_near_recording_end_stays_in_bounds():
    start, end, truncated = _event_clip_bounds({"start_s": 95.0, "end_s": 99.0}, 100.0)
    assert 0 <= start < end <= 100.0
    assert truncated is False


def test_discover_events_writes_per_curve_media_for_a_moving_tone(tmp_path):
    """Software smoke for the automatic discovery media wiring, not accuracy evidence."""
    from dopplergeist.discovery import discover_events
    from dopplergeist.intake import intake_recording

    sample_rate = 8000
    times = np.arange(sample_rate * 40) / sample_rate
    frequency = 220 - times
    wave = 0.3 * np.sin(2 * np.pi * np.cumsum(frequency) / sample_rate)
    wave += np.random.default_rng(44).normal(0, 0.002, len(times))
    source = tmp_path / "control.wav"
    sf.write(source, wave, sample_rate)
    recording = intake_recording(source, tmp_path / "intake")
    output = tmp_path / "discovery"
    events = discover_events(recording, output_dir=output, plot_event_details=True, event_audio=True)
    assert events
    media = json.loads((output / "event-media.json").read_text())
    assert media["events"]
    entries = [entry for entry in media["events"].values() if "image" in entry and "audio" in entry]
    assert entries
    assert (output / entries[0]["image"]).is_file()
    assert (output / entries[0]["audio"]["raw"]).is_file()


def test_event_plot_uses_the_detector_window_for_high_band_ridges(tmp_path):
    source = recording(tmp_path, duration_s=10.0)
    output = tmp_path / "discovery"
    output.mkdir()
    high_band = event(band_hz=(1600.0, 2000.0))
    high_band["quality"] = {"window_s": 0.5, "hop_s": 0.125}
    media = _write_event_media(source, [high_band], output, DiscoverySettings(),
                               plot_event_details=True, event_audio=False)
    assert media["version"] == 7
    assert media["groups"]["harmonics-0001"]["image"].startswith("group-")
    plot = media["events"]["event-0001"]["plot"]
    assert plot["window_s"] == 0.5
    assert plot["hop_s"] <= 0.05
    assert plot["gap_s"] == 0.5
    assert plot["columns"] >= 100
    assert plot["end_s"] - plot["start_s"] < 30
