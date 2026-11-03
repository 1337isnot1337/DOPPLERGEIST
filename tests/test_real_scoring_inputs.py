"""Private scoring snapshots using archived real ridge/flight fit inputs."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from dopplergeist import batch_ridge, matching


def recorded():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture["times"])),
                   np.asarray(fixture["ridge"]), np.asarray(fixture["weight"]), {})
    return fixture["event"], measurement


def arrays(measurement):
    return measurement[0].time, measurement[1], measurement[2]


def test_recorded_snapshot_is_private_and_immutable():
    event, measurement = recorded()
    original = deepcopy((event, measurement))

    @matching._cache_ridge_fits
    def run():
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        copied_event, copied = events[0], measurements[0]
        token = matching._prepared_score_token(copied, copied_event)
        assert token is not None and matching._prepared_score_token(measurement, event) is None
        assert copied_event == event and copied_event is not event
        for new, previous in zip(arrays(copied), arrays(measurement)):
            np.testing.assert_array_equal(new, previous)
            assert new.dtype == previous.dtype and new.strides == previous.strides
            with pytest.raises(ValueError):
                new.setflags(write=True)
        event["f0_range_hz"][0] = 0.0
        measurement[1][0] = -1.0
        assert copied_event == original[0]
        np.testing.assert_array_equal(copied[1], original[1][1])
        assert matching._prepared_score_token(copied, copied_event) is token
        cache = matching._ridge_fit_cache.get()
        assert 0 < cache.score_input_bytes <= cache.score_input_limit

    run()
    assert matching._ridge_fit_cache.get() is None


@pytest.mark.parametrize("changed", ["bounds", "fraction", "scale", "time", "shape", "dtype"])
def test_recorded_snapshot_token_rejects_changed_settings_or_view_metadata(changed):
    event, measurement = recorded()

    @matching._cache_ridge_fits
    def run():
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        copied_event, copied = events[0], measurements[0]
        assert matching._prepared_score_token(copied, copied_event) is not None
        if changed == "bounds":
            copied_event["f0_range_hz"][0] = float(np.nextafter(copied_event["f0_range_hz"][0], np.inf))
        elif changed in ("fraction", "scale"):
            copied_event["quality"]["source_drift_fraction" if changed == "fraction" else "frequency_loss_scale_hz"] = 0.0
        elif changed == "time":
            copied[0].time = copied[0].time.copy()
        elif changed == "shape":
            copied[1].shape = (1, -1)
        else:
            copied[1].dtype = np.int64
        assert matching._prepared_score_token(copied, copied_event) is None

    run()


@pytest.mark.parametrize("kind", ["weight", "bounds", "noncontiguous", "custom", "budget"])
def test_unsupported_recorded_inputs_keep_the_original_path(kind):
    event, measurement = recorded()
    if kind == "weight":
        measurement[2][0] = -1.0
    elif kind == "bounds":
        event["f0_range_hz"][0] = float("nan")
    elif kind == "noncontiguous":
        measurement = (matching.RidgeTimes(measurement[0].time[::2]),
                       measurement[1][::2], measurement[2][::2], {})
    elif kind == "custom":
        class Custom(dict):
            def __deepcopy__(self, memo):
                raise AssertionError("Custom copy hook executed")
            def __sizeof__(self):
                raise AssertionError("Custom size hook executed")
        event = dict(event, ignored_custom_metadata=Custom())

    @matching._cache_ridge_fits
    def run():
        if kind == "budget":
            matching._ridge_fit_cache.get().score_input_limit = 1
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        assert events[0] is event and measurements[0] is measurement
        assert matching._prepared_score_token(measurement, event) is None
        assert not matching._ridge_fit_cache.get().score_inputs

    run()


def test_custom_validation_hooks_and_nested_contexts_do_not_share_tokens(monkeypatch):
    event, measurement = recorded()

    @matching._cache_ridge_fits
    def outer():
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        copied_event, copied = events[0], measurements[0]
        token = matching._prepared_score_token(copied, copied_event)
        assert token is not None

        @matching._cache_ridge_fits
        def inner():
            assert matching._prepared_score_token(copied, copied_event) is None
        inner()
        assert matching._prepared_score_token(copied, copied_event) is token
        with monkeypatch.context() as patch:
            patch.setattr(matching, "_ridge_fit_inputs", lambda *args: None)
            assert matching._prepared_score_token(copied, copied_event) is None
            events, measurements = matching._prepare_score_inputs([event], [measurement])
            assert events[0] is event and measurements[0] is measurement
        with monkeypatch.context() as patch:
            patch.setattr(matching, "_fit_ridge_uncached", lambda *args, **kwargs: None)
            assert matching._prepared_score_token(copied, copied_event) is None
            events, measurements = matching._prepare_score_inputs([event], [measurement])
            assert events[0] is event and measurements[0] is measurement

    outer()


def test_recorded_snapshot_does_not_evaluate_custom_settings_or_nondefault_errors():
    event, measurement = recorded()

    class CustomScale(float):
        def __gt__(self, other):
            raise AssertionError("Custom comparison executed")

        def __float__(self):
            raise AssertionError("Custom conversion executed")

    @matching._cache_ridge_fits
    def run():
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        assert matching._prepared_score_token(measurements[0], events[0]) is not None
        with np.errstate(over="raise"):
            assert matching._prepared_score_token(measurements[0], events[0]) is None
            unchanged_events, unchanged_measurements = matching._prepare_score_inputs([event], [measurement])
            assert unchanged_events[0] is event and unchanged_measurements[0] is measurement
        event["quality"]["frequency_uncertainty_hz"] = CustomScale(1.0)
        unchanged_events, unchanged_measurements = matching._prepare_score_inputs([event], [measurement])
        assert unchanged_events[0] is event and unchanged_measurements[0] is measurement

    run()


def test_direct_scoring_input_import_order():
    subprocess.run([sys.executable, "-c",
                    "import dopplergeist.scoring_inputs; import dopplergeist.matching; "
                    "import dopplergeist.batch_ridge"], check=True)


@pytest.mark.parametrize("changed_index", [0, 1, 2])
def test_bulk_tokens_validate_every_recorded_snapshot(changed_index, monkeypatch):
    observed = [recorded() for _ in range(3)]
    original_events = [pair[0] for pair in observed]
    original_measurements = [pair[1] for pair in observed]

    @matching._cache_ridge_fits
    def run():
        events, measurements = matching._prepare_score_inputs(original_events, original_measurements)
        tokens = matching._prepared_score_tokens(measurements, events)
        assert tokens == tuple(matching._prepared_score_token(measurement, event)
                               for measurement, event in zip(measurements, events))
        assert len(tokens) == 3 and all(token is not None for token in tokens)
        assert matching._prepared_score_tokens(original_measurements, original_events) is None
        assert matching._prepared_score_tokens(measurements[:-1], events) is None
        with np.errstate(under="raise"):
            assert matching._prepared_score_tokens(measurements, events) is None
        with monkeypatch.context() as patch:
            original = matching._source_fit
            patch.setattr(matching, "_source_fit", lambda *args, **kwargs: original(*args, **kwargs))
            assert matching._prepared_score_tokens(measurements, events) is None
        assert matching._prepared_score_tokens(measurements, events) == tokens
        events[changed_index]["f0_range_hz"][0] = float("nan")
        assert matching._prepared_score_tokens(measurements, events) is None
        return measurements, events

    measurements, events = run()
    assert matching._prepared_score_tokens(measurements, events) is None


@pytest.mark.parametrize("layout", ["C", "F", "reversed"])
def test_recorded_prepared_keys_and_every_batch_fit_are_exact(layout):
    event, measurement = recorded()
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    factors, emissions = np.asarray(fixture["factors"]), np.asarray(fixture["emissions"])
    if layout == "F":
        factors, emissions = np.asfortranarray(factors), np.asfortranarray(emissions)
    elif layout == "reversed":
        factors, emissions = factors[::-1], emissions[::-1]
    expected_key = batch_ridge._batch_fit_key(measurement, event, factors, emissions)
    expected = batch_ridge._first_event_fits_uncached(measurement, event, factors, emissions)
    assert expected is not None
    sigma = matching._frequency_scale(event)
    fraction = event["quality"].get("source_drift_fraction", .02)
    expected_scalar = [matching._fit_ridge_uncached(None, None, measurement, 0.,
                       event["f0_range_hz"], 343., sigma, fraction,
                       acoustic_result=(factor, emission))
                       for factor, emission in zip(factors, emissions)]

    @matching._cache_ridge_fits
    def run():
        events, measurements = matching._prepare_score_inputs([event], [measurement])
        copied_event, copied = events[0], measurements[0]
        token = matching._prepared_score_token(copied, copied_event)
        assert token is not None
        assert batch_ridge._batch_fit_key(copied, copied_event, factors, emissions) == expected_key
        assert batch_ridge._first_event_fits_uncached(copied, copied_event, factors, emissions) == expected
        prepared = matching._prepare_ridge_fit_inputs(copied, sigma, fraction)
        assert all(actual is original for actual, original in
                   zip((prepared.times, prepared.ridge, prepared.weight), token.selected))
        assert prepared.normalized_weight is None
        for index, (factor, emission) in enumerate(zip(factors, emissions)):
            assert matching.fit_ridge(None, None, copied, 0., copied_event["f0_range_hz"],
                       343., sigma, fraction, acoustic_result=(factor, emission)) == expected_scalar[index]
        # Invalid model parameters retain their original validation even when
        # the numerical measurement itself is an unchanged private snapshot.
        with pytest.raises(ValueError, match="drift fraction"):
            matching._ridge_fit_inputs(copied, sigma, .2)
        copied_event["quality"]["source_drift_fraction"] = .01
        assert matching._prepared_score_token(copied, copied_event) is None
        assert batch_ridge._batch_fit_key(copied, copied_event, factors, emissions) != expected_key

    run()
