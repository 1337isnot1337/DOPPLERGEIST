"""Actual upload cancellation controls; require an existing real-recording job.

The race control delays only the outgoing cancel request until the real worker
finishes. All audio, worker execution and HTTP responses remain actual inputs.
"""
import importlib.util
import json
import os
from pathlib import Path
import time

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("verify_real_terminal_controls",
    ROOT / "scripts/verify_upload_http.py")
HTTP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HTTP)


@pytest.mark.parametrize("delay_cancel", [False, True], ids=["cancel-running", "completion-wins-race"])
def test_actual_cancellation_must_be_confirmed_even_without_expected_status(tmp_path, monkeypatch, delay_cancel):
    saved = os.environ.get("DOPPLERGEIST_REAL_UPLOAD_JOB")
    if not saved:
        pytest.skip("Set DOPPLERGEIST_REAL_UPLOAD_JOB to a real job with MP3 and recording-start window")
    source = Path(saved)
    request = json.loads((source / "request.json").read_text())
    request.pop("audio_path")
    assert request.get("time_window"), "The actual recording needs its existing recording-start window"
    audio = source / "input.mp3"
    assert HTTP.sha256(audio) == json.loads((source / "input.json").read_text())["sha256"]
    real_request = HTTP.LocalClient.request

    def request_after_real_completion(client, method, path, **kwargs):
        if delay_cancel and method == "POST" and path.endswith("/cancel"):
            while True:
                status, current = real_request(client, "GET", path.rsplit("/", 1)[0])
                assert status == 200
                if current["status"] in HTTP.TERMINAL:
                    break
                time.sleep(min(0.02, HTTP.remaining(client.deadline)))
        return real_request(client, method, path, **kwargs)

    monkeypatch.setattr(HTTP.LocalClient, "request", request_after_real_completion)
    cache = tmp_path / "empty-offline-cache"
    cache.mkdir()
    output = tmp_path / "upload"
    receipt = HTTP.verify_http(audio, output, request=request,
        operator={"offline": True, "cache_root": str(cache)}, expect_status=None,
        cancel_at_stage="discovery", job_max_runtime_s=90, timeout_s=120, poll_interval_s=0.05)
    assert receipt["expected_status"] is None
    assert receipt["cancellation"]["observed_status"] == "running"
    assert receipt["cancellation"]["observed_stage"] == "discovery"
    assert receipt["cancellation"]["http_status"] == 200
    result = json.loads((output / "result.json").read_text())
    assert HTTP.sha256(output / "jobs" / result["job_id"] / "input.mp3") == HTTP.sha256(audio)
    if delay_cancel:
        assert result["status"] == "failed" and result["reason_code"] == "data_unavailable"
        assert receipt["cancellation"]["confirmed"] is False
        assert receipt["verification_passed"] is False
        assert "did not finish cancelled" in receipt["error"]
    else:
        assert result["status"] == "cancelled"
        assert receipt["cancellation"]["confirmed"] is True
        assert receipt["verification_passed"] is True
