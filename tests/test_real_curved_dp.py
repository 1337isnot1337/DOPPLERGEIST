"""Exact recurrence checks on source-derived real spectra, without generated data."""
import math
from pathlib import Path
import struct

import numpy as np
import pytest

from dopplergeist.advanced_discovery import (
    _curved_forward, _curved_forward_reference, best_sequence_curved,
)


FIXTURE = Path(__file__).parent / "fixtures/real-curved-dp-aerosonic.npz"


@pytest.mark.parametrize("band", ["low", "high"])
@pytest.mark.parametrize("nf,nt", [(1, 1), (3, 2), (64, 1), (1, 64), (64, 64)])
@pytest.mark.parametrize("velocity", [2, 6, 32])
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_recorded_spectra_preserve_scores_indices_and_every_backpointer(band, nf, nt, velocity, dtype):
    with np.load(FIXTURE, allow_pickle=False) as recorded:
        image = np.ascontiguousarray(recorded[band][:nf, :nt].T, dtype=dtype)
    original = _curved_forward_reference(image, velocity, 1.5)
    optimized = _curved_forward(image, velocity, 1.5)
    assert struct.pack("d", original[0]) == struct.pack("d", optimized[0])
    assert original[1:4] == optimized[1:4]
    assert original[4].dtype == optimized[4].dtype == np.int8
    np.testing.assert_array_equal(original[4], optimized[4])


@pytest.mark.parametrize("band,bins,hop", [("low", 144, 0.125), ("low", 144, 0.5), ("high", 576, 0.125)])
def test_public_backtracking_returns_the_recorded_reference_path(band, bins, hop):
    with np.load(FIXTURE, allow_pickle=False) as recorded:
        image = recorded[band]
    rate = 0.05 if bins > 144 else 0.3
    vmax = max(2, math.ceil(rate * hop * bins / math.log(2)))
    score, t, j, v, back = _curved_forward_reference(np.ascontiguousarray(image.T), vmax, 1.5)
    expected = []
    while True:
        expected.append((t, j))
        change = int(back[t, j, v])
        if change == 127 or t == 0:
            break
        j -= v - vmax
        v += change
        t -= 1
    actual_score, actual_path = best_sequence_curved(image, hop, bins_per_octave=bins)
    assert actual_score == score
    np.testing.assert_array_equal(actual_path, expected[::-1])
