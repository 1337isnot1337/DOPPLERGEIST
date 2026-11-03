"""Validation parity on saved recorded-ridge fits, including corrupted evidence.

These tests change fit metadata to exercise software guards; they do not create
recordings, trajectories or location-accuracy cases.
"""
from copy import deepcopy
import json
from pathlib import Path
import warnings

import numpy as np
import pytest

from dopplergeist import matching, search


@pytest.fixture
def recorded():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    return fixture["legacy_diagnostics"], fixture["event"]


@pytest.fixture
def native():
    function = search._native_validate_ridge_events
    if function is None:
        pytest.skip("optional native ridge extension is not installed")
    return function


def outcome(function):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value = ("result", function())
        except Exception as error:
            value = ("error", type(error), str(error))
    return value, [(type(item.message), str(item.message)) for item in caught]


def compare(monkeypatch, native, result, events, association=False):
    with monkeypatch.context() as patch:
        patch.setattr(search, "_native_validate_ridge_events", None)
        expected = outcome(lambda: search._ridge_trial_classification(result, events, association))
    assert outcome(lambda: search._ridge_trial_classification(result, events, association)) == expected
    return expected[0]


def test_recorded_fits_take_native_path_and_preserve_aggregate_checks(recorded, native, monkeypatch):
    fits, event = recorded
    for fit in fits:
        result = search._ridge_result([fit])
        assert native([fit], result["event_scores"], result["f0_hz"], [event]) is True
        assert compare(monkeypatch, native, result, [event]) == ("result", ("evaluated", None))
        association = matching.association_score(result, [event])
        compare(monkeypatch, native, association, [event], True)
        for key, value in (("score", 1.0), ("residual_score", 0.0),
                           ("score_kind", "unrecognized"), ("optimizer_success", False)):
            changed = dict(association, **{key: value})
            compare(monkeypatch, native, changed, [event], True)


def test_recorded_field_mutations_keep_all_python_failure_reasons(recorded, native, monkeypatch):
    fits, event = recorded
    expected_reasons = {
        "support_fraction": (0.0, "incomplete_acoustic_support"),
        "source_reference_emission_time_s": (np.inf, "nonfinite_fit_evidence"),
        "sample_count": (9, "invalid_fit_evidence"),
        "optimizer_success": (False, "failed_optimizer"),
        "score": (-123.0, "inconsistent_event_fit_evidence"),
        "source_drift_hz": (fits[0]["drift_bound_hz"] + 1.0, "fit_outside_declared_drift_domain"),
        "source_drift_hz_s": (123.0, "inconsistent_source_drift"),
    }
    for field, (value, reason) in expected_reasons.items():
        result = search._ridge_result([deepcopy(fits[0])])
        result["event_diagnostics"][0][field] = value
        assert compare(monkeypatch, native, result, [event]) == ("result", ("unknown", reason))
    result = search._ridge_result([deepcopy(fits[0])])
    changed = dict(event, f0_range_hz=[1.0, 2.0])
    assert compare(monkeypatch, native, result, [changed]) == (
        "result", ("unknown", "fit_outside_declared_frequency_domain"))

    # Invalid or noncanonical replacements must reach the original validator.
    for field in search._CEILING_FLOAT_FIELDS:
        for value in (None, True, 1, np.float32(1), np.float64(1), np.nan, np.inf, -np.inf):
            result = search._ridge_result([deepcopy(fits[0])])
            result["event_diagnostics"][0][field] = value
            assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], [event]) is False
            compare(monkeypatch, native, result, [event])
        result = search._ridge_result([deepcopy(fits[0])])
        del result["event_diagnostics"][0][field]
        compare(monkeypatch, native, result, [event])


