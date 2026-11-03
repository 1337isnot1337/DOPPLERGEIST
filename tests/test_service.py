"""Transport/lifecycle checks. Scientific end-to-end checks live separately."""
from contextlib import contextmanager
import io
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request

import pytest

from dopplergeist.jobs import JobManager, read_json, result
from dopplergeist.service import JobServer


@contextmanager
def running_server(tmp_path, monkeypatch):
    # Hold queued analyses to test HTTP and persistence independently of DSP.
    monkeypatch.setattr(JobManager, "_run", lambda self, directory: None)
    manager = JobManager(tmp_path)
    server = JobServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield manager, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        manager.close()
        thread.join()


def request(url, data=None, metadata=None, **headers):
    if metadata is not None:
        headers.update({"Content-Type": "application/octet-stream", "X-Dopplergeist-Request": json.dumps(metadata)})
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        body = response.read()
        return response.status, json.loads(body) if response.headers.get_content_type() == "application/json" else body


def test_upload_readback_cancel_and_original_preservation(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        code, job = request(url + "/api/jobs", b"encoded audio payload", {"schema_version": 1})
        assert code == 202 and job["status"] == "queued"
        job_id = job["job_id"]
        assert request(url + f"/api/jobs/{job_id}")[1] == job
        assert request(url + f"/api/jobs/{job_id}/cancel", b"")[1]["status"] == "cancelled"
        assert request(url + f"/api/jobs/{job_id}/artifacts/input.mp3")[1] == b"encoded audio payload"
        items = request(url + f"/api/jobs/{job_id}/artifacts")[1]["artifacts"]
        assert "input.json" in [p["path"] for p in items]
        assert "operator.json" not in [p["path"] for p in items]
    restarted = JobManager(tmp_path)
    try:
        assert restarted.get(job_id)["status"] == "cancelled"
        assert (restarted.directory(job_id) / "input.mp3").read_bytes() == b"encoded audio payload"
    finally:
        restarted.close()


def test_terminal_result_survives_restart_and_interrupted_job_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(JobManager, "_run", lambda self, directory: None)
    manager = JobManager(tmp_path)
    complete = manager.submit({"schema_version": 1}, io.BytesIO(b"first"), 5)
    result(manager.directory(complete["job_id"]), "inconclusive", reason_code="no_events", message="No events.")
    pending = manager.submit({"schema_version": 1}, io.BytesIO(b"second"), 6)
    manager.close()
    # Simulate abrupt shutdown rather than the normal graceful cancellation.
    result(tmp_path / pending["job_id"], "running", stage="search")
    restarted = JobManager(tmp_path)
    try:
        assert restarted.get(complete["job_id"])["reason_code"] == "no_events"
        assert restarted.get(pending["job_id"])["reason_code"] == "interrupted"
        assert (tmp_path / complete["job_id"] / "input.mp3").read_bytes() == b"first"
    finally:
        restarted.close()


def test_request_validation_upload_limits_and_paths(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        for metadata in ({"schema_version": 1, "events": []}, {"schema_version": 1, "audio_path": "/etc/passwd"},
                         {"schema_version": 1, "discovery": {"chunk_s": 24., "overlap_s": 16.}}):
            with pytest.raises(urllib.error.HTTPError) as error:
                request(url + "/api/jobs", b"x", metadata)
            assert error.value.code == 400
        with pytest.raises(ValueError):
            manager.submit({"schema_version": 1}, io.BytesIO(b"x"), manager.max_upload_bytes + 1)
        job = request(url + "/api/jobs", b"x", {"schema_version": 1})[1]
        for suffix in ("operator.json", "%2e%2e/%2e%2e/.manager.lock", "%2Fetc%2Fpasswd"):
            with pytest.raises(urllib.error.HTTPError) as error:
                request(url + f"/api/jobs/{job['job_id']}/artifacts/" + suffix)
            assert error.value.code == 404
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + "/api/jobs", b"x", {"schema_version": 1}, Origin="https://unrelated.example")
        assert error.value.code == 403
        assert b"DOPPLERGEIST" in request(url + "/")[1]
        assert b"upload-form" in request(url + "/app.js")[1]


def test_lock_and_queued_cancellation(tmp_path):
    manager = JobManager(tmp_path)
    manager._serial.acquire()
    try:
        with pytest.raises(ValueError, match="Another job manager"):
            JobManager(tmp_path)
        queued = manager.submit({"schema_version": 1}, io.BytesIO(b"x"), 1)
        assert manager.cancel(queued["job_id"])["status"] == "cancelled"
    finally:
        manager._serial.release()
        manager.close()


def test_analysis_wall_time_budget_is_terminal_and_persistent(tmp_path):
    # A real subprocess is stopped before importing the scientific stack. This
    # tests resource/lifecycle enforcement, not a simulated search result.
    manager = JobManager(tmp_path, max_runtime_s=0.001)
    try:
        job = manager.submit({"schema_version": 1}, io.BytesIO(b"x"), 1)
        final = manager.wait(job["job_id"])
        assert final["status"] == "inconclusive" and final["reason_code"] == "work_limit"
        assert manager.get(job["job_id"]) == final
        assert not manager._processes
    finally:
        manager.close()


def test_resume_preserves_original_and_checks_input(tmp_path, monkeypatch):
    monkeypatch.setattr(JobManager, "_run", lambda self, directory: None)
    manager = JobManager(tmp_path, {"search_budget": {"tile_cells": 16}})
    try:
        job = manager.submit({"schema_version": 1}, io.BytesIO(b"original"), 8)
        old = manager.directory(job["job_id"])
        result(old, "inconclusive", reason_code="work_limit", message="Time limit.")
        with pytest.raises(ValueError, match="No search checkpoints"):
            manager.resume(job["job_id"])
        (old / "search").mkdir()
        (old / "search" / "manifest.json").write_text('{"run_hash":"saved"}')
        (old / "search" / "retention.sqlite").write_bytes(b"ledger")
        (old / "search" / "tile-1.json").write_text("original checkpoint")
        manager.max_upload_bytes = 4  # A prior upload may have used a larger limit.
        resumed = manager.resume(job["job_id"])
        new = manager.directory(resumed["job_id"])
        assert new != old and manager.get(job["job_id"])["reason_code"] == "work_limit"
        assert (new / "input.mp3").read_bytes() == b"original"
        assert read_json(new / "operator.json") == read_json(old / "operator.json")
        assert read_json(new / "request.json")["audio_path"] == str(new / "input.mp3")
        (new / "search" / "tile-1.json").write_text("new checkpoint")
        assert (old / "search" / "tile-1.json").read_text() == "original checkpoint"
        (old / "input.mp3").write_bytes(b"changed!")
        with pytest.raises(ValueError, match="audio has changed"):
            manager.resume(job["job_id"])
        with pytest.raises(ValueError, match="Only a job stopped"):
            manager.resume(resumed["job_id"])
    finally:
        manager.close()
