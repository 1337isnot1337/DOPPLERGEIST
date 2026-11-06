"""Optional CPU/CUDA parity check on an existing recorded-audio spectrogram."""
import os

import numpy as np
import pytest
from scipy.ndimage import median_filter

from dopplergeist.advanced_discovery import local_median


def test_recorded_spectrogram_median_parity(monkeypatch):
    path = os.environ.get("DOPPLERGEIST_REAL_SPECTROGRAM")
    if not path:
        pytest.skip("Set DOPPLERGEIST_REAL_SPECTROGRAM to a recorded-audio spectrogram")
    pytest.importorskip("cupy")
    image = np.load(path, allow_pickle=False)
    expected = median_filter(image, size=(31, 1), mode="nearest")
    monkeypatch.setenv("DOPPLERGEIST_MEDIAN_BACKEND", "cpu")
    np.testing.assert_array_equal(local_median(image), expected)
    monkeypatch.setenv("DOPPLERGEIST_MEDIAN_BACKEND", "cuda")
    np.testing.assert_array_equal(local_median(image), expected)
