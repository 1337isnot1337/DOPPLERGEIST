"""Native evidence checks on archived fits of real audio and ADS-B observations.

Malformed scalar metadata exercise validation and fallback behavior; these tests
do not generate audio, trajectories, or a field-validation corpus.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dopplergeist import matching, search


def recorded():
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


def outcome(function, *args):
    try:
        return ("result", function(*args))
    except Exception as error:
        return ("error", type(error), str(error))


def assert_python_parity(monkeypatch, result, events, association=False):
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_ridge_module", None)
        expected = outcome(search._ridge_trial_classification, result, events, association)
    actual = outcome(search._ridge_trial_classification, result, events, association)
    assert actual == expected


@pytest.fixture
def native():
    function = getattr(matching._native_ridge_module, "event_fit_reason", None)
    if function is None:
        pytest.skip("optional native evidence validator is not installed")
    return function


def test_native_recorded_event_evidence_and_final_score_parity(native, monkeypatch):
    diagnostics, event = recorded()
    for selected in ([diagnostic] for diagnostic in diagnostics):
        for association in (False, True):
            events = [deepcopy(event) for _ in selected]
            result = result_for(selected, events, association)
            assert native(result["event_diagnostics"], result["event_scores"], result["f0_hz"], events) == 0
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


def test_native_rechecks_every_recorded_diagnostic_field(native, monkeypatch):
    diagnostics, event = recorded()
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


def test_native_recorded_frequency_and_drift_domain_parity(native, monkeypatch):
    diagnostics, event = recorded()
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


def test_native_reason_order_and_in_place_mutation(native, monkeypatch):
    diagnostics, event = recorded()
    fit = deepcopy(diagnostics[0])
    result = result_for([fit], [event])
    arguments = (result["event_diagnostics"], result["event_scores"], result["f0_hz"], [event])
    assert native(*arguments) == 0
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
        assert native(*arguments) == code
        assert_python_parity(monkeypatch, result, [event])
    fit.clear()
    fit.update(diagnostics[0])
    configured = dict(event, f0_range_hz=[1.0, 2.0])
    assert native(*arguments[:-1], [configured]) == 6
    assert_python_parity(monkeypatch, result, [configured])
    # A later event's invalid data cannot replace the earlier failure reason.
    fits = deepcopy(diagnostics[:2])
    fits[0]["support_fraction"] = 0.0
    fits[1]["rmse_hz"] = -1.0
    result = result_for(fits, [event, event])
    assert_python_parity(monkeypatch, result, [event, event])


def test_native_source_drift_tolerance_boundary_keeps_python_arithmetic(native, monkeypatch):
    diagnostics, event = recorded()
    for diagnostic in diagnostics:
        drift, span = diagnostic["source_drift_hz"], diagnostic["source_span_s"]
        tolerance = 1e-12 + 1e-12 * abs(drift)
        for direction in (-1.0, 1.0):
            edge = (drift + direction * tolerance) / span
            for rate in (edge, float(np.nextafter(edge, -np.inf)), float(np.nextafter(edge, np.inf))):
                fit = dict(diagnostic, source_drift_hz_s=rate)
                result = result_for([fit], [event])
                assert_python_parity(monkeypatch, result, [event])


def test_native_custom_types_and_older_extension_keep_python_fallback(native, monkeypatch):
    class CustomDict(dict):
        pass

    class CustomList(list):
        pass

    class CustomString(str):
        pass

    diagnostics, event = recorded()
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
        assert native(*arguments) is None
        altered_result = dict(result, event_diagnostics=arguments[0], event_scores=arguments[1], f0_hz=arguments[2])
        assert_python_parity(monkeypatch, altered_result, arguments[3])
    with monkeypatch.context() as patch:
        patch.setattr(matching, "_native_ridge_module", SimpleNamespace())
        assert_python_parity(monkeypatch, result, standard[3])
