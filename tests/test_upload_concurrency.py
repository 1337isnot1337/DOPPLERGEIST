"""Job transport synchronization; these byte streams are not audio fixtures."""
import io
import threading

import pytest

from dopplergeist.jobs import JobManager


class PausedStream(io.BytesIO):
    def __init__(self):
        super().__init__(b"upload transport bytes")
        self.started = threading.Event()
        self.release = threading.Event()

    def read(self, size=-1):
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("upload test did not release stream")
        return super().read(size)


def test_slow_upload_does_not_block_cancel_and_reserves_queue_slot(tmp_path):
    manager = JobManager(tmp_path, max_pending=2)
    manager._serial.acquire()
    stream = PausedStream()
    upload = None
    try:
        first = manager.submit({"schema_version": 1}, io.BytesIO(b"first"), 5)
        uploaded = []
        upload = threading.Thread(target=lambda: uploaded.append(manager.submit(
            {"schema_version": 1}, stream, len(stream.getvalue()))))
        upload.start()
        assert stream.started.wait(5)
        cancelled = threading.Event()
        cancel = threading.Thread(target=lambda: (manager.cancel(first["job_id"]), cancelled.set()))
        cancel.start()
        assert cancelled.wait(1), "cancellation blocked behind upload"
        cancel.join()
        with pytest.raises(OverflowError):
            manager.submit({"schema_version": 1}, io.BytesIO(b"third"), 5)
        stream.release.set()
        upload.join(5)
        assert not upload.is_alive() and uploaded[0]["status"] == "queued"
        assert manager.get(first["job_id"])["status"] == "cancelled"
    finally:
        stream.release.set()
        if upload:
            upload.join(5)
        manager._serial.release()
        manager.close()


def test_shutdown_waits_for_upload_and_does_not_launch_it(tmp_path):
    manager = JobManager(tmp_path)
    stream = PausedStream()
    errors = []

    def submit():
        try:
            manager.submit({"schema_version": 1}, stream, len(stream.getvalue()))
        except ValueError as exc:
            errors.append(str(exc))

    upload = threading.Thread(target=submit)
    upload.start()
    assert stream.started.wait(5)
    close = threading.Thread(target=manager.close)
    close.start()
    try:
        with manager._uploads_changed:
            assert manager._uploads_changed.wait_for(lambda: manager._closed, timeout=5)
        assert close.is_alive()
    finally:
        stream.release.set()
        upload.join(5)
        close.join(5)
    assert not upload.is_alive() and not close.is_alive()
    assert errors == ["Service is shutting down"]
    assert not manager._threads


def test_second_upload_can_queue_while_first_is_paused(tmp_path):
    manager = JobManager(tmp_path, max_pending=2)
    manager._serial.acquire()
    stream = PausedStream()
    slow = threading.Thread(target=lambda: manager.submit(
        {"schema_version": 1}, stream, len(stream.getvalue())))
    fast_done = threading.Event()
    fast = threading.Thread(target=lambda: (manager.submit(
        {"schema_version": 1}, io.BytesIO(b"next"), 4), fast_done.set()))
    try:
        slow.start()
        assert stream.started.wait(5)
        fast.start()
        assert fast_done.wait(1), "second upload blocked behind first"
    finally:
        stream.release.set()
        slow.join(5)
        if fast.ident is not None:
            fast.join(5)
        manager._serial.release()
        manager.close()


def test_incomplete_upload_releases_queue_slot(tmp_path):
    manager = JobManager(tmp_path, max_pending=1)
    manager._serial.acquire()
    try:
        with pytest.raises(ValueError, match="Incomplete upload"):
            manager.submit({"schema_version": 1}, io.BytesIO(b"short"), 6)
        job = manager.submit({"schema_version": 1}, io.BytesIO(b"next"), 4)
        assert job["status"] == "queued"
    finally:
        manager._serial.release()
        manager.close()
