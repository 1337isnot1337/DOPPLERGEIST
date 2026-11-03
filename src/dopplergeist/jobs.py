"""Persistent local jobs; each analysis has its own cancellable process group."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import uuid

from .contracts import validate_request, validate_result

TERMINAL = {"needs_input", "succeeded", "inconclusive", "failed", "cancelled"}


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def result(job_dir, status, **fields):
    value = validate_result(dict(schema_version=1, job_id=Path(job_dir).name, status=status, **fields))
    write_json(Path(job_dir) / "result.json", value)
    return value


def _evidence(value):
    return {key: value[key] for key in ("recording", "events", "candidates", "coverage", "artifacts") if key in value}


class JobManager:
    def __init__(self, root, config=None, *, max_pending=4, max_runtime_s=3600, max_upload_bytes=100*1024*1024):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config = config or {}
        if not isinstance(self.config, dict):
            raise ValueError("Operator configuration must be a JSON object")
        self.max_pending = max_pending
        self.max_runtime_s = max_runtime_s
        self.max_upload_bytes = max_upload_bytes
        if any(not math.isfinite(value) or value <= 0 for value in (max_pending, max_runtime_s, max_upload_bytes)):
            raise ValueError("Job limits must be positive")
        self._lockfile = (self.root / ".manager.lock").open("a")
        try:
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lockfile.close()
            raise ValueError("Another job manager is using this directory") from None
        self._mutex = threading.RLock()
        self._serial = threading.Semaphore(1)
        self._threads = {}
        self._processes = {}
        self._closed = False
        # Preserve terminal outputs. An interrupted process is never silently replayed.
        for path in self.root.glob("*/result.json"):
            old = read_json(path)
            if old["status"] not in TERMINAL:
                result(path.parent, "failed", reason_code="interrupted", message="Service stopped before completion; submit a new job to retry.", **_evidence(old))

    def directory(self, job_id):
        try:
            if uuid.UUID(job_id).hex != job_id:
                raise ValueError
        except (ValueError, AttributeError):
            raise KeyError("Unknown job") from None
        path = self.root / job_id
        if not (path / "result.json").is_file():
            raise KeyError("Unknown job")
        return path

    def get(self, job_id):
        return read_json(self.directory(job_id) / "result.json")

    def submit(self, metadata, source, size, *, suffix=".mp3", _search_seed=None, _config=None, _expected_digest=None):
        """Copy exactly size bytes from a binary stream before launching analysis."""
        if size <= 0 or (_search_seed is None and size > self.max_upload_bytes):
            raise ValueError(f"Audio size must be 1..{self.max_upload_bytes} bytes")
        request = validate_request(dict(metadata, audio_path="pending"))
        with self._mutex:
            if self._closed:
                raise ValueError("Service is shutting down")
            if sum(thread.is_alive() for thread in self._threads.values()) >= self.max_pending:
                raise OverflowError("Job queue is full; try again after a job finishes")
            job_id = uuid.uuid4().hex
            directory = self.root / job_id
            directory.mkdir(mode=0o700)
            suffix = suffix.lower() if suffix.lower() in {".mp3", ".wav", ".flac", ".m4a", ".ogg"} else ".mp3"
            audio = directory / ("input" + suffix)
            digest = hashlib.sha256()
            with audio.open("xb") as target:
                remaining = size
                while remaining:
                    block = source.read(min(1024*1024, remaining))
                    if not block:
                        result(directory, "failed", reason_code="incomplete_upload", message="Upload ended before its declared length.")
                        raise ValueError("Incomplete upload")
                    target.write(block)
                    digest.update(block)
                    remaining -= len(block)
            if _expected_digest is not None and digest.hexdigest() != _expected_digest:
                result(directory, "failed", reason_code="input_changed", message="Original job audio has changed.")
                raise ValueError("Original job audio has changed")
            request["audio_path"] = str(audio)
            write_json(directory / "request.json", request)
            write_json(directory / "operator.json", self.config if _config is None else _config)
            write_json(directory / "input.json", {"sha256": digest.hexdigest(), "bytes": size, "path": audio.name})
            if _search_seed is not None:
                shutil.copytree(_search_seed, directory / "search")
            queued = result(directory, "queued", stage="queued", progress=0)
            thread = threading.Thread(target=self._run, args=(directory,), daemon=True)
            self._threads[job_id] = thread
            thread.start()
            return queued

    def resume(self, job_id):
        """Start a new job from a stopped wall-time-limited search's checkpoints."""
        directory = self.directory(job_id)
        old = self.get(job_id)
        if old["status"] != "inconclusive" or old.get("reason_code") != "work_limit":
            raise ValueError("Only a job stopped by its wall-time limit can be resumed")
        search = directory / "search"
        if (not (search / "manifest.json").is_file() or not (search / "retention.sqlite").is_file()
                or not any(search.glob("tile-*.json"))):
            raise ValueError("No search checkpoints are available for this job")
        original = read_json(directory / "input.json")
        audio = directory / original["path"]
        if audio.parent != directory or not audio.is_file():
            raise ValueError("Original job audio is unavailable")
        if audio.stat().st_size != original["bytes"]:
            raise ValueError("Original job audio has changed")
        request = read_json(directory / "request.json")
        config = read_json(directory / "operator.json")
        with audio.open("rb") as source:
            return self.submit(request, source, original["bytes"], suffix=audio.suffix,
                               _search_seed=search, _config=config, _expected_digest=original["sha256"])

    def _run(self, directory):
        try:
            with self._serial:
                with self._mutex:
                    if self.get(directory.name)["status"] in TERMINAL:
                        return
                    env = dict(os.environ)
                    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
                    with (directory / "worker.log").open("ab") as log:
                        process = subprocess.Popen([sys.executable, "-m", "dopplergeist.jobs", "--execute", str(directory),
                                                    "--parent-pid", str(os.getpid())],
                                                   stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                    self._processes[directory.name] = process
                try:
                    process.wait(timeout=self.max_runtime_s)
                except subprocess.TimeoutExpired:
                    self._stop(process)
                    with self._mutex:
                        if self.get(directory.name)["status"] not in TERMINAL:
                            result(directory, "inconclusive", reason_code="work_limit", message="Analysis exceeded the configured wall-time budget; inspect partial artifacts.", **_evidence(self.get(directory.name)))
                with self._mutex:
                    if self.get(directory.name)["status"] not in TERMINAL:
                        result(directory, "failed", reason_code="worker_exit", message=f"Analysis process exited ({process.returncode}); inspect worker.log.", **_evidence(self.get(directory.name)))
        except Exception as exc:
            with self._mutex:
                if self.get(directory.name)["status"] not in TERMINAL:
                    result(directory, "failed", reason_code="worker_launch", message=f"Could not run analysis: {exc}", **_evidence(self.get(directory.name)))
        finally:
            with self._mutex:
                self._processes.pop(directory.name, None)
                self._threads.pop(directory.name, None)

    @staticmethod
    def _stop(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def cancel(self, job_id):
        with self._mutex:
            directory = self.directory(job_id)
            current = self.get(job_id)
            if current["status"] in TERMINAL:
                return current
            (directory / "cancel").touch()
            process = self._processes.get(job_id)
            if process:
                self._stop(process)
            return result(directory, "cancelled", message="Cancelled by the user; partial artifacts are preserved.", **_evidence(self.get(job_id)))

    def wait(self, job_id):
        thread = self._threads.get(job_id)
        if thread:
            thread.join()
        return self.get(job_id)

    def close(self):
        with self._mutex:
            self._closed = True
            for job_id, thread in list(self._threads.items()):
                if thread.is_alive():
                    self.cancel(job_id)
        for thread in list(self._threads.values()):
            thread.join()
        self._lockfile.close()


def execute(directory, parent_pid=None):
    # On Linux, an abruptly killed server must not leave an orphan analysis or
    # decoder consuming resources and later overwriting an interrupted result.
    if parent_pid is not None and sys.platform == "linux":
        import ctypes
        def terminate_group(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.killpg(os.getpgrp(), signal.SIGTERM)
        signal.signal(signal.SIGTERM, terminate_group)
        ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0)
        if os.getppid() != parent_pid:
            terminate_group(signal.SIGTERM, None)
    from .automatic import analyze
    directory = Path(directory)
    request = read_json(directory / "request.json")
    config = read_json(directory / "operator.json")

    def progress(stage, fraction, **fields):
        if (directory / "cancel").exists():
            raise InterruptedError("Job cancelled")
        return result(directory, "running", stage=stage, progress=fraction, **fields)

    try:
        progress("intake", 0.02)
        final = analyze(request, directory, config, progress)
        if (directory / "cancel").exists():
            result(directory, "cancelled", message="Cancelled by the user.", **_evidence(read_json(directory / "result.json")))
        else:
            result(directory, **final)
    except InterruptedError:
        result(directory, "cancelled", message="Cancelled by the user.", **_evidence(read_json(directory / "result.json")))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        result(directory, "failed", reason_code="processing_error", message=f"{type(exc).__name__}: {exc}", **_evidence(read_json(directory / "result.json")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", required=True)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    execute(args.execute, args.parent_pid)
