"""A bound accounts for a trial; it does not fabricate a supported trajectory."""
from copy import deepcopy

import pytest

from dopplergeist.automatic import _coverage


def report():
    return {
        "status": "complete", "tiles_total": 2, "tiles_completed": 2,
        "data_scope_complete": True, "all_event_groups_considered": True,
        "model_support_complete": False, "model_assessment_complete": True,
        "model_support": {
            "unsupported_cpa_track_evaluations": 0, "unclassified_score_candidates": 2,
            "evaluated_trials": 4, "rejected_trials": 1, "unknown_trials": 3,
            "unreported_trial_envelopes": 0, "bounded_score_candidates": 2,
            "unbounded_score_candidates": 0,
        },
        "finite_search_evidence": {
            "schema_version": 1, "scope": "evaluated_finite_grid",
            "score_kind": "matched_group_support_minus_normalized_residual",
            "complete": True, "pruning_accounted_for": True, "max_event_groups": 4,
            "bounded_unknown_envelopes": 2, "bounded_unknown_rejections": 1,
            "best_unknown_score_upper_bound": 1.0, "discarded_count": 1,
            "best_discarded_score": 1.0, "unclassified_score_candidates": 2,
            "unsupported_cpa_track_evaluations": 0,
        },
    }


def coverage(value):
    return _coverage({"search": {"coverage": "conus"}}, value, {})


def test_certified_bounds_account_for_work_without_relabeling_missing_support():
    value = report()
    original = deepcopy(value)
    result = coverage(value)
    assert result["search_complete"] is True
    assert result["data_status"] == "available"
    assert "certified score bounds" in " ".join(result["limitations"])
    assert "unknown clock trials: 3" in " ".join(result["limitations"])
    assert value == original
    assert value["model_support_complete"] is False


def test_competitive_bounds_are_left_for_the_unchanged_confidence_decision():
    value = report()
    value["finite_search_evidence"].update(best_unknown_score_upper_bound=4., best_discarded_score=4.)
    assert coverage(value)["search_complete"] is True


def test_every_missing_fit_may_have_a_certified_rejecting_event():
    value = report()
    value["finite_search_evidence"].update(bounded_unknown_rejections=2,
        best_unknown_score_upper_bound=None, discarded_count=0, best_discarded_score=None)
    assert coverage(value)["search_complete"] is True


@pytest.mark.parametrize("section,key,value", [
    (None, "model_assessment_complete", False),
    (None, "model_assessment_complete", 1),
    (None, "model_support_complete", True),
    (None, "status", "partial"),
    ("model_support", "bounded_score_candidates", 1),
    ("model_support", "bounded_score_candidates", True),
    ("model_support", "unclassified_score_candidates", 3),
    ("model_support", "unknown_trials", 1),
    ("model_support", "unknown_trials", True),
    ("model_support", "unsupported_cpa_track_evaluations", 1),
    ("model_support", "unreported_trial_envelopes", 1),
    ("model_support", "unbounded_score_candidates", 1),
    ("finite_search_evidence", "complete", False),
    ("finite_search_evidence", "pruning_accounted_for", False),
    ("finite_search_evidence", "scope", "continuous_space"),
    ("finite_search_evidence", "schema_version", True),
    ("finite_search_evidence", "score_kind", "negative_robust_ridge_loss_hz"),
    ("finite_search_evidence", "bounded_unknown_envelopes", 1),
    ("finite_search_evidence", "bounded_unknown_rejections", 3),
    ("finite_search_evidence", "bounded_unknown_rejections", True),
    ("finite_search_evidence", "unclassified_score_candidates", 1),
    ("finite_search_evidence", "unsupported_cpa_track_evaluations", 1),
    ("finite_search_evidence", "max_event_groups", 0),
    ("finite_search_evidence", "discarded_count", 0),
    ("finite_search_evidence", "best_discarded_score", .5),
    ("finite_search_evidence", "best_unknown_score_upper_bound", None),
    ("finite_search_evidence", "best_unknown_score_upper_bound", float("nan")),
    ("finite_search_evidence", "best_unknown_score_upper_bound", -1.),
    ("finite_search_evidence", "best_unknown_score_upper_bound", 5.),
])
def test_incomplete_or_inconsistent_bound_accounting_does_not_restore_coverage(section, key, value):
    source = report()
    (source if section is None else source[section])[key] = value
    assert coverage(source)["search_complete"] is False


@pytest.mark.parametrize("section,key", [
    (None, "model_assessment_complete"), (None, "model_support_complete"),
    ("model_support", "unreported_trial_envelopes"),
    ("finite_search_evidence", "bounded_unknown_envelopes"),
])
def test_missing_new_evidence_cannot_silently_default_to_complete(section, key):
    source = report()
    del (source if section is None else source[section])[key]
    assert coverage(source)["search_complete"] is False


@pytest.mark.parametrize("changes", [
    {"tiles_completed": 1}, {"tile_failures": [{"tile": "missing"}]},
    {"refinement_failure": "budget exhausted"}, {"all_event_groups_considered": False},
])
def test_certified_scoring_bounds_do_not_cover_other_missing_work(changes):
    source = report()
    source.update(changes)
    assert coverage(source)["search_complete"] is False


def test_flight_coverage_stays_partial_despite_complete_scoring_accounting():
    source = report()
    source["data_scope_complete"] = False
    result = coverage(source)
    assert result["data_status"] == "partial"
    assert "historical_flight_scope_or_audible_border_region" in result["missing_data"]


def test_declared_incomplete_assessment_overrides_legacy_complete_support():
    source = report()
    source.update(model_support_complete=True, model_assessment_complete=False)
    source["model_support"].update(unclassified_score_candidates=0, unknown_trials=0,
                                  bounded_score_candidates=0)
    assert coverage(source)["search_complete"] is False


def test_assessment_flag_without_raw_support_evidence_is_incomplete():
    source = report()
    del source["model_support_complete"], source["model_support"]
    assert coverage(source)["search_complete"] is False
