"""Negative controls for the external timing acceptance measurement."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


spec = importlib.util.spec_from_file_location(
    "methodology_verifier", Path(__file__).parents[1] / "scripts/verify_methodology.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize("shift", [-70, 0, 83])
def test_timing_pilots_recover_inserted_delay(shift):
    rate = 4000
    reference = np.random.default_rng(441).normal(0, 0.1, rate * 10)
    decoded = np.roll(reference, shift)
    measured = verifier.timing_offsets(reference, decoded, rate, [2, 5, 8])
    assert all(abs(row["offset_s"] - shift / rate) < 1 / rate for row in measured)


def test_unrelated_or_silent_audio_cannot_pass_timing():
    reference = np.random.default_rng(441).normal(0, 0.1, 40000)
    unrelated = np.random.default_rng(442).normal(0, 0.1, 40000)
    with pytest.raises(ValueError, match="absent, distorted"):
        verifier.timing_offsets(reference, unrelated, 4000, [2, 5, 8])
    with pytest.raises(ValueError, match="no usable signal"):
        verifier.timing_offsets(np.zeros(40000), unrelated, 4000, [2, 5, 8])


def test_truncated_decode_cannot_pass_timing():
    reference = np.random.default_rng(441).normal(0, 0.1, 40000)
    with pytest.raises(ValueError, match="every complete timing pilot"):
        verifier.timing_offsets(reference, reference[:20000], 4000, [2, 5, 8])


def test_expected_missing_clock_does_not_accept_a_failed_job():
    root = Path(__file__).parents[1]
    result = json.loads((root / "docs/examples/job-needs-input.json").read_text())
    verifier.inspect_result(result, "a" * 64, "needs_input", "recording_time_required")
    result.update(status="failed", reason_code="decode_failed")
    with pytest.raises(ValueError, match="Expected needs_input"):
        verifier.inspect_result(result, "a" * 64, "needs_input")


def test_a_different_recording_cannot_pass_upload_acceptance():
    root = Path(__file__).parents[1]
    result = json.loads((root / "docs/examples/job-needs-input.json").read_text())
    result["recording"] = {"source_sha256": "b" * 64, "duration_s": 45,
                           "sample_rate_hz": 4000, "channels": 1, "source_format": "mp3"}
    with pytest.raises(ValueError, match="hash differs"):
        verifier.inspect_result(result, "a" * 64, "needs_input")


def test_supported_location_requires_completed_declared_coverage():
    root = Path(__file__).parents[1]
    result = json.loads((root / "docs/examples/job-result.json").read_text())
    result["recording"] = {"source_sha256": "a" * 64, "duration_s": 100,
                           "sample_rate_hz": 4000, "channels": 1, "source_format": "mp3"}
    result["coverage"] = {"search_complete": False, "data_status": "partial", "limitations": []}
    with pytest.raises(ValueError, match="complete declared coverage"):
        verifier.inspect_result(result, "a" * 64, "succeeded")
