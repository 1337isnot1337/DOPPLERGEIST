import numpy as np
import soundfile as sf

from aircraft_geoloc.contracts import validate_event
from aircraft_geoloc.discovery import discover_events
from aircraft_geoloc.intake import intake_recording


def _audio(tmp_path, events, duration=180):
    sr = 4000
    t = np.arange(sr * duration) / sr
    data = np.random.default_rng(9133).normal(0, 0.08, len(t))
    data += 0.12 * np.sin(2 * np.pi * 400 * t)
    for center, f0, harmonics in events:
        relative = t - center
        frequency = f0 * (1 - 0.18 * relative / np.sqrt(relative ** 2 + 8 ** 2))
        phase = 2 * np.pi * np.cumsum(frequency) / sr
        amplitude = 0.16 * np.exp(-(relative / 24) ** 2) * (np.abs(relative) < 44)
        for harmonic in harmonics:
            data += amplitude / harmonic * np.sin(harmonic * phase)
    path = tmp_path / "recording.wav"
    sf.write(path, data, sr, subtype="FLOAT")
    return intake_recording(path, tmp_path / "intake")


def test_blind_whole_file_seams_harmonics_and_separate_events(tmp_path):
    recording = _audio(tmp_path, [(65, 120, [1, 2, 3]), (135, 250, [1, 2])])
    events = discover_events(recording, output_dir=tmp_path / "discovery")
    assert len(events) == 2, [(e["start_s"], e["end_s"], e["band_hz"]) for e in events]
    for center, event in zip((65, 135), events):
        assert event["start_s"] < center < event["end_s"]
        assert event["quality"]["harmonic_count"] >= 2
        assert validate_event(event) == event
        assert np.all(np.diff([point["time_s"] for point in event["ridge"]]) > 0)
    assert (tmp_path / "discovery" / "discovery.png").is_file()


def test_noise_stationary_tones_and_upward_chirp_are_rejected(tmp_path):
    sr = 4000
    t = np.arange(sr * 120) / sr
    data = np.random.default_rng(791).normal(0, 0.1, len(t))
    data += 0.3 * np.sin(2 * np.pi * 180 * t)
    data += 0.1 * signal_chirp(t)
    path = tmp_path / "negative.wav"
    sf.write(path, data, sr)
    recording = intake_recording(path, tmp_path / "intake")
    assert discover_events(recording) == []


def signal_chirp(t):
    return np.sin(2 * np.pi * (500 * t + 0.25 * t ** 2))


def test_overlapping_nonharmonic_events_are_retained(tmp_path):
    recording = _audio(tmp_path, [(60, 120, [1, 2]), (76, 210, [1])], duration=140)
    events = discover_events(recording)
    assert len(events) == 2, [(e["start_s"], e["end_s"], e["band_hz"]) for e in events]
    assert events[0]["end_s"] > events[1]["start_s"]


def test_short_input_has_no_forced_event(tmp_path):
    recording = _audio(tmp_path, [], duration=1)
    assert discover_events(recording) == []


def test_missing_fundamental_harmonics_are_one_event(tmp_path):
    recording = _audio(tmp_path, [(65, 120, [2, 3])], duration=140)
    events = discover_events(recording)
    assert len(events) == 1
    assert events[0]["quality"]["harmonic_count"] == 2


def test_switching_stationary_tones_do_not_make_a_flyover(tmp_path):
    sr = 4000
    t = np.arange(sr * 120) / sr
    data = np.random.default_rng(811).normal(0, 0.04, len(t))
    data += 0.2 * (1 / (1 + np.exp((t - 60) / 2))) * np.sin(2 * np.pi * 74 * t)
    data += 0.2 * (1 / (1 + np.exp(-(t - 60) / 2))) * np.sin(2 * np.pi * 65 * t)
    path = tmp_path / "switching.wav"
    sf.write(path, data, sr)
    assert discover_events(intake_recording(path, tmp_path / "intake")) == []
