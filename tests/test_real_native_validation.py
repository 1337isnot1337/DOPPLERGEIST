"""Validation parity on saved recorded-ridge fits, including corrupted evidence.

These tests change fit metadata to exercise software guards; they do not create
recordings, trajectories or location-accuracy cases.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
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


def load_recorded():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    return fixture["legacy_diagnostics"], fixture["event"]


def result_for(diagnostics, events, association=False):
    result = {
        "score_kind": "negative_robust_ridge_loss_hz",
        "score": float(sum(fit["score"] for fit in diagnostics)),
        "event_scores": [fit["score"] for fit in diagnostics],
        "f0_hz": [fit["f0_hz"] for fit in diagnostics],
        "event_diagnostics": diagnostics,
    }
    return matching.association_score(result, events) if association else result


def reason_outcome(function, *args):
    try:
        return ("result", function(*args))
    except Exception as error:
        return ("error", type(error), str(error))


def assert_python_parity(monkeypatch, result, events, association=False):
    with monkeypatch.context() as patch:
        patch.setattr(search, "_native_validate_ridge_events", None)
        expected = reason_outcome(search._ridge_trial_classification, result, events, association)
    actual = reason_outcome(search._ridge_trial_classification, result, events, association)
    assert actual == expected


@pytest.fixture
def native_reason():
    function = getattr(matching._native_ridge_module, "event_fit_reason", None)
    if function is None:
        pytest.skip("optional native evidence validator is not installed")
    return function


def test_native_recorded_event_evidence_and_final_score_parity(native_reason, monkeypatch):
    diagnostics, event = load_recorded()
    for selected in ([diagnostic] for diagnostic in diagnostics):
        for association in (False, True):
            events = [deepcopy(event) for _ in selected]
            result = result_for(selected, events, association)
            assert native_reason(result["event_diagnostics"], result["event_scores"], result["f0_hz"], events) == 0
            assert_python_parity(monkeypatch, result, events, association)
    # The outer classifier still performs Python's exact score summation and
    # association arithmetic, including its first failure and optimizer flag.
    events = [deepcopy(event) for _ in diagnostics]
    for association in (False, True):
        result = result_for(diagnostics, events, association)
        assert_python_parity(monkeypatch, result, events, association)
        for field in ("score", "residual_score", "score_kind", "optimizer_success"):
            for value in (None, False, True, -float("inf"), 0.0, "invalid"):
                changed = dict(result, **{field: value})
                assert_python_parity(monkeypatch, changed, events, association)


def test_native_rechecks_every_recorded_diagnostic_field(native_reason, monkeypatch):
    diagnostics, event = load_recorded()
    checked = 0
    for diagnostic in diagnostics:
        original = result_for([diagnostic], [event])
        for field, previous in diagnostic.items():
            values = (None, False, True, float("nan"), float("inf"), -float("inf"),
                      0, 0.0, -1.0, 1e200, np.float32(previous), np.float64(previous),
                      np.longdouble(previous), 2**80)
            for value in values:
                changed = deepcopy(original)
                changed["event_diagnostics"][0][field] = value
                assert_python_parity(monkeypatch, changed, [event])
                checked += 1
            changed = deepcopy(original)
            del changed["event_diagnostics"][0][field]
            assert_python_parity(monkeypatch, changed, [event])
            checked += 1
        for key in ("event_scores", "f0_hz"):
            for value in (np.float64(original[key][0]), 0.0, None, True, float("nan")):
                changed = deepcopy(original)
                changed[key][0] = value
                assert_python_parity(monkeypatch, changed, [event])
                checked += 1
    assert checked > 800


def test_native_recorded_frequency_and_drift_domain_parity(native_reason, monkeypatch):
    diagnostics, event = load_recorded()
    for diagnostic in diagnostics:
        result = result_for([diagnostic], [event])
        for bounds in (None, [], [0.0, 1.0], [-1.0, 1.0], [1.0, 0.0],
                       [1.0, float("inf")], [float("nan"), 1000.0], [1, 1000],
                       np.asarray(event["f0_range_hz"]), tuple(event["f0_range_hz"])):
            configured = dict(event, f0_range_hz=bounds)
            assert_python_parity(monkeypatch, result, [configured])
        for fraction in (None, False, True, -1.0, -0.0, 0.1, 0.2, float("nan"),
                         float("inf"), np.float32(.02), np.float64(.02), np.longdouble(.02)):
            configured = dict(event, quality=dict(event["quality"], source_drift_fraction=fraction))
            assert_python_parity(monkeypatch, result, [configured])
        for quality in (None, {}, []):
            assert_python_parity(monkeypatch, result, [dict(event, quality=quality)])
        without_quality = {key: value for key, value in event.items() if key != "quality"}
        assert_python_parity(monkeypatch, result, [without_quality])


def test_native_reason_order_and_in_place_mutation(native_reason, monkeypatch):
    diagnostics, event = load_recorded()
    fit = deepcopy(diagnostics[0])
    result = result_for([fit], [event])
    arguments = (result["event_diagnostics"], result["event_scores"], result["f0_hz"], [event])
    assert native_reason(*arguments) == 0
    changes = (
        ("support_fraction", 0.0, 1),
        ("rmse_hz", float("nan"), 2),
        ("sample_count", 1, 3),
        ("optimizer_success", False, 4),
        ("score", float(np.nextafter(fit["score"], np.inf)), 5),
        ("source_drift_hz", fit["drift_bound_hz"] + 1.0, 7),
        ("source_drift_hz_s", fit["source_drift_hz_s"] + 1.0, 8),
    )
    for field, value, code in changes:
        fit.clear()
        fit.update(diagnostics[0])
        fit[field] = value
        assert native_reason(*arguments) == code
        assert_python_parity(monkeypatch, result, [event])
    fit.clear()
    fit.update(diagnostics[0])
    configured = dict(event, f0_range_hz=[1.0, 2.0])
    assert native_reason(*arguments[:-1], [configured]) == 6
    assert_python_parity(monkeypatch, result, [configured])
    # A later event's invalid data cannot replace the earlier failure reason.
    fits = deepcopy(diagnostics[:2])
    fits[0]["support_fraction"] = 0.0
    fits[1]["rmse_hz"] = -1.0
    result = result_for(fits, [event, event])
    assert_python_parity(monkeypatch, result, [event, event])


def test_native_source_drift_tolerance_boundary_keeps_python_arithmetic(native_reason, monkeypatch):
    diagnostics, event = load_recorded()
    for diagnostic in diagnostics:
        drift, span = diagnostic["source_drift_hz"], diagnostic["source_span_s"]
        tolerance = 1e-12 + 1e-12 * abs(drift)
        for direction in (-1.0, 1.0):
            edge = (drift + direction * tolerance) / span
            for rate in (edge, float(np.nextafter(edge, -np.inf)), float(np.nextafter(edge, np.inf))):
                fit = dict(diagnostic, source_drift_hz_s=rate)
                result = result_for([fit], [event])
                assert_python_parity(monkeypatch, result, [event])


def test_native_custom_types_and_older_extension_keep_python_fallback(native_reason, monkeypatch):
    class CustomDict(dict):
        pass

    class CustomList(list):
        pass

    class CustomString(str):
        pass

    diagnostics, event = load_recorded()
    result = result_for(diagnostics, [event] * len(diagnostics))
    standard = [diagnostics, result["event_scores"], result["f0_hz"], [event] * len(diagnostics)]
    cases = []
    for index in range(4):
        changed = standard.copy()
        changed[index] = CustomList(changed[index])
        cases.append(changed)
    for altered in (CustomDict(diagnostics[0]),
                    dict(diagnostics[0], score=np.float64(diagnostics[0]["score"])),
                    dict(diagnostics[0], sample_count=2**80)):
        cases.append([[altered] + diagnostics[1:], *standard[1:]])
    keyed = {CustomString(key): value for key, value in diagnostics[0].items()}
    cases.append([[keyed] + diagnostics[1:], *standard[1:]])
    cases.append([*standard[:3], [CustomDict(event)] * len(diagnostics)])
    cases.append([*standard[:3], [dict(event, quality=CustomDict(event["quality"]))] * len(diagnostics)])
    for arguments in cases:
        assert native_reason(*arguments) is None
        altered_result = dict(result, event_diagnostics=arguments[0], event_scores=arguments[1], f0_hz=arguments[2])
        assert_python_parity(monkeypatch, altered_result, arguments[3])
    expected = reason_outcome(search._ridge_trial_classification, result, standard[3])
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_ridge_module", SimpleNamespace())
        patch.setattr(search, "_native_validate_ridge_events", None)
        assert reason_outcome(search._ridge_trial_classification, result, standard[3]) == expected


def test_both_native_interfaces_preserve_container_and_integer_fallbacks(recorded, native, native_reason):
    fits, event = recorded
    result = search._ridge_result([deepcopy(fits[0])])
    arguments = (result["event_diagnostics"], result["event_scores"], result["f0_hz"])
    assert native(*arguments, [event]) is True
    assert native_reason(*arguments, [event]) == 0
    assert native(*arguments, (event,)) is False
    assert native_reason(*arguments, (event,)) == 0
    # The boolean API retains upstream's platform-sized integer gate. Larger
    # Python integers must still reach the original unbounded validator.
    result["event_diagnostics"][0]["sample_count"] = sys.maxsize + 1
    assert native(*arguments, [event]) is False
    assert native_reason(*arguments, [event]) is None


def test_custom_boolean_validator_preserves_nonfinite_aggregate_ceiling(recorded, monkeypatch):
    fits, event = recorded
    fit = dict(fits[0], score=float("nan"))
    arguments = (fit, fit["score"], fit["f0_hz"], event, 3.0)
    monkeypatch.setattr(search, "_native_validate_ridge_events", lambda *args: True)
    expected = outcome(lambda: search._association_event_ceiling_uncached(*arguments))
    assert expected == (("result", 1.0), [])
    assert outcome(lambda: search._association_event_ceiling(*arguments)) == expected


def test_changed_boolean_validator_does_not_reuse_cached_ceiling(recorded, monkeypatch):
    fits, event = recorded
    fit = dict(fits[0], support_fraction=0.0)
    arguments = (fit, fit["score"], fit["f0_hz"], event, 3.0)
    calls = []

    def custom_validator(*args):
        calls.append(args)
        return True

    @matching._cache_ridge_fits
    def exercise():
        cache = matching._ridge_fit_cache.get()
        assert search._association_event_ceiling(*arguments) == 1.0
        assert len(cache.ceiling_entries) == 1
        with monkeypatch.context() as patch:
            patch.setattr(search, "_native_validate_ridge_events", custom_validator)
            expected = search._association_event_ceiling_uncached(*arguments)
            assert expected != 1.0
            calls.clear()
            assert search._association_event_ceiling(*arguments) == expected
            assert len(calls) == 1
            assert len(cache.ceiling_entries) == 1
        assert search._association_event_ceiling(*arguments) == 1.0

    exercise()
