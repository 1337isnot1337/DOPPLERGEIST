"""Job lifecycle and audio-checkpoint integrity checks, without DSP fixtures."""
import hashlib
import io
import json

import pytest

from dopplergeist.automatic import _load_audio_checkpoint, _save_audio_checkpoint
from dopplergeist.jobs import JobManager, read_json, result, write_json


def checkpoint(manager, job_id):
    directory = manager.directory(job_id)
    request = read_json(directory / "request.json")
    digest = hashlib.sha256((directory / "input.mp3").read_bytes()).hexdigest()
    (directory / "intake").mkdir()
    (directory / "discovery").mkdir()
    (directory / "intake/recording.f32").write_bytes(b"completed cache")
    write_json(directory / "intake/recording.json", {
        "source_sha256": digest, "duration_s": 1.0, "sample_rate_hz": 4000,
        "channels": 1, "source_format": "mp3"})
    write_json(directory / "intake/intake.json", {})
    write_json(directory / "discovery/discovery.json", {"source_sha256": digest, "events": []})
    _save_audio_checkpoint(directory, request, {})
    result(directory, "cancelled", message="Stopped after discovery")
    return directory, request


def test_resume_reuses_completed_discovery_and_persists_result(tmp_path):
    manager = JobManager(tmp_path)
    manager._serial.acquire()
    try:
        job = manager.submit({"schema_version": 1}, io.BytesIO(b"not a media file"), 16)
        job_id = job["job_id"]
        manager.cancel(job_id)
    finally:
        manager._serial.release()
    manager.wait(job_id)
    directory, _ = checkpoint(manager, job_id)
    before = (directory / "discovery/discovery.json").read_bytes()
    try:
        assert manager.resume(job_id)["status"] == "queued"
        final = manager.wait(job_id)
        assert final["status"] == "needs_input"
        assert final["reason_code"] == "recording_time_required"
        assert (directory / "discovery/discovery.json").read_bytes() == before
        assert read_json(directory / "provenance.json")["resumed_from"] == "audio_complete"
    finally:
        manager.close()


def test_checkpoint_rejects_changed_input_or_detection(tmp_path):
    manager = JobManager(tmp_path)
    manager._serial.acquire()
    try:
        job = manager.submit({"schema_version": 1}, io.BytesIO(b"not a media file"), 16)
        manager.cancel(job["job_id"])
    finally:
        manager._serial.release()
    manager.wait(job["job_id"])
    directory, request = checkpoint(manager, job["job_id"])
    try:
        _load_audio_checkpoint(directory, request, {})
        with pytest.raises(ValueError, match="changed"):
            _load_audio_checkpoint(directory, request, {"discovery": {"chunk_s": 180}})
        (directory / "discovery/discovery.json").write_text(json.dumps({"events": []}))
        with pytest.raises(ValueError, match="changed"):
            manager.resume(job["job_id"])
        assert manager.get(job["job_id"])["status"] == "cancelled"
    finally:
        manager.close()
