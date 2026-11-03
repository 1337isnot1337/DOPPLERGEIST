"""Batched native fitting on frozen, recorded acoustic factors and ridges."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import batch_ridge, matching


@pytest.fixture
def recorded_batch():
    if matching._native_fit_irls_batch is None:
        pytest.skip("optional native batch fitter is not installed")
    source = Path(__file__).parent / "data/real-ridge-batch-arithmetic.json"
    data = json.loads(source.read_text())
    measurement = (matching.RidgeTimes(np.asarray(data["times"], dtype=float)),
                   np.asarray(data["ridge"], dtype=float), np.asarray(data["weight"], dtype=float), {})
    return measurement, deepcopy(data["event"]), np.asarray(data["factors"]), np.asarray(data["emissions"])


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=True)


@pytest.mark.parametrize("order", ["C", "F", "reversed"])
@pytest.mark.parametrize("policy", ["default", "raise"])
def test_recorded_native_batch_is_exact_and_reduces_dispatch(recorded_batch, monkeypatch, order, policy):
    measurement, event, factors, emissions = recorded_batch
    if order == "reversed":
        factors, emissions = factors[::-1], emissions[::-1]
    else:
        factors, emissions = np.array(factors, order=order), np.array(emissions, order=order)
    settings = {} if policy == "default" else {"all": "raise"}
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls_batch", None)
        with np.errstate(**settings):
            expected = batch_ridge._first_event_fits_uncached(measurement, event, factors, emissions)
    before = matching._native_ridge_module.fit_statistics()
    with np.errstate(**settings):
        actual = batch_ridge._first_event_fits_uncached(measurement, event, factors, emissions)
    after = matching._native_ridge_module.fit_statistics()
    assert canonical(actual) == canonical(expected)
    assert after["scalar_calls"] == before["scalar_calls"]
    assert after["batch_calls"] - before["batch_calls"] == int(order == "C")
    assert after["batch_successful_rows"] - before["batch_successful_rows"] == (len(factors) if order == "C" else 0)


@pytest.mark.parametrize("failure", ["false", "type_error"])
def test_recorded_batch_failure_retains_vectorized_fallback(recorded_batch, monkeypatch, failure):
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_fit_irls", None)
        expected = batch_ridge._first_event_fits_uncached(*recorded_batch)

    def unavailable(*args):
        # A partial native output must never enter the final fit diagnostics.
        args[-1][:] = 12345.
        if failure == "type_error":
            raise TypeError("Unsupported native buffers")
        return False

    monkeypatch.setattr(matching, "_native_fit_irls_batch", unavailable)
    actual = batch_ridge._first_event_fits_uncached(*recorded_batch)
    assert canonical(actual) == canonical(expected)


def native_arguments(recorded_batch):
    measurement, event, factors, emissions = recorded_batch
    times, ridge, weight = matching._ridge_fit_inputs(measurement, matching._frequency_scale(event), .02)
    measured = np.isfinite(times) & np.isfinite(ridge) & (weight > 0)
    y, w = ridge[measured], weight[measured]
    independent = len(np.unique(times[measured]))
    w = w * independent / w.sum()
    span = np.maximum(np.ptp(emissions, axis=1), 1e-9)
    reference = (emissions.min(axis=1) + emissions.max(axis=1)) / 2
    u = (emissions - reference[:, None]) / span[:, None]
    low, high = event["f0_range_hz"]
    cap = np.clip(np.median(y[None, :] / factors, axis=1), low, high) * .02
    return [factors, u, y, w, cap, low, high, matching._frequency_scale(event),
            independent, np.empty((len(factors), 5))]


@pytest.mark.parametrize("invalid", ["shape", "dtype", "readonly", "strided"])
def test_native_output_buffers_are_checked(recorded_batch, invalid):
    args = native_arguments(recorded_batch)
    if invalid == "shape":
        args[-1] = args[-1][:, :4].copy()
    elif invalid == "dtype":
        args[-1] = args[-1].astype(np.float32)
    elif invalid == "readonly":
        args[-1].setflags(write=False)
    else:
        args[-1] = args[-1][::-1]
    with pytest.raises((TypeError, ValueError, BufferError)):
        matching._native_fit_irls_batch(*args)


def test_native_batch_reuses_scalar_arithmetic_for_recorded_rows(recorded_batch):
    args = native_arguments(recorded_batch)
    expected = [matching._native_fit_irls(factor, u, args[2], args[3], args[5], args[6],
                                        float(cap), args[7], args[8])
                for factor, u, cap in zip(args[0], args[1], args[4])]
    assert matching._native_fit_irls_batch(*args)
    assert np.array_equal(args[-1], np.asarray(expected))


@pytest.mark.parametrize("source", ["factors", "time", "ridge", "weight", "caps", "reversed_caps"])
def test_native_batch_rejects_overlapping_output_before_writing(recorded_batch, source):
    args = native_arguments(recorded_batch)
    rows = len(args[0])
    if source in {"caps", "reversed_caps"}:
        storage = np.empty((rows, 5))
        caps = storage[:, 0] if source == "caps" else storage[::-1, 0]
        caps[:] = args[4]
        args[4], args[-1] = caps, storage
    else:
        index = {"factors": 0, "time": 1, "ridge": 2, "weight": 3}[source]
        args[-1] = args[index].reshape(-1)[:rows * 5].reshape(rows, 5)
    before = [value.copy() for value in (*args[:5], args[-1])]
    with pytest.raises(ValueError, match="must not overlap"):
        matching._native_fit_irls_batch(*args)
    for actual, saved in zip((*args[:5], args[-1]), before):
        assert np.array_equal(actual, saved, equal_nan=True)


def test_native_batch_accepts_disjoint_strided_recorded_inputs(recorded_batch):
    args = native_arguments(recorded_batch)
    expected = [matching._native_fit_irls(factor, u, args[2], args[3], args[5], args[6],
                                        float(cap), args[7], args[8])
                for factor, u, cap in zip(args[0], args[1], args[4])]
    for index in (2, 3, 4):
        storage = np.empty(len(args[index]) * 2)
        vector = storage[-2::-2]
        vector[:] = args[index]
        args[index] = vector
    assert matching._native_fit_irls_batch(*args)
    assert np.array_equal(args[-1], np.asarray(expected))


def test_native_batch_accepts_adjacent_input_and_output(recorded_batch):
    args = native_arguments(recorded_batch)
    expected = [matching._native_fit_irls(factor, u, args[2], args[3], args[5], args[6],
                                        float(cap), args[7], args[8])
                for factor, u, cap in zip(args[0], args[1], args[4])]
    output_size = len(args[0]) * 5
    storage = np.empty(output_size + len(args[2]))
    storage[output_size:] = args[2]
    args[2] = storage[output_size:]
    args[-1] = storage[:output_size].reshape(len(args[0]), 5)
    assert matching._native_fit_irls_batch(*args)
    assert np.array_equal(args[-1], np.asarray(expected))