def test_native_fallback_preserves_integer_range_and_custom_types(recorded, native, monkeypatch):
    fits, event = recorded

    class Dictionary(dict):
        pass

    class Sequence(list):
        pass

    class Number(float):
        pass

    mutations = []
    for field in ("sample_count", "independent_sample_count"):
        for value in (True, 31.0, np.int64(31), 10**100, -1, None):
            result = search._ridge_result([deepcopy(fits[0])])
            result["event_diagnostics"][0][field] = value
            mutations.append((result, [event]))
    result = search._ridge_result([deepcopy(fits[0])])
    result["event_diagnostics"][0]["sample_count"] = 10**100
    result["event_diagnostics"][0]["independent_sample_count"] = 10**90
    mutations.append((result, [event]))
    for field in search._CEILING_FLOAT_FIELDS:
        result = search._ridge_result([deepcopy(fits[0])])
        result["event_diagnostics"][0][field] = Number(result["event_diagnostics"][0][field])
        mutations.append((result, [event]))
    result = search._ridge_result([Dictionary(fits[0])])
    mutations.append((result, [event]))
    for field in ("event_diagnostics", "event_scores", "f0_hz"):
        result = search._ridge_result([deepcopy(fits[0])])
        result[field] = Sequence(result[field])
        mutations.append((result, [event]))
    for changed in (Dictionary(event), dict(event, quality=Dictionary(event["quality"])),
                    dict(event, f0_range_hz=Sequence(event["f0_range_hz"]))):
        mutations.append((search._ridge_result([deepcopy(fits[0])]), [changed]))
    mutations.append((search._ridge_result([deepcopy(fits[0])]), Sequence([event])))
    for result, events in mutations:
        assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], events) is False
        compare(monkeypatch, native, result, events)


def test_native_fallback_preserves_custom_key_and_getter_calls(recorded, native, monkeypatch):
    fits, event = recorded
    calls = []

    class Dictionary(dict):
        def get(self, *args):
            calls.append(args)
            return super().get(*args)

    result = search._ridge_result([Dictionary(fits[0])])
    assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], [event]) is False
    assert calls == []
    compare(monkeypatch, native, result, [event])
    midpoint = len(calls) // 2
    assert calls[:midpoint] == calls[midpoint:]

    class Key(str):
        pass

    for key in (17, Key("extra")):
        result = search._ridge_result([dict(fits[0], extra=1)])
        result["event_diagnostics"][0][key] = result["event_diagnostics"][0].pop("extra")
        assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], [event]) is False
        compare(monkeypatch, native, result, [event])


def test_default_fraction_and_current_mutable_values_are_rechecked(recorded, native, monkeypatch):
    fits, event = recorded
    result = search._ridge_result([deepcopy(fits[0])])
    for changed in (event, {"f0_range_hz": tuple(event["f0_range_hz"])},
                    dict(event, quality={"source_drift_fraction": 0.02})):
        assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], [changed]) is True
        compare(monkeypatch, native, result, [changed])
    for field in ("score", "support_fraction", "f0_hz"):
        original = result["event_diagnostics"][0][field]
        result["event_diagnostics"][0][field] = np.nextafter(original, np.inf).item()
        compare(monkeypatch, native, result, [event])
        result["event_diagnostics"][0][field] = original
        assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], [event]) is True


def test_native_ceiling_preserves_numpy_policies_and_custom_classifier(recorded, native, monkeypatch):
    fits, event = recorded
    fit = fits[0]
    # Equality with the observed loss gives a zero contribution. nextafter
    # then exercises the original NumPy underflow warning/exception behavior.
    limits = (-fit["score"], np.nextafter(-fit["score"], np.inf).item(), 3.0,
              np.float64(3.0), 3, 0.0, np.inf, np.nan)
    for policy in ("ignore", "warn", "raise"):
        for limit in limits:
            arguments = (fit, fit["score"], fit["f0_hz"], event, limit)
            with np.errstate(under=policy):
                with monkeypatch.context() as patch:
                    patch.setattr(search, "_native_validate_ridge_events", None)
                    expected = outcome(lambda: search._association_event_ceiling(*arguments))
                actual = outcome(lambda: search._association_event_ceiling(*arguments))
            # NaN ceilings compare via their serialized value.
            assert repr(actual) == repr(expected)
    with monkeypatch.context() as patch:
        patch.setattr(search, "_ridge_trial_classification", lambda *args: ("unknown", "custom"))
        assert search._association_event_ceiling(fit, fit["score"], fit["f0_hz"], event, 3.0) == 1.0
    with monkeypatch.context() as patch:
        patch.setattr(search, "_association_event_ceiling_uncached", lambda *args: 0.125)
        assert search._association_event_ceiling(fit, fit["score"], fit["f0_hz"], event, 3.0) == 0.125
