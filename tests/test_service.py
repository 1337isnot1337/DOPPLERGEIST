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
        status = request(url + f"/api/jobs/{job_id}")[1]
        assert {key: status[key] for key in job} == job
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


def test_internal_control_lock_is_not_a_downloadable_artifact(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        job_id = "0123456789abcdef0123456789abcdef"
        directory = manager.root / job_id
        directory.mkdir()
        result(directory, "needs_input", reason_code="recording_time_required",
               message="Supply a defensible UTC window.", required_fields=["time_window"])
        (directory / ".control.lock").touch()
        (directory / "discovery.json").write_text("{}")

        items = request(url + f"/api/jobs/{job_id}/artifacts")[1]["artifacts"]
        assert "discovery.json" in [item["path"] for item in items]
        assert ".control.lock" not in [item["path"] for item in items]
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + f"/api/jobs/{job_id}/artifacts/.control.lock")
        assert error.value.code == 404


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

def test_location_artifacts_are_hidden_while_running(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        job = request(url + "/api/jobs", b"payload", {"schema_version": 1})[1]
        directory = manager.directory(job["job_id"])
        (directory / "search").mkdir()
        (directory / "search" / "candidates.json").write_text("{}")
        (directory / "refined-candidates.json").write_text("{}")
        (directory / "public.txt").write_text("available")
        result(directory, "running", stage="search")

        items = request(url + f"/api/jobs/{job['job_id']}/artifacts")[1]["artifacts"]
        paths = [item["path"] for item in items]
        assert "search/candidates.json" not in paths
        assert "refined-candidates.json" not in paths
        assert "public.txt" in paths
        for name in ("search/candidates.json", "refined-candidates.json"):
            with pytest.raises(urllib.error.HTTPError) as error:
                request(url + f"/api/jobs/{job['job_id']}/artifacts/" + name)
            assert error.value.code == 403


def test_restricted_result_artifacts_are_denied(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        job_id = "abcdef0123456789abcdef0123456789"
        directory = manager.root / job_id
        directory.mkdir()
        result(directory, "failed", reason_code="restricted_location", message="Restricted.")
        (directory / "keep.txt").write_text("unavailable")
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + f"/api/jobs/{job_id}/artifacts")
        assert error.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + f"/api/jobs/{job_id}/artifacts/keep.txt")
        assert error.value.code == 403


def job_with_events(manager, job_id="0123456789abcdef0123456789abcdef"):
    directory = manager.root / job_id
    directory.mkdir()
    event = {
        "event_id": "event-0001", "start_s": 0.0, "end_s": 10.0,
        "band_hz": [100.0, 200.0], "harmonic_group_id": "harmonics-0001",
        "ridge": [{"time_s": 0.0, "frequency_hz": 100.0, "weight": 3.0},
                  {"time_s": 5.0, "frequency_hz": 150.0, "weight": 3.5},
                  {"time_s": 10.0, "frequency_hz": 200.0, "weight": 3.0}],
        "quality": {"median_contrast": 3.2},
    }
    before = result(directory, "inconclusive", reason_code="insufficient_evidence",
                    message="Retained proposals are not a supported location.", events=[event])
    (directory / "request.json").write_text(json.dumps({
        "schema_version": 1, "audio_path": str(directory / "input.mp3"),
    }))
    (directory / "input.json").write_text(json.dumps({
        "path": "input.mp3", "bytes": 4, "sha256": "0" * 64,
    }))
    (directory / "input.mp3").write_bytes(b"fake")
    return directory, before


