from dopplergeist.jobs import JobManager, read_json, result


def test_api_cancel_preserves_terminal_result_written_while_stopping(tmp_path, monkeypatch):
    manager = JobManager(tmp_path)
    try:
        job_id = "a" * 32
        directory = tmp_path / job_id
        directory.mkdir()
        result(directory, "running", stage="search", progress=0.5)
        manager._processes[job_id] = object()

        expected = {
            "schema_version": 1,
            "job_id": job_id,
            "status": "inconclusive",
            "reason_code": "no_events",
            "message": "No events.",
        }

        def worker_commits_before_exit(_process):
            result(directory, "inconclusive", reason_code="no_events", message="No events.")

        monkeypatch.setattr(manager, "_stop", worker_commits_before_exit)

        assert manager.cancel(job_id) == expected
        assert read_json(directory / "result.json") == expected
    finally:
        manager.close()
