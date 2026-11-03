"""Encoded audio through the real job process, intake and automatic discovery."""
import hashlib
import io
import subprocess

import numpy as np
import pytest
import soundfile as sf

from aircraft_geoloc.jobs import JobManager


def encoded_mp3(tmp_path, *, moving=False):
    pytest.importorskip("aircraft_geoloc.intake")
    pytest.importorskip("aircraft_geoloc.discovery")
    sr = 8000
    t = np.arange(sr * 40) / sr
    frequency = 220 - t if moving else np.full_like(t, 200)
    # Deterministic acoustic control, not aircraft/location truth.
    wave = .3*np.sin(2*np.pi*np.cumsum(frequency)/sr) + np.random.default_rng(44).normal(0, .002, len(t))
    source = tmp_path / "control.wav"
    sf.write(source, wave, sr)
    target = tmp_path / "control.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-codec:a", "libmp3lame", str(target)], check=True)
    return target.read_bytes()


def submit_and_wait(tmp_path, payload, *, time_window=None):
    manager = JobManager(tmp_path / "jobs")
    try:
        request = {"schema_version": 1}
        if time_window:
            request["time_window"] = time_window
        queued = manager.submit(request, io.BytesIO(payload), len(payload))
        final = manager.wait(queued["job_id"])
        directory = manager.directory(queued["job_id"])
        return final, directory
    finally:
        manager.close()


WINDOW = {"start_utc": "2026-09-08T20:00:00Z", "end_utc": "2026-09-08T20:01:00Z", "source": "user"}


def test_real_mp3_without_time_requests_clock_and_preserves_hash(tmp_path):
    payload = encoded_mp3(tmp_path)
    final, directory = submit_and_wait(tmp_path, payload)
    assert final["status"] == "needs_input", final
    assert final["reason_code"] == "recording_time_required"
    assert final["required_fields"] == ["time_window"]
    assert final["recording"]["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (directory / "input.mp3").read_bytes() == payload
    assert (directory / final["artifacts"]["provenance"]).is_file()


def test_stationary_mp3_returns_no_events_without_search(tmp_path):
    payload = encoded_mp3(tmp_path)
    final, directory = submit_and_wait(tmp_path, payload, time_window=WINDOW)
    assert final["status"] == "inconclusive" and final["reason_code"] == "no_supported_events", final
    assert not final["events"]
    assert not (directory / "search").exists()


def test_moving_tone_mp3_discovers_events_then_reports_missing_data(tmp_path):
    pytest.importorskip("aircraft_geoloc.data_access")
    pytest.importorskip("aircraft_geoloc.matching")
    pytest.importorskip("aircraft_geoloc.tiled_search")
    payload = encoded_mp3(tmp_path, moving=True)
    final, directory = submit_and_wait(tmp_path, payload, time_window=WINDOW)
    assert final["status"] == "inconclusive" and final["reason_code"] == "data_unavailable", final
    assert len(final["events"]) >= 1
    assert list((directory / "discovery").glob("event-*-spectrogram.png"))
    assert final["coverage"]["data_status"] == "unavailable"


def test_corrupt_upload_returns_predictable_decode_failure(tmp_path):
    pytest.importorskip("aircraft_geoloc.intake")
    pytest.importorskip("aircraft_geoloc.discovery")
    final, directory = submit_and_wait(tmp_path, b"not encoded audio", time_window=WINDOW)
    assert final["status"] == "failed" and final["reason_code"] == "invalid_media", final
    assert (directory / "input.mp3").read_bytes() == b"not encoded audio"