def post_json(url, value):
    request_url = urllib.request.Request(
        url, data=json.dumps(value).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request_url, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_review_labels_are_separate_from_result_and_start_user_assisted_reanalysis(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        directory, before = job_with_events(manager)
        job_id = directory.name
        assert request(url + f"/api/jobs/{job_id}/reviews")[1]["labels"] == {}

        status, reviewed = post_json(url + f"/api/jobs/{job_id}/reviews", {
            "label": "false_positive", "event_ids": ["event-0001"], "note": "steady wind tone"})
        assert status == 200
        assert reviewed["labels"]["event-0001"]["label"] == "false_positive"
        assert reviewed["labels"]["event-0001"]["note"] == "steady wind tone"
        assert request(url + f"/api/jobs/{job_id}/reviews")[1] == reviewed
        assert read_json(directory / "result.json") == before
        artifact_paths = [item["path"] for item in request(url + f"/api/jobs/{job_id}/artifacts")[1]["artifacts"]]
        assert "event-reviews.json" in artifact_paths
        (directory / "discovery").mkdir()
        (directory / "discovery/event-0001-audio.wav").write_bytes(b"RIFF" + b"0" * 40)
        with urllib.request.urlopen(
                url + f"/api/jobs/{job_id}/artifacts/discovery/event-0001-audio.wav") as response:
            assert response.headers.get_content_type().startswith("audio/")
            assert response.headers.get("Content-Disposition") is None

        reanalysis = urllib.request.Request(url + f"/api/jobs/{job_id}/reanalyze", data=b"", method="POST")
        with urllib.request.urlopen(reanalysis, timeout=5) as response:
            assert response.status == 202
            queued = json.loads(response.read())
        assert queued["status"] == "queued"
        assert queued["job_id"] != job_id
        new_directory = manager.directory(queued["job_id"])
        new_request = read_json(new_directory / "request.json")
        assert new_request["excluded_event_ids"] == ["event-0001"]
        assert new_request["review_source_job_id"] == job_id
        assert (new_directory / "input.mp3").read_bytes() == b"fake"
        assert read_json(directory / "result.json") == before


def test_review_api_rejects_unknown_labels_events_and_empty_reanalysis(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        job = request(url + "/api/jobs", b"payload", {"schema_version": 1})[1]
        with pytest.raises(urllib.error.HTTPError) as error:
            post_json(url + f"/api/jobs/{job['job_id']}/reviews",
                      {"label": "false_positive", "event_ids": ["event-0001"]})
        assert error.value.code == 400
        assert request(url + f"/api/jobs/{job['job_id']}/reviews")[1]["labels"] == {}

        directory, _ = job_with_events(manager)
        job_id = directory.name
        for body in (
            {"label": "false_positive", "event_ids": ["event-9999"]},
            {"label": "maybe", "event_ids": ["event-0001"]},
            {"label": "false_positive", "event_ids": []},
            {"label": "false_positive", "event_ids": ["event-0001"], "extra": True},
        ):
            with pytest.raises(urllib.error.HTTPError) as error:
                post_json(url + f"/api/jobs/{job_id}/reviews", body)
            assert error.value.code == 400

        post_json(url + f"/api/jobs/{job_id}/reviews", {"label": "confirmed", "event_ids": ["event-0001"]})
        with pytest.raises(urllib.error.HTTPError) as error:
            request(url + f"/api/jobs/{job_id}/reanalyze", b"")
        assert error.value.code == 400


def test_review_labels_survive_manager_restart(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        directory, _ = job_with_events(manager)
        post_json(url + f"/api/jobs/{directory.name}/reviews",
                  {"label": "false_positive", "event_ids": ["event-0001"]})
    restarted = JobManager(tmp_path)
    try:
        assert read_json(directory / "event-reviews.json")["labels"]["event-0001"]["label"] == "false_positive"
    finally:
        restarted.close()


def test_reanalysis_carries_forward_prior_exclusions(tmp_path, monkeypatch):
    with running_server(tmp_path, monkeypatch) as (manager, url):
        directory, _ = job_with_events(manager)
        request_value = read_json(directory / "request.json")
        request_value["excluded_event_ids"] = ["event-0000"]
        (directory / "request.json").write_text(json.dumps(request_value))
        post_json(url + f"/api/jobs/{directory.name}/reviews",
                  {"label": "false_positive", "event_ids": ["event-0001"]})
        reanalysis = urllib.request.Request(url + f"/api/jobs/{directory.name}/reanalyze",
                                            data=b"", method="POST")
        with urllib.request.urlopen(reanalysis, timeout=5) as response:
            queued = json.loads(response.read())
        new_request = read_json(manager.directory(queued["job_id"]) / "request.json")
        assert new_request["excluded_event_ids"] == ["event-0000", "event-0001"]
