import uuid
import subprocess
import sys
import threading
import time

import pytest

from dopplergeist import jobs
from dopplergeist.jobs import JobManager, read_json, request_local_cancel, result


def make_running_job(root):
    job_id = uuid.uuid4().hex
    directory = root / job_id
    directory.mkdir()
    result(directory, "running", stage="search", progress=0.5)
    return job_id, directory


def use_idle_worker(monkeypatch):
    popen = subprocess.Popen
    def start_idle_worker(command, **kwargs):
        return popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
    monkeypatch.setattr(subprocess, "Popen", start_idle_worker)


def use_controlled_worker(monkeypatch, release):
    popen = subprocess.Popen
    def start_controlled_worker(command, **kwargs):
        child = popen([sys.executable, "-c",
                       "import pathlib,sys,time\nwhile not pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)",
                       str(release)], **kwargs)
        wait = child.wait
        # Observe the child's exit rather than the manager's polling timeout.
        child.wait = lambda timeout=None: wait(timeout=8 if timeout is not None else None)
        return child
    monkeypatch.setattr(subprocess, "Popen", start_controlled_worker)


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


def test_startup_recovery_honors_existing_cancellation(tmp_path):
    job_id, directory = make_running_job(tmp_path)
    (directory / "cancel").touch()
    manager = JobManager(tmp_path)
    try:
        assert manager.get(job_id)["status"] == "cancelled"
    finally:
        manager.close()


def test_startup_recovery_keeps_interrupted_and_terminal_behavior(tmp_path):
    job_id, directory = make_running_job(tmp_path)
    finished_id, finished_directory = make_running_job(tmp_path)
    previous = result(finished_directory, "inconclusive", reason_code="no_events", message="No events.")
    manager = JobManager(tmp_path)
    try:
        interrupted = manager.get(job_id)
        assert interrupted["status"] == "failed" and interrupted["reason_code"] == "interrupted"
        assert manager.get(finished_id) == previous
        assert not (finished_directory / ".control.lock").exists()
    finally:
        manager.close()


def test_cancel_request_during_startup_recovery_is_consistent(tmp_path, monkeypatch):
    job_id, directory = make_running_job(tmp_path)
    recovery_read = threading.Event()
    allow_recovery = threading.Event()
    original_read = jobs.read_json
    managers, responses, errors = [], [], []

    def pause_recovery(path):
        value = original_read(path)
        if threading.current_thread().name == "recovery-test" and path == directory / "result.json":
            recovery_read.set()
            assert allow_recovery.wait(8)
        return value

    monkeypatch.setattr(jobs, "read_json", pause_recovery)

    def recover():
        try:
            managers.append(JobManager(tmp_path))
        except Exception as error:
            errors.append(error)

    recovery = threading.Thread(target=recover, name="recovery-test")
    recovery.start()
    cancel = None
    try:
        assert recovery_read.wait(5)
        cancel = threading.Thread(target=lambda: responses.append(request_local_cancel(tmp_path, job_id)))
        cancel.start()
        cancel.join(timeout=0.5)
        allow_recovery.set()
        recovery.join(timeout=8)
        cancel.join(timeout=8)
        assert not recovery.is_alive() and not cancel.is_alive() and not errors
        final = original_read(directory / "result.json")
        if responses[0].get("cancellation_requested"):
            assert final["status"] == "cancelled"
        else:
            assert responses[0] == final
            assert final["status"] == "failed" and final["reason_code"] == "interrupted"
    finally:
        allow_recovery.set()
        recovery.join(timeout=8)
        if cancel is not None:
            cancel.join(timeout=8)
        for manager in managers:
            manager.close()

def test_local_cancel_stops_unresponsive_worker_and_preserves_checkpoint(tmp_path, monkeypatch):
    # Exercise the control plane with a real process that never reports progress;
    # no recording or aircraft observations are generated.
    manager = JobManager(tmp_path, max_runtime_s=60)
    job_id, directory = make_running_job(tmp_path)
    checkpoint = directory / "saved-checkpoint"
    checkpoint.write_text("retained")
    use_idle_worker(monkeypatch)
    thread = threading.Thread(target=manager._run, args=(directory,))
    manager._threads[job_id] = thread
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while job_id not in manager._processes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job_id in manager._processes
        request_local_cancel(tmp_path, job_id)
        thread.join(timeout=3)
        assert not thread.is_alive(), "manager did not stop the worker after cancellation"
        assert read_json(directory / "result.json")["status"] == "cancelled"
        assert checkpoint.read_text() == "retained"
    finally:
        manager.close()
        thread.join(timeout=5)


