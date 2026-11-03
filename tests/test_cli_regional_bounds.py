"""Command-line geographic argument checks without generated recordings."""

import subprocess
import sys
from pathlib import Path


def test_analyze_help_includes_bounded_region():
    run = subprocess.run([sys.executable, "-m", "dopplergeist.cli", "analyze", "--help"],
                         capture_output=True, text=True, check=True)
    assert "--bounds WEST SOUTH EAST NORTH" in run.stdout


def test_analyze_rejects_reversed_bounds_before_creating_job(tmp_path):
    # Request validation runs before decoding; an existing file is sufficient.
    jobs = tmp_path / "jobs"
    run = subprocess.run(
        [sys.executable, "-m", "dopplergeist.cli", "analyze", str(Path(__file__)),
         "--bounds", "-98.73", "30.29", "-98.98", "30.47", "--jobs", str(jobs)],
        capture_output=True, text=True,
    )
    assert run.returncode != 0
    assert "Bounds must be increasing" in run.stderr
    assert not jobs.exists()
