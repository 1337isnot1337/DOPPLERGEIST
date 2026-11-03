"""Encoded audio through the real job process, intake and automatic discovery."""
import hashlib
import json
import threading
import urllib.request
import subprocess

import numpy as np
import pytest
import soundfile as sf

from aircraft_geoloc.jobs import JobManager
from aircraft_geoloc.service import JobServer


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
    server = JobServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = {"schema_version": 1}
        if time_window:
            request["time_window"] = time_window
        upload = urllib.request.Request(base + "/api/jobs", payload,
                    headers={"Content-Type": "application/octet-stream", "X-Dopplergeist-Request": json.dumps(request)})
        with urllib.request.urlopen(upload, timeout=10) as response:
            assert response.status == 202
            queued = json.load(response)
        final = manager.wait(queued["job_id"])
        directory = manager.directory(queued["job_id"])
        with urllib.request.urlopen(base + f"/api/jobs/{queued['job_id']}") as response:
            assert json.load(response) == final
        with urllib.request.urlopen(base + f"/api/jobs/{queued['job_id']}/artifacts/input.mp3") as response:
            assert response.read() == payload
        return final, directory
    finally:
        server.shutdown()
        server.server_close()
        manager.close()
        thread.join()


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
    assert list((directory / "discovery").glob("event-*.png"))
    assert final["coverage"]["data_status"] == "unavailable"


def test_corrupt_upload_returns_predictable_decode_failure(tmp_path):
    pytest.importorskip("aircraft_geoloc.intake")
    pytest.importorskip("aircraft_geoloc.discovery")
    final, directory = submit_and_wait(tmp_path, b"not encoded audio", time_window=WINDOW)
    assert final["status"] == "failed" and final["reason_code"] == "invalid_media", final
    assert (directory / "input.mp3").read_bytes() == b"not encoded audio"


def test_subset_association_preserves_original_event_identity(tmp_path):
    """A middle subset must never be relabelled as the first input events."""
    pytest.importorskip("aircraft_geoloc.confidence")
    from aircraft_geoloc.automatic import _decide
    from aircraft_geoloc.jobs import read_json
    events = [{"event_id": f"event-{i}", "start_s": i*10., "end_s": i*10.+5, "band_hz": [100., 120.],
               "ridge": [{"time_s": i*10.+t, "frequency_hz": 115.-t} for t in (1., 2., 3.)]} for i in range(3)]
    search = {"status": "complete", "scoring_time_is_locked": True, "ranked": [
        {"event_indices": [1, 2], "flight_ids": ["second-flight", "third-flight"], "lat": 40., "lon": -100.,
         "score": -1., "recording_start_time_s": 1788897600., "event_diagnostics": [{"rmse_hz": .1}, {"rmse_hz": .2}]}]}
    state = {"recording": {"time_window": WINDOW}, "coverage": {"search_complete": True, "data_status": "available", "limitations": []}}
    def finish(status, reason_code=None, message=None, **fields):
        return dict(status=status, reason_code=reason_code, message=message, **fields)
    final = _decide(search, events, events, [None]*3, [], None, state, tmp_path,
                    {"refine_finalists": 0}, finish, lambda: None)
    assert final["status"] == "inconclusive" and final["reason_code"] == "unexplained_events"
    assert final["candidates"][0]["event_ids"] == ["event-1", "event-2"]
    diagnostics = read_json(tmp_path / "refined-candidates.json")["matching_diagnostics"]
    assert "event-0" not in diagnostics
    assert diagnostics["event-1"]["rmse_hz"] == .1
    assert diagnostics["event-2"]["rmse_hz"] == .2


def test_complete_tile_work_is_separate_from_partial_flight_coverage():
    from aircraft_geoloc.automatic import _coverage
    coverage = _coverage({"search": {"coverage": "conus"}},
        {"status": "partial", "tiles_total": 819, "tiles_completed": 819,
         "tile_failures": [], "refinement_failure": None, "data_scope_complete": False}, {})
    assert coverage["search_complete"] is True
    assert coverage["data_status"] == "partial"
    assert "historical_flight_scope_or_audible_border_region" in coverage["missing_data"]


def test_acquisition_budget_counts_utc_archive_days_across_midnight(tmp_path):
    from types import SimpleNamespace
    from aircraft_geoloc.automatic import MissingData, _search
    window = {"start_utc": "2026-09-08T23:59:00Z", "end_utc": "2026-09-08T23:59:00Z", "source": "user"}
    event = {"event_id": "event-1", "start_s": 0., "end_s": 10., "band_hz": [100., 120.],
             "ridge": [{"time_s": float(t), "frequency_hz": 115.-t} for t in range(10)]}
    recording = SimpleNamespace(metadata={"time_window": window, "duration_s": 61.})
    request = {"schema_version": 1, "audio_path": "unused", "time_window": window, "search": {"coverage": "conus"}}
    with pytest.raises(MissingData, match="acquisition budget"):
        _search(request, recording, [event], tmp_path, {"cache_root": str(tmp_path), "max_acquisition_days": 1}, lambda: None)
    assert not (tmp_path/"flights").exists()
