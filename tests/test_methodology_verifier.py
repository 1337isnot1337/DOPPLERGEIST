"""Negative controls for the external timing acceptance measurement."""
import importlib.util
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
