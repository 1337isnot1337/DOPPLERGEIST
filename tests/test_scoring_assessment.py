"""Conservative finite-envelope classification of actual shared-clock fits."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from aircraft_geoloc import matching, search
from aircraft_geoloc.finite_search import classified_assessment


SPEC = importlib.util.spec_from_file_location("scoring_test_support", Path(__file__).with_name("test_matching.py"))
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)


def case():
    centers = (30, 130)
    return dict(
        candidate={"passes": [{"flight_id": identity, "receive_time": center}
                              for identity, center in zip(("a", "b"), centers)], "event_indices": [0, 1]},
        point=SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=0, x=0, y=0),
        tracks={identity: SUPPORT.Flyover(center) for identity, center in zip(("a", "b"), centers)},
        events=[{"event_id": f"event-{i}", "cpa_receive_s": center, "f0_range_hz": [119, 121]}
                for i, center in enumerate(centers)],
        measurements=[SUPPORT.measurement(center) for center in centers],
        mode="robust_ridge", time_origin=0, time_sweep_s=1, time_step_s=1)


def assert_counts(row, scheduled, evaluated, rejected, unknown, complete):
    assessment = row["scoring_assessment"]
    expected = {"scheduled_trials": scheduled, "evaluated_trials": evaluated,
                "rejected_trials": rejected, "unknown_trials": unknown}
    assert {key: assessment[key] for key in expected} == expected
    assert all(type(assessment[key]) is int for key in expected)
    assert assessment["scheduled_trials"] == assessment["evaluated_trials"] + assessment["unknown_trials"]
    assert 0 <= assessment["rejected_trials"] <= assessment["evaluated_trials"]
    assert assessment["complete"] is complete
    assert classified_assessment(row) is complete


def test_complete_actual_shared_clock_trials_keep_winner_and_count_every_trial(monkeypatch):
    inputs, recorded = case(), []
    original = matching.score_ridges
    def score(*args, **kwargs):
        result = original(*args, **kwargs)
        recorded.append((float(args[4]), matching.association_score(deepcopy(result), args[1])))
        return result
    monkeypatch.setattr(matching, "score_ridges", score)
    row = search.score_candidate(**inputs)
    assert [clock for clock, _ in recorded] == [-1, 0, 1]
    clock, expected = max(recorded, key=lambda trial: trial[1]["score"])
    assert row["recording_start_time_s"] == clock == 0
    for key in ("score", "event_scores", "event_diagnostics", "f0_hz", "score_kind"):
        assert row[key] == expected[key]
    assert row["flight_ids"] == ["a", "b"]
    assert row["event_indices"] == [0, 1]
    assert_counts(row, 3, 3, 0, 0, True)


@pytest.mark.parametrize("unknown_first", (False, True))
def test_a_finite_winner_does_not_hide_an_unknown_clock_trial(unknown_first):
    inputs = case()
    class Limited(SUPPORT.Flyover):
        def acoustic(self, t, observer, c):
            factor, emission, distance = super().acoustic(t, observer, c)
            supported = np.asarray(t) >= 105 if unknown_first else np.asarray(t) <= 154.5
            return np.where(supported, factor, np.nan), emission, distance
    inputs["tracks"]["b"] = Limited(130)
    row = search.score_candidate(**inputs)
    assert np.isfinite(row["score"]) and row["recording_start_time_s"] == 0
    assert_counts(row, 3, 2, 0, 1, False)
    assert row["scoring_assessment"]["unknown_reasons"] == {"incomplete_acoustic_support": 1}


def test_supported_residual_threshold_rejection_is_evaluated_not_unknown():
    inputs = case()
    inputs["tracks"] = {"a": SUPPORT.Flyover(60), "b": SUPPORT.Flyover(160)}
    row = search.score_candidate(**inputs)
    assert row["score"] == -np.inf
    assert_counts(row, 3, 3, 3, 0, True)
    assert row["scoring_assessment"]["unknown_reasons"] == {}


def test_declared_zero_drift_model_is_still_a_complete_finite_evaluation():
    inputs = case()
    for event in inputs["events"]:
        event["quality"] = {"source_drift_fraction": 0.0}
    row = search.score_candidate(**inputs)
    assert all(fit["drift_bound_hz"] == fit["source_drift_hz"] == 0 for fit in row["event_diagnostics"])
    assert_counts(row, 3, 3, 0, 0, True)


def test_mixed_finite_and_rejected_trials_can_be_complete_without_changing_scores():
    inputs = case()
    inputs.update(time_sweep_s=10, time_step_s=5)
    row = search.score_candidate(**inputs)
    assessment = row["scoring_assessment"]
    assert np.isfinite(row["score"]) and row["recording_start_time_s"] == 0
    assert 0 < assessment["rejected_trials"] < 5
    assert_counts(row, 5, 5, assessment["rejected_trials"], 0, True)


@pytest.mark.parametrize("defect", ("few_points", "zero_weights", "missing_emission", "zero_factor"))
def test_missing_or_degenerate_model_support_is_never_an_evaluated_rejection(defect):
    inputs = case()
    if defect == "few_points":
        measurement = inputs["measurements"][1]
        inputs["measurements"][1] = (matching.RidgeTimes(measurement[0].time[:9]),
                                      measurement[1][:9], measurement[2][:9], {})
    elif defect == "zero_weights":
        measurement = inputs["measurements"][1]
        inputs["measurements"][1] = (measurement[0], measurement[1], np.zeros_like(measurement[2]), {})
    else:
        class Missing(SUPPORT.Flyover):
            def acoustic(self, t, observer, c):
                factor, emission, distance = super().acoustic(t, observer, c)
                if defect == "missing_emission":
                    emission[:] = np.nan
                else:
                    factor[:] = 0
                return factor, emission, distance
        inputs["tracks"]["b"] = Missing(130)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        row = search.score_candidate(**inputs)
    assert_counts(row, 3, 0, 0, 3, False)
    assert not np.isfinite(row["score"])


@pytest.mark.parametrize("key,value", (("sample_count", True), ("sample_count", -1),
    ("independent_sample_count", False), ("independent_sample_count", 0), ("source_span_s", 0), ("support_fraction", True),
    ("f0_hz", np.nan), ("source_drift_hz", np.inf), ("rmse_hz", np.nan), ("optimizer_success", False)))
def test_finite_winner_with_invalid_fit_metadata_remains_unclassified(monkeypatch, key, value):
    original = matching.score_ridges
    def corrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        result["event_diagnostics"][1][key] = value
        return result
    monkeypatch.setattr(matching, "score_ridges", corrupted)
    row = search.score_candidate(**case())
    assert np.isfinite(row["score"])
    assert_counts(row, 3, 0, 0, 3, False)


@pytest.mark.parametrize("defect", ("frequency", "excess_drift", "zero_cap", "forged_cap", "slope"))
def test_finite_fits_outside_or_inconsistent_with_declared_domain_remain_unknown(monkeypatch, defect):
    original = matching.score_ridges
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        fit = result["event_diagnostics"][1]
        if defect == "frequency":
            fit["f0_hz"] = result["f0_hz"][1] = 999.0
        elif defect == "excess_drift":
            fit["source_drift_hz"] = 10000.0
            fit["source_drift_hz_s"] = fit["source_drift_hz"] / fit["source_span_s"]
        elif defect == "zero_cap":
            fit.update(drift_bound_hz=0.0, source_drift_hz=1.0)
            fit["source_drift_hz_s"] = 1.0 / fit["source_span_s"]
        elif defect == "forged_cap":
            fit["drift_bound_hz"] = 10000.0
        else:
            fit["source_drift_hz_s"] += 1.0
        return result
    monkeypatch.setattr(matching, "score_ridges", changed)
    row = search.score_candidate(**case())
    assert np.isfinite(row["score"])
    assert_counts(row, 3, 0, 0, 3, False)


def test_empty_clock_domain_has_no_invented_acoustic_rejections():
    inputs = case()
    inputs["candidate"]["recording_start_bounds_s"] = [10, 20]
    inputs["time_sweep_s"] = 0
    row = search.score_candidate(**inputs)
    assert row["score"] == -np.inf
    assert row["scoring_assessment"]["empty_clock_domain"] is True
    assert_counts(row, 0, 0, 0, 0, False)


@pytest.mark.parametrize("mode", ("ridge", "brightness"))
def test_legacy_finite_scores_do_not_gain_an_implicit_core_certificate(monkeypatch, mode):
    inputs = case()
    del inputs["candidate"]["event_indices"]
    inputs["mode"] = mode
    monkeypatch.setattr(search, "event_score", lambda *args, **kwargs: (1.0, 120.0))
    row = search.score_candidate(**inputs)
    assert np.isfinite(row["score"])
    assert_counts(row, 3, 0, 0, 3, False)
    assert row["scoring_assessment"]["unknown_reasons"] == {"uncertified_legacy_scoring": 3}


@pytest.mark.parametrize("name", ("evaluated_trials", "rejected_trials", "unknown_trials"))
@pytest.mark.parametrize("value", (True, -1))
def test_actual_scorer_certificate_does_not_bypass_producer_counter_validation(name, value):
    row = search.score_candidate(**case())
    assert classified_assessment(row)
    row["scoring_assessment"][name] = value
    assert not classified_assessment(row)
