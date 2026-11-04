"""CLI input failures that must stop before creating or running an audio job."""

import os
from pathlib import Path
import socket
import subprocess
import sys


REPOSITORY = Path(__file__).resolve().parents[1]


def _run_cli(*arguments):
    environment = os.environ.copy()
    source_path = str(REPOSITORY / "src")
    environment["PYTHONPATH"] = source_path + os.pathsep + environment.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "dopplergeist.cli", *map(str, arguments)],
                          cwd=REPOSITORY, env=environment, capture_output=True, text=True)


def test_analyze_rejects_time_source_without_start_utc(tmp_path):
    # The existing test source is only a path here; parser validation runs before audio intake.
    recording = Path(__file__)
    jobs = tmp_path / "jobs"
    run = _run_cli("analyze", recording, "--time-source", "recording metadata", "--jobs", jobs)

    assert run.returncode == 2
    assert "--time-source requires --start-utc" in run.stderr
    assert not jobs.exists()


def test_analyze_reports_job_store_initialization_error_without_traceback():
    existing_file = Path(__file__)
    run = _run_cli("analyze", existing_file, "--jobs", existing_file)

    assert run.returncode == 2
    assert "Could not open job store" in run.stderr
    assert "Traceback" not in run.stderr


def test_serve_reports_job_store_initialization_error_without_traceback():
    existing_file = Path(__file__)
    run = _run_cli("serve", "--jobs", existing_file, "--port", "0")

    assert run.returncode == 2
    assert "Could not start local service" in run.stderr
    assert "Traceback" not in run.stderr


def test_serve_reports_occupied_port_without_traceback(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        run = _run_cli("serve", "--jobs", tmp_path / "jobs", "--port", str(port))

    assert run.returncode == 2
    assert "Could not start local service" in run.stderr
    assert "Traceback" not in run.stderr
