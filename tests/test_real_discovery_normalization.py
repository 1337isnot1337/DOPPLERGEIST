"""Exact normalization checks on unmodified excerpts of a real recording.

The fixture stores decoded PCM bytes and their offsets in the reference upload.
Hook/failure cases are software compatibility checks on those same observations.
"""
import base64
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import signal

from dopplergeist import discovery
from dopplergeist.audio import Spectrum


@pytest.fixture(scope="module")
def real_pcm():
    path = Path(__file__).parent / "fixtures/real_discovery_normalization.json"
    fixture = json.loads(path.read_text())
    assert fixture["sample_format"] == "<f4"
    assert len(fixture["source_sha256"]) == 64
    excerpts = []
    for record in fixture["excerpts"]:
        raw = base64.b64decode(record["pcm_f32le_base64"], validate=True)
        assert len(raw) == record["sample_count"] * 4
        assert 0 <= record["sample_offset"] <= fixture["decoded_sample_count"] - record["sample_count"]
        excerpts.append((record["sample_offset"] / fixture["sample_rate_hz"],
                         np.frombuffer(raw, dtype="<f4").copy()))
    return fixture["sample_rate_hz"], excerpts


def original_spectrum(data, sr, start, settings):
    """Original scalar-axis reductions, retained as the compatibility oracle."""
    n, hop = round(sr * settings.window_s), round(sr * settings.hop_s)
    if len(data) < n:
        return None
    f, t, power = signal.spectrogram(data, fs=sr, window="hann", nperseg=n,
                                    noverlap=n - hop, nfft=n, scaling="density")
    keep = (f >= settings.min_frequency_hz) & (f <= min(settings.max_frequency_hz, sr * 0.48))
    f, power = f[keep], power[keep]
    db = 10 * np.log10(power + np.finfo(np.float32).tiny)
    whitened = db - np.median(db, axis=1, keepdims=True)
    center = np.median(whitened, axis=0, keepdims=True)
    scale = 1.4826 * np.median(np.abs(whitened - center), axis=0, keepdims=True)
    contrast = np.clip((whitened - center) / np.maximum(scale, 1.0), -4, 12)
    return Spectrum(t + start, f, db, contrast)


def assert_exact(expected, actual):
    if expected is None:
        assert actual is None
        return
    assert actual is not None
    for name in ("time", "frequency", "db", "contrast"):
        left, right = getattr(expected, name), getattr(actual, name)
        assert left.dtype == right.dtype, name
        assert left.shape == right.shape, name
        assert left.strides == right.strides, name
        assert left.flags.c_contiguous == right.flags.c_contiguous, name
        assert left.flags.f_contiguous == right.flags.f_contiguous, name
        assert left.flags.writeable == right.flags.writeable, name
        assert left.tobytes(order="C") == right.tobytes(order="C"), name


@pytest.mark.parametrize("excerpt", [0, 1])
@pytest.mark.parametrize("upper", [1600.0, 1599.5])
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_real_spectra_match_original_reductions(real_pcm, excerpt, upper, dtype):
    sr, excerpts = real_pcm
    start, recorded = excerpts[excerpt]
    data = recorded.astype(dtype)
    before = data.tobytes()
    settings = discovery.DiscoverySettings(max_frequency_hz=upper)
    expected = original_spectrum(data, sr, start, settings)
    actual = discovery._spectrum(data, sr, start, settings)
    assert len(actual.time) >= 3
    assert len(actual.frequency) % 2 == (1 if upper == 1600.0 else 0)
    assert_exact(expected, actual)
    assert data.tobytes() == before


@pytest.mark.parametrize("name", ["median", "abs", "maximum", "clip", "isfinite"])
def test_real_custom_normalization_hooks_keep_original_dispatch(real_pcm, monkeypatch, name):
    sr, excerpts = real_pcm
    start, data = excerpts[0]
    settings = discovery.DiscoverySettings()
    original, calls = getattr(np, name), []

    def recorded_function(*args, **kwargs):
        calls.append((getattr(args[0], "shape", None), kwargs.get("axis")))
        return original(*args, **kwargs)

    monkeypatch.setattr(np, name, recorded_function)
    expected = original_spectrum(data, sr, start, settings)
    expected_calls = calls[:]
    calls.clear()
    actual = discovery._spectrum(data, sr, start, settings)
    assert calls == expected_calls
    assert_exact(expected, actual)


def test_real_non_c_layout_keeps_original_layout(real_pcm, monkeypatch):
    sr, excerpts = real_pcm
    start, data = excerpts[0]
    settings = discovery.DiscoverySettings()
    logarithm = np.log10
    monkeypatch.setattr(np, "log10", lambda *args, **kwargs: np.asfortranarray(logarithm(*args, **kwargs)))
    expected = original_spectrum(data, sr, start, settings)
    actual = discovery._spectrum(data, sr, start, settings)
    assert expected.contrast.flags.f_contiguous and not expected.contrast.flags.c_contiguous
    assert_exact(expected, actual)


@pytest.mark.parametrize("failure", [np.nan, np.inf, -np.inf])
def test_real_normalization_nonfinite_failure_keeps_original_path(real_pcm, monkeypatch, failure):
    sr, excerpts = real_pcm
    start, data = excerpts[0]
    settings = discovery.DiscoverySettings()
    logarithm = np.log10

    def failing_logarithm(*args, **kwargs):
        result = logarithm(*args, **kwargs)
        result[0, 0] = failure
        return result

    monkeypatch.setattr(np, "log10", failing_logarithm)
    with np.errstate(invalid="ignore"):
        expected = original_spectrum(data, sr, start, settings)
        actual = discovery._spectrum(data, sr, start, settings)
    assert not np.isfinite(actual.db).all()
    assert_exact(expected, actual)


def test_real_short_prefix_still_has_no_spectrum(real_pcm):
    sr, excerpts = real_pcm
    start, data = excerpts[0]
    settings = discovery.DiscoverySettings()
    prefix = data[:round(sr * settings.window_s) - 1]
    assert original_spectrum(prefix, sr, start, settings) is None
    assert discovery._spectrum(prefix, sr, start, settings) is None
