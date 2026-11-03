"""Serve the copied, terminal CI job with its unmodified original implementation."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
PREPARATION = json.loads((ROOT / "preparation.json").read_text())
JOBS = ROOT / "jobs"


def snapshot():
    return {
        str(p.relative_to(JOBS)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(JOBS.rglob("*"))
        if p.is_file() and p.name != ".manager.lock"
    }


def utc():
    return datetime.now(timezone.utc).isoformat()


before = snapshot()
(ROOT / "jobs-before.json").write_text(json.dumps(before, indent=2) + "\n")
env = dict(os.environ, PYTHONPATH=PREPARATION["source_path"])
command = [sys.executable, "-m", "aircraft_geoloc.cli", "serve", "--jobs", str(JOBS),
           "--port", "8795", "--max-runtime", "3600"]
receipt = {"scope": "Saved terminal result readback only; no upload or scientific run.",
           "source_commit": PREPARATION["source_commit"], "command": command,
           "started_utc": utc(), "files_before": len(before)}
with (ROOT / "server.log").open("w") as log:
    process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    receipt["server_pid"] = process.pid
    try:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError("Original service exited before readiness")
            try:
                with urlopen("http://127.0.0.1:8795/api/capabilities", timeout=.5) as response:
                    receipt["capabilities"] = json.load(response)
                receipt["ready_utc"] = utc()
                (ROOT / "service-start.json").write_text(json.dumps(receipt, indent=2) + "\n")
                print(json.dumps({"ready": True, "pid": process.pid}), flush=True)
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("Original service readiness timed out")
        process.wait()
    except KeyboardInterrupt:
        receipt["stop_requested_utc"] = utc()
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
                receipt["forced_termination"] = True
        receipt["service_exit_code"] = process.returncode
        receipt["stopped_utc"] = utc()
        after = snapshot()
        receipt["files_after"] = len(after)
        receipt["job_file_bytes_unchanged"] = before == after
        receipt["changed_paths"] = sorted(k for k in before.keys() | after.keys()
                                          if before.get(k) != after.get(k))
        (ROOT / "service-lifecycle.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
