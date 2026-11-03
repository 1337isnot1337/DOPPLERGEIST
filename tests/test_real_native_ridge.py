"""Exact native arithmetic checks using captured recorded-ridge/ADS-B inputs.

Prefixes and fitting parameters exercise reduction tails and model branches;
the test does not generate recordings or trajectories.
"""
import json
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import matching


def test_native_ridge_matches_python_on_recorded_samples(monkeypatch):
    native = getattr(matching, "_native_fit_irls", None)
    if native is None:
        pytest.skip("optional native ridge extension is not installed")
    root = Path(__file__).parent
    fixture = json.loads((root / "data/real-ridge-batch-arithmetic.json").read_text())
    times = np.asarray(fixture["times"], dtype=float)
    ridge = np.asarray(fixture["ridge"], dtype=float)
    weight = np.asarray(fixture["weight"], dtype=float)
    factors = np.asarray(fixture["factors"], dtype=float)
    emissions = np.asarray(fixture["emissions"], dtype=float)
    bounds = fixture["event"]["f0_range_hz"]
    checked = 0
    for count in range(10, len(times) + 1):
        measurement = (matching.RidgeTimes(times[:count]), ridge[:count], weight[:count], {})
        for factor, emitted in zip(factors[:, :count], emissions[:, :count]):
            for sigma in (0.5, 1.0, 3.7, 18.001973492902533):
                for fraction in (0.0, 0.02, 0.1):
                    arguments = (None, None, measurement, 0.0, bounds, 343.0, sigma, fraction)
                    with monkeypatch.context() as patch:
                        patch.setattr(matching, "_native_fit_irls", None)
                        expected = matching._fit_ridge_uncached(*arguments,
                            acoustic_result=(factor, emitted))
                    actual = matching._fit_ridge_uncached(*arguments,
                        acoustic_result=(factor, emitted))
                    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), (count, sigma, fraction, actual, expected)
                    checked += 1
    assert checked == (len(times) - 9) * len(factors) * 12


@pytest.mark.parametrize("sigma", [np.float32(0.7), np.float64(0.7), 1])
def test_noncanonical_scalar_parameters_keep_python_arithmetic(monkeypatch, sigma):
    if getattr(matching, "_native_fit_irls", None) is None:
        pytest.skip("optional native ridge extension is not installed")
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture["times"], dtype=float)),
                   np.asarray(fixture["ridge"], dtype=float),
                   np.asarray(fixture["weight"], dtype=float), {})
    acoustic = (np.asarray(fixture["factors"][0], dtype=float),
                np.asarray(fixture["emissions"][0], dtype=float))
    arguments = (None, None, measurement, 0.0, fixture["event"]["f0_range_hz"], 343.0, sigma, 0.02)
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls", None)
        expected = matching._fit_ridge_uncached(*arguments, acoustic_result=acoustic)

    def unexpected_native_call(*args):
        raise AssertionError("Noncanonical scalar parameter reached the native backend")

    monkeypatch.setattr(matching, "_native_fit_irls", unexpected_native_call)
    actual = matching._fit_ridge_uncached(*arguments, acoustic_result=acoustic)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_custom_numpy_error_policy_uses_python_backend(monkeypatch):
    if getattr(matching, "_native_fit_irls", None) is None:
        pytest.skip("optional native ridge extension is not installed")
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture["times"], dtype=float)),
                   np.asarray(fixture["ridge"], dtype=float),
                   np.asarray(fixture["weight"], dtype=float), {})
    acoustic = (np.asarray(fixture["factors"][0], dtype=float),
                np.asarray(fixture["emissions"][0], dtype=float))
    arguments = (None, None, measurement, 0.0, fixture["event"]["f0_range_hz"], 343.0, 1.0, 0.02)
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls", None)
        with np.errstate(all="raise"):
            expected = matching._fit_ridge_uncached(*arguments, acoustic_result=acoustic)

    def unexpected_native_call(*args):
        raise AssertionError("Custom NumPy error policy reached the native backend")

    monkeypatch.setattr(matching, "_native_fit_irls", unexpected_native_call)
    with np.errstate(all="raise"):
        actual = matching._fit_ridge_uncached(*arguments, acoustic_result=acoustic)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
