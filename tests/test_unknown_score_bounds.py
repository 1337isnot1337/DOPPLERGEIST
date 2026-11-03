"""Unknown trajectory support stays unknown; finite score ceilings can exclude it."""
from copy import deepcopy
from types import SimpleNamespace
import sqlite3

import numpy as np
import pytest

from dopplergeist import matching
from dopplergeist.data_access import DataUnavailable, content_hash
from dopplergeist.finite_search import RetentionLedger, bounded_assessment, classified_assessment
from dopplergeist.matching import RidgeTimes, association_score, score_ridges
from dopplergeist.search import _association_trial_bound, score_candidate
from dopplergeist.tiled_search import merge_candidates
from test_scoring_assessment import Model
from test_finite_search import row


KIND = "matched_group_support_minus_normalized_residual"


def inputs(models, frequencies=None):
    times = np.arange(0., 20., .5)
    frequencies = frequencies or [120.] * len(models)
    events = [{"event_id": f"e{i}", "cpa_receive_s": 10., "f0_range_hz": [119., 121.]}
              for i in range(len(models))]
    measurements = [(RidgeTimes(times), np.full_like(times, value), np.ones_like(times), {})
                    for value in frequencies]
    return events, measurements


def core(models, frequencies=None):
    events, measurements = inputs(models, frequencies)
    return association_score(score_ridges(models, events, measurements, np.zeros(3), 0.), events), events


def envelope(models, frequencies=None):
    events, measurements = inputs(models, frequencies)
    point = SimpleNamespace(point_id=0, lat=40., lon=-100., elev_m=0., x=0., y=0.)
    tracks = {str(i): model for i, model in enumerate(models)}
    candidate = {"event_indices": list(range(len(models))),
                 "passes": [{"flight_id": identity, "receive_time": 10.} for identity in tracks]}
    return score_candidate(candidate, point, tracks, events, measurements, mode="robust_ridge",
                           time_origin=0., time_sweep_s=1., time_step_s=1.)


def persisted_bound(result):
    detail = {key: deepcopy(result[key]) for key in ("event_indices", "flight_ids", "score_kind", "scoring_assessment")}
    return {"bound_id": "bound-" + content_hash(detail), "detail": detail,
            "groups_count": len(result["event_indices"]),
            "upper_score": result["scoring_assessment"]["unknown_score_upper_bound"]}


def test_actual_missing_support_has_group_count_ceiling_without_claiming_a_fit():
    result = envelope([Model(last_supported=-10)] * 4)
    assessment = result["scoring_assessment"]
    assert result["score"] == -np.inf
    assert not assessment["complete"] and not classified_assessment(result)
    assert assessment["unknown_trials"] == assessment["bounded_unknown_trials"] == 3
    assert assessment["unknown_score_upper_bound"] == 4.
    assert assessment["reasons"] == ["incomplete_ridge_or_trajectory_support"]
    assert bounded_assessment(result)


def test_supported_event_rejects_an_association_but_missing_support_is_preserved():
    result = envelope([Model(), Model(last_supported=-10)], [200., 120.])
    assessment = result["scoring_assessment"]
    assert result["score"] == -np.inf and not assessment["complete"]
    assert assessment["unknown_trials"] == assessment["bounded_unknown_rejections"] == 3
    assert assessment["unknown_score_upper_bound"] is None
    assert assessment["rejected_trials"] == 0, "Missing core fits must not be relabelled as complete fits"
    assert bounded_assessment(result)


def test_supported_loss_tightens_bound_for_every_unknown_event_completion():
    partial, events = core([Model(), Model(last_supported=-10)], [122., 120.])
    upper = _association_trial_bound(partial, events)
    assert 1. < upper < 2.
    for frequency in np.linspace(100., 150., 21):
        completed, _ = core([Model(), Model()], [122., frequency])
        assert completed["score"] <= upper


@pytest.mark.parametrize("change", [{"support_fraction": .5}, {"optimizer_success": False},
    {"source_span_s": 0.}, {"f0_hz": np.nan}, {"source_drift_hz": 1000.}, {"rmse_hz": -1.}])
def test_invalid_supported_fit_cannot_tighten_or_reject(change):
    result, events = core([Model(), Model(last_supported=-10)], [200., 120.])
    assert _association_trial_bound(result, events) == -np.inf
    result["event_diagnostics"][0].update(change)
    assert _association_trial_bound(result, events) == 2.


