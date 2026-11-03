import uuid

import pytest

from dopplergeist.jobs import JobManager, read_json, request_local_cancel, result


def make_running_job(root):
    job_id = uuid.uuid4().hex
    directory = root / job_id
    directory.mkdir()
    result(directory, "running", stage="search", progress=0.5)
    return job_id, directory


def test_local_cancel_sets_marker_without_rewriting_job_result(tmp_path):
    manager = JobManager(tmp_path)
    try:
        job_id, directory = make_running_job(tmp_path)
        previous = read_json(directory / "result.json")
        requested = request_local_cancel(tmp_path, job_id)
        assert requested["cancellation_requested"] is True
        assert requested["status"] == "running"
        assert (directory / "cancel").is_file()
        assert read_json(directory / "result.json") == previous
    finally:
        manager.close()


def test_local_cancel_requires_live_manager_and_preserves_terminal_jobs(tmp_path):
    job_id, directory = make_running_job(tmp_path)
    with pytest.raises(ValueError, match="No active job manager"):
        request_local_cancel(tmp_path, job_id)
    assert not (directory / "cancel").exists()

    previous = result(directory, "inconclusive", reason_code="no_events", message="No events.")
    assert request_local_cancel(tmp_path, job_id) == previous
    assert not (directory / "cancel").exists()
