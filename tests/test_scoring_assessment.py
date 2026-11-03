"""Independent protocol checks for classified bounded clock trials."""
from types import SimpleNamespace

import numpy as np
import pytest

from dopplergeist import geometry
from dopplergeist.matching import RidgeTimes
from dopplergeist.search import score_candidate


class Model:
    def __init__(self, last_supported=np.inf, error=None):
        self.last_supported, self.error = last_supported, error

    def acoustic(self, times, observer, c):
        if self.error is not None:
            raise self.error
        times = np.asarray(times)
        factor = np.where(times <= self.last_supported, 1.0, np.nan)
        return factor, times - 5, np.full_like(times, 1700.0)


def score(model, *, ridge_hz=120.0, association=False, bounds=None):
    times = np.arange(0, 20, 0.5)
    measurement = (RidgeTimes(times), np.full_like(times, ridge_hz), np.ones_like(times), {})
    point = SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=0, x=0, y=0)
    candidate = {"passes": [{"flight_id": "test-flight", "receive_time": 10}]}
    if association:
        candidate["event_indices"] = [0]
    if bounds is not None:
        candidate["recording_start_bounds_s"] = bounds
    event = {"event_id": "event", "cpa_receive_s": 10, "f0_range_hz": [119, 121]}
    return score_candidate(candidate, point, {"test-flight": model}, [event], [measurement],
                           mode="robust_ridge", time_origin=0, time_sweep_s=1, time_step_s=1)


def test_all_declared_clock_trials_are_evaluated():
    result = score(Model())
    assert result["score"] == pytest.approx(0)
    assert result["scoring_assessment"] == {"complete": True, "evaluated_trials": 3,
        "rejected_trials": 0, "unknown_trials": 0, "reasons": []}


def test_finite_best_does_not_hide_unknown_clock_trial():
    result = score(Model(last_supported=20))
    assert np.isfinite(result["score"])
    assessment = result["scoring_assessment"]
    assert not assessment["complete"]
    assert (assessment["evaluated_trials"], assessment["rejected_trials"], assessment["unknown_trials"]) == (2, 0, 1)
    assert assessment["reasons"] == ["incomplete_ridge_or_trajectory_support"]


def test_completed_acoustic_rejection_is_classified_without_a_finite_best():
    result = score(Model(), ridge_hz=200, association=True)
    assert result["score"] == -np.inf
    assert result["scoring_assessment"] == {"complete": True, "evaluated_trials": 0,
        "rejected_trials": 3, "unknown_trials": 0, "reasons": ["acoustic_loss_exceeds_limit"]}


def test_typed_emission_failure_stays_unknown_instead_of_losing_candidate_accounting():
    error = geometry.AcousticSupportError("test-flight", "non_monotone_arrival")
    result = score(Model(error=error))
    assert result["score"] == -np.inf
    assert result["scoring_assessment"] == {"complete": False, "evaluated_trials": 0,
        "rejected_trials": 0, "unknown_trials": 3,
        "reasons": ["test-flight: non_monotone_arrival"]}


def test_actual_non_monotone_model_exposes_typed_track_identity():
    track = geometry.Track("broken-observations", [0, 1, 2], [0, 0, 0], [0, 0, 0], [9000, 8000, 7000])
    with pytest.raises(geometry.AcousticSupportError) as failure:
        track.acoustic(np.array([1.0]), geometry.ecef(0, 0, 0))
    assert failure.value.track_id == "broken-observations"
    assert failure.value.reason == "non_monotone_arrival"
    assert isinstance(failure.value, ValueError)


def test_unrelated_value_error_is_not_relabelled_as_trajectory_support():
    with pytest.raises(ValueError, match="configuration defect"):
        score(Model(error=ValueError("configuration defect")))


def test_empty_clock_domain_is_not_a_vacuous_completed_assessment():
    result = score(Model(), bounds=[5, 6])
    assert result["score"] == -np.inf
    assert result["scoring_assessment"] == {"complete": False, "evaluated_trials": 0,
        "rejected_trials": 0, "unknown_trials": 1, "reasons": ["no_clock_trials"]}