@pytest.mark.parametrize("kind", [None, "summed_spectral_contrast", "negative_robust_ridge_loss_hz"])
def test_no_missing_fit_bound_for_another_score_definition(kind):
    result, events = core([Model(last_supported=-10)])
    result["score_kind"] = kind
    assert _association_trial_bound(result, events) is None


def test_maximum_bound_includes_every_scheduled_shared_clock(monkeypatch):
    models = [Model(), Model(last_supported=-10)]
    calls = 0
    original = matching.score_ridges

    def different_clock(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls != 2:
            result["event_diagnostics"][0]["optimizer_success"] = False
        return result

    monkeypatch.setattr(matching, "score_ridges", different_clock)
    result = envelope(models, [200., 120.])
    assessment = result["scoring_assessment"]
    assert calls == assessment["scheduled_trials"] == 3
    assert assessment["bounded_unknown_rejections"] == 1
    assert assessment["unknown_score_upper_bound"] == 2.


@pytest.mark.parametrize("change", [{"scheduled_trials": 2}, {"scheduled_trials": None},
    {"trial_count_semantics": "other"}, {"empty_clock_domain": True},
    {"bounded_unknown_trials": 2}, {"unknown_score_upper_bound": -1.},
    {"unknown_score_upper_bound": 2.}, {"bounded_unknown_rejections": 4}])
def test_persisted_bound_requires_complete_valid_counter_accounting(change):
    result = envelope([Model(last_supported=-10)])
    result["scoring_assessment"].update(change)
    assert not bounded_assessment(result)


def test_ledger_preserves_bounds_across_resume_and_the_existing_competitive_margin(tmp_path):
    ledger = RetentionLedger(tmp_path / "retention.sqlite", "run", KIND)
    winner = row(0., 3.8075341081656915, groups=4)
    small = persisted_bound(envelope([Model(last_supported=-10)]))
    rejected = persisted_bound(envelope([Model(), Model(last_supported=-10)], [200., 120.]))
    kept = merge_candidates([winner], 1, ledger=ledger, stage="coarse:a", bounds=[small, rejected])
    saved = ledger.checksum("coarse:a")
    options = dict(complete=True, spacing_m=1000, refine_spacing_m=100, max_event_groups=4)
    result = ledger.evidence(kept, **options)
    assert result["bounded_unknown_envelopes"] == 2
    assert result["bounded_unknown_rejections"] == 1 and result["discarded_count"] == 1
    assert result["best_unknown_score_upper_bound"] == result["best_discarded_score"] == 1.
    assert (winner["score"] - result["best_discarded_score"]) / 4 > .2
    resumed = RetentionLedger(ledger.path, "run", KIND)
    assert resumed.stage_valid("coarse:a", saved)
    assert resumed.evidence(kept, **options) == result
    large = persisted_bound(envelope([Model(last_supported=-10)] * 4))
    merge_candidates([], 1, ledger=resumed, stage="coarse:b", bounds=[large])
    competitive = resumed.evidence(kept, **options)
    assert competitive["best_discarded_score"] == 4.
    assert (winner["score"] - competitive["best_discarded_score"]) / 4 <= .2
    assert not resumed.evidence(kept, **dict(options, complete=False))["complete"]
    with sqlite3.connect(ledger.path) as db:
        db.execute("DELETE FROM bounds WHERE stage='coarse:b'")
    assert not resumed.evidence(kept, **options)["pruning_accounted_for"]


def test_ledger_refuses_wrong_score_kind_and_invalid_bound_detail(tmp_path):
    bound = persisted_bound(envelope([Model(last_supported=-10)]))
    wrong = RetentionLedger(tmp_path / "wrong.sqlite", "run", "summed_spectral_contrast")
    with pytest.raises(DataUnavailable, match="association-score bound"):
        wrong.record("coarse:a", [], [], 0, bounds=[bound])
    ledger = RetentionLedger(tmp_path / "correct.sqlite", "run", KIND)
    del bound["detail"]["scoring_assessment"]["scheduled_trials"]
    bound["bound_id"] = "bound-" + content_hash(bound["detail"])
    with pytest.raises(DataUnavailable, match="association-score bound"):
        ledger.record("coarse:a", [], [], 0, bounds=[bound])
