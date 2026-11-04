"""Optional CLI size-boundary check using an existing real large recording."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_real_large_recording_can_raise_upload_limit(tmp_path):
    value = os.environ.get("DOPPLERGEIST_REAL_LARGE_MP3")
    if not value:
        pytest.skip("set a real recording larger than 100 MiB")
    audio = Path(value)
    assert 100 * 1024 * 1024 < audio.stat().st_size < 200 * 1024 * 1024
    jobs = tmp_path / "jobs"
    base = [sys.executable, "-m", "dopplergeist.cli", "analyze", str(audio), "--jobs", str(jobs)]
    rejected = subprocess.run(base, capture_output=True, text=True, timeout=30)
    assert rejected.returncode == 2
    assert "increase --max-upload-mb" in rejected.stderr
    assert "Traceback" not in rejected.stderr
    assert not jobs.exists()
    # A short, isolated run checks actual ingestion and the size override; it is
    # not an accuracy or completion test, and does not alter the source audio.
    allowed = subprocess.run(base + ["--max-upload-mb", "200", "--max-runtime", "2"],
                             capture_output=True, text=True, timeout=90)
    assert allowed.returncode == 0, allowed.stderr
    result = json.loads(allowed.stdout)
    assert result["status"] in {"failed", "inconclusive", "needs_input", "succeeded"}
    saved = jobs / result["job_id"] / "input.mp3"
    assert saved.stat().st_size == audio.stat().st_size
    assert "Traceback" not in allowed.stderr
