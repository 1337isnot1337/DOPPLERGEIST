import json
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf

from aircraft_geoloc.contracts import validate_recording
from aircraft_geoloc.intake import AudioIntakeError, intake_recording, source_hash


@pytest.mark.skipif(sys.platform != "linux", reason="Linux ru_maxrss is measured in KiB")
def test_chunk_iterator_does_not_retain_recording_sized_rss(tmp_path):
    # A synthetic raw-cache stress fixture, not a captured audio recording.
    cache = tmp_path / "long.f32"
    with cache.open("wb") as stream:
        stream.truncate(128 * 1024**2)
    script = """
import json, resource, sys
from pathlib import Path
from aircraft_geoloc.intake import IntakeRecording
path = Path(sys.argv[1])
duration = path.stat().st_size / 4 / 4000
metadata = dict(source_sha256="0" * 64, duration_s=duration, sample_rate_hz=4000,
                channels=1, source_format="synthetic_raw_cache", time_window=None)
recording = IntakeRecording(path, metadata, {})
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
checksum = 0.0
for start, samples in recording.iter_chunks():
    checksum += float(samples.sum())
print(json.dumps(dict(growth_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss-before,
                      last_end_s=start+len(samples)/4000, checksum=checksum)))
"""
    result = json.loads(subprocess.check_output([sys.executable, "-c", script, str(cache)], text=True))
    assert result["growth_kib"] < 32 * 1024, result
    assert result["last_end_s"] == pytest.approx(cache.stat().st_size / 4 / 4000)
    assert result["checksum"] == 0


def test_stereo_resampling_chunk_times_and_missing_clock(tmp_path):
    sr = 48000
    t = np.arange(sr * 3) / sr
    # Distinct stereo channels verify downmix as well as resampling.
    stereo = np.column_stack((0.4 * np.sin(2 * np.pi * 120 * t), 0.2 * np.sin(2 * np.pi * 240 * t)))
    source = tmp_path / "stereo.wav"
    sf.write(source, stereo, sr, subtype="FLOAT")
    recording = intake_recording(source, tmp_path / "cache")
    assert validate_recording(recording.metadata) == recording.metadata
    assert recording.time_status == "needs_input"
    assert recording.metadata["time_window"] is None
    assert recording.metadata["duration_s"] == 3
    assert recording.metadata["source_sha256"] == source_hash(source)
    decoded = np.fromfile(recording.samples_path, dtype="<f4")
    expected_t = np.arange(12000) / 4000
    expected = 0.2 * np.sin(2 * np.pi * 120 * expected_t) + 0.1 * np.sin(2 * np.pi * 240 * expected_t)
    assert np.sqrt(np.mean((decoded[100:-100] - expected[100:-100]) ** 2)) < 0.001
    chunks = list(recording.iter_chunks(chunk_s=1, overlap_s=0.25))
    assert [start for start, _ in chunks] == [0, 0.75, 1.5, 2.25]
    for start, chunk in chunks:
        first = round(start * 4000)
        np.testing.assert_array_equal(chunk, decoded[first:first + len(chunk)])
    with pytest.raises(FileExistsError):
        intake_recording(source, tmp_path / "cache")


def test_mp3_codec_skip_preserves_audio_zero(tmp_path):
    sr = 44100
    samples = np.zeros(sr * 4)
    for first in (sr // 2, sr * 2, sr * 3):
        samples[first:first + 1000] = np.hanning(1000) * np.sin(2 * np.pi * 600 * np.arange(1000) / sr)
    source = tmp_path / "bursts.wav"
    sf.write(source, samples, sr)
    mp3 = tmp_path / "actual.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-codec:a", "libmp3lame", "-q:a", "2", str(mp3)], check=True)
    window = {"start_utc": "2026-09-08T20:00:00Z", "end_utc": "2026-09-08T20:01:00Z", "source": "user"}
    wav = intake_recording(source, tmp_path / "wav", time_window=window)
    encoded = intake_recording(mp3, tmp_path / "mp3", time_window=window)
    assert encoded.time_status == "ready"
    assert abs(encoded.metadata["duration_s"] - wav.metadata["duration_s"]) <= 1 / 4000
    a = np.fromfile(wav.samples_path, dtype="<f4")
    b = np.fromfile(encoded.samples_path, dtype="<f4")
    for second in (0.5, 2, 3):
        first, last = int((second - 0.1) * 4000), int((second + 0.15) * 4000)
        lag = np.argmax(np.correlate(a[first:last], b[first:last], "full")) - (last - first - 1)
        assert abs(lag / 4000) <= 0.001


def test_creation_tag_is_a_hint_and_short_clip_is_valid(tmp_path):
    source = tmp_path / "short.wav"
    sf.write(source, np.zeros(400), 8000)
    tagged = tmp_path / "tagged.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-metadata", "date=2020-01-01T00:00:00Z", str(tagged)], check=True)
    recording = intake_recording(tagged, tmp_path / "cache")
    assert recording.metadata["duration_s"] == 0.05
    assert recording.time_status == "needs_input"
    hints = recording.diagnostics["time_hints"]
    assert any(hint["value"] == "2020-01-01T00:00:00Z" for hint in hints)
    assert all(not hint["usable_as_recording_clock"] for hint in hints)
    assert json.loads((tmp_path / "cache" / "recording.json").read_text()) == recording.metadata


def test_malformed_missing_empty_and_invalid_clock(tmp_path):
    malformed = tmp_path / "pretend.mp3"
    malformed.write_bytes(b"not a media container")
    with pytest.raises(AudioIntakeError) as error:
        intake_recording(malformed, tmp_path / "bad")
    assert error.value.code == "invalid_media"
    with pytest.raises(AudioIntakeError) as error:
        intake_recording(tmp_path / "missing.wav", tmp_path / "missing")
    assert error.value.code == "unreadable_audio"
    source = tmp_path / "empty.wav"
    sf.write(source, np.empty(0), 4000)
    with pytest.raises(AudioIntakeError) as error:
        intake_recording(source, tmp_path / "empty")
    assert error.value.code in ("empty_audio", "invalid_media")
    with pytest.raises(ValueError, match="timezone"):
        intake_recording(malformed, tmp_path / "naive", time_window={
            "start_utc": "2026-01-01T00:00:00", "end_utc": "2026-01-01T00:01:00", "source": "user"})