def test_time_limit_still_reports_inconclusive(tmp_path, monkeypatch):
    manager = JobManager(tmp_path, max_runtime_s=0.2)
    job_id, directory = make_running_job(tmp_path)
    use_idle_worker(monkeypatch)
    try:
        manager._run(directory)
        outcome = read_json(directory / "result.json")
        assert outcome["status"] == "inconclusive"
        assert outcome["reason_code"] == "work_limit"
        assert not (directory / "cancel").exists()
    finally:
        manager.close()


@pytest.mark.parametrize("worker_finished", [False, True])
def test_cancel_racing_worker_exit_preserves_terminal_result(tmp_path, monkeypatch, worker_finished):
    manager = JobManager(tmp_path, max_runtime_s=60)
    job_id, directory = make_running_job(tmp_path)
    release = directory / "release"
    use_controlled_worker(monkeypatch, release)
    thread = threading.Thread(target=manager._run, args=(directory,))
    manager._threads[job_id] = thread
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while job_id not in manager._processes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job_id in manager._processes
        request_local_cancel(tmp_path, job_id)
        if worker_finished:
            expected = result(directory, "inconclusive", reason_code="no_events", message="No events.")
        release.touch()
        thread.join(timeout=8)
        assert not thread.is_alive()
        outcome = read_json(directory / "result.json")
        if worker_finished:
            assert outcome == expected
        else:
            assert outcome["status"] == "cancelled"
    finally:
        release.touch(exist_ok=True)
        manager.close()
        thread.join(timeout=8)


def test_cancel_request_and_exit_do_not_leave_failed_result(tmp_path, monkeypatch):
    manager = JobManager(tmp_path, max_runtime_s=60)
    job_id, directory = make_running_job(tmp_path)
    release = directory / "release"
    use_controlled_worker(monkeypatch, release)
    entering_touch, allow_touch = threading.Event(), threading.Event()
    original_touch = type(release).touch

    def delayed_touch(path, *args, **kwargs):
        if path == directory / "cancel":
            entering_touch.set()
            assert allow_touch.wait(8)
        return original_touch(path, *args, **kwargs)

    monkeypatch.setattr(type(release), "touch", delayed_touch)
    thread = threading.Thread(target=manager._run, args=(directory,))
    manager._threads[job_id] = thread
    thread.start()
    requested = []
    request_thread = None
    try:
        deadline = time.monotonic() + 5
        while job_id not in manager._processes and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job_id in manager._processes
        request_thread = threading.Thread(target=lambda: requested.append(request_local_cancel(tmp_path, job_id)))
        request_thread.start()
        assert entering_touch.wait(5)
        release.touch()
        thread.join(timeout=1)
        allow_touch.set()
        request_thread.join(timeout=8)
        thread.join(timeout=8)
        assert requested[0]["cancellation_requested"]
        assert read_json(directory / "result.json")["status"] == "cancelled"
    finally:
        allow_touch.set()
        release.touch(exist_ok=True)
        if request_thread is not None:
            request_thread.join(timeout=8)
        manager.close()
        thread.join(timeout=8)


def test_cancel_while_worker_launch_fails_is_cancelled(tmp_path, monkeypatch):
    manager = JobManager(tmp_path, max_runtime_s=60)
    job_id, directory = make_running_job(tmp_path)
    launching, allow_failure = threading.Event(), threading.Event()

    def fail_launch(*args, **kwargs):
        launching.set()
        assert allow_failure.wait(8)
        raise OSError("simulated process launch failure")

    monkeypatch.setattr(subprocess, "Popen", fail_launch)
    thread = threading.Thread(target=manager._run, args=(directory,))
    manager._threads[job_id] = thread
    thread.start()
    try:
        assert launching.wait(5)
        assert request_local_cancel(tmp_path, job_id)["cancellation_requested"]
        allow_failure.set()
        thread.join(timeout=8)
        assert not thread.is_alive()
        assert read_json(directory / "result.json")["status"] == "cancelled"
    finally:
        allow_failure.set()
        manager.close()
        thread.join(timeout=8)
