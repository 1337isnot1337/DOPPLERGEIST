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


def _recorded_native_batch():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture["times"], dtype=float)),
                   np.asarray(fixture["ridge"], dtype=float),
                   np.asarray(fixture["weight"], dtype=float), {})
    return (measurement, fixture["event"], np.asarray(fixture["factors"], dtype=float),
            np.asarray(fixture["emissions"], dtype=float))


@pytest.mark.parametrize("order", ["C", "F", "reversed"])
@pytest.mark.parametrize("error_policy", ["default", "raise"])
def test_native_batch_matches_recorded_vectorized_fits(monkeypatch, order, error_policy):
    from dopplergeist.batch_ridge import _first_event_fits_uncached

    native = getattr(matching, "_native_fit_irls", None)
    if native is None:
        pytest.skip("optional native ridge extension is not installed")
    measurement, event, factors, emissions = _recorded_native_batch()
    if order == "reversed":
        factors, emissions = factors[::-1], emissions[::-1]
    else:
        factors, emissions = np.array(factors, order=order), np.array(emissions, order=order)
    policy = {} if error_policy == "default" else {"all": "raise"}
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls", None)
        with np.errstate(**policy):
            expected = _first_event_fits_uncached(measurement, event, factors, emissions)
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return native(*args)

    monkeypatch.setattr(matching, "_native_fit_irls", counted)
    with np.errstate(**policy):
        actual = _first_event_fits_uncached(measurement, event, factors, emissions)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert calls == (len(factors) if order == "C" else 0)


@pytest.mark.parametrize("failure", ["none", "type_error"])
@pytest.mark.parametrize("failure_row", [0, 2])
def test_native_batch_failure_keeps_vectorized_fallback(monkeypatch, failure, failure_row):
    from dopplergeist.batch_ridge import _first_event_fits_uncached

    if getattr(matching, "_native_fit_irls", None) is None:
        pytest.skip("optional native ridge extension is not installed")
    native = matching._native_fit_irls
    inputs = _recorded_native_batch()
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls", None)
        expected = _first_event_fits_uncached(*inputs)
    calls = 0

    def unavailable(*args):
        nonlocal calls
        calls += 1
        if calls <= failure_row:
            return native(*args)
        if failure == "type_error":
            raise TypeError("Native buffer is unavailable")
        return None

    monkeypatch.setattr(matching, "_native_fit_irls", unavailable)
    actual = _first_event_fits_uncached(*inputs)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert calls == failure_row + 1


@pytest.mark.parametrize("field", ["sigma", "fraction", "lower", "upper"])
@pytest.mark.parametrize("scalar_type", [int, np.float32, np.float64])
def test_noncanonical_batch_parameters_keep_vectorized_arithmetic(monkeypatch, field, scalar_type):
    from dopplergeist.batch_ridge import _first_event_fits_uncached

    if getattr(matching, "_native_fit_irls", None) is None:
        pytest.skip("optional native ridge extension is not installed")
    measurement, event, factors, emissions = _recorded_native_batch()
    if field == "sigma":
        event["quality"]["frequency_loss_scale_hz"] = scalar_type(1)
    elif field == "fraction":
        event["quality"]["source_drift_fraction"] = scalar_type(0.02)
    else:
        index = 0 if field == "lower" else 1
        event["f0_range_hz"][index] = scalar_type(event["f0_range_hz"][index])
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls", None)
        expected = _first_event_fits_uncached(measurement, event, factors, emissions)

    def unexpected_native_call(*args):
        raise AssertionError("Noncanonical batch parameter reached the native backend")

    monkeypatch.setattr(matching, "_native_fit_irls", unexpected_native_call)
    actual = _first_event_fits_uncached(measurement, event, factors, emissions)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize("unsupported", ["short", "empty", "nonfinite_factor", "nonfinite_emission"])
def test_unsupported_recorded_batches_keep_none_fallback(monkeypatch, unsupported):
    from dopplergeist.batch_ridge import _first_event_fits_uncached

    measurement, event, factors, emissions = _recorded_native_batch()
    if unsupported == "short":
        measurement = (matching.RidgeTimes(measurement[0].time[:9]),
                       measurement[1][:9], measurement[2][:9], {})
        factors, emissions = factors[:, :9], emissions[:, :9]
    elif unsupported == "empty":
        factors, emissions = factors[:0], emissions[:0]
    elif unsupported == "nonfinite_factor":
        factors[0, 0] = np.nan
    else:
        emissions[0, 0] = np.nan

    def unexpected_native_call(*args):
        raise AssertionError("Unsupported batch reached the native backend")

    monkeypatch.setattr(matching, "_native_fit_irls", unexpected_native_call)
    with np.errstate(all="raise"):
        assert _first_event_fits_uncached(measurement, event, factors, emissions) is None
