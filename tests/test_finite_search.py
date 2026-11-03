from copy import deepcopy
import sqlite3

import pytest

from aircraft_geoloc.data_access import DataUnavailable
from aircraft_geoloc.finite_search import RetentionLedger, classified_assessment, identify_mode
from aircraft_geoloc.tiled_search import merge_candidates


KIND = "matched_group_support_minus_normalized_residual"


def row(x, score, clock=100., groups=1):
    return {"x": x, "y": 0., "lat": 40., "lon": -100., "elev_m": 10., "score": score,
            "score_kind": KIND, "recording_start_time_s": clock,
            "event_indices": list(range(groups)), "flight_ids": [f"flight{i}" for i in range(groups)],
            "pass_emission_times_s": [90.+i*50 for i in range(groups)]}


def evidence(ledger, kept, **kwargs):
    return ledger.evidence(kept, complete=True, spacing_m=1000, refine_spacing_m=100, max_event_groups=4, **kwargs)


def test_mode_identity_is_exact_spatial_clock_pass_and_group_seed():
    original = row(1., .4)
    identity = identify_mode(original)
    duplicate = deepcopy(original); duplicate.update(point_id=999, score=.5)
    assert identify_mode(duplicate) == identity
    for alternate in [row(1.+1e-8, .4), row(1., .4, clock=100.+1e-8), row(1., .4, groups=2)]:
        assert identify_mode(alternate) != identity
    alternate = row(1., .4); alternate["pass_emission_times_s"] = [90.+1e-8]
    assert identify_mode(alternate) != identity
    # A continuous refinement remains a representation of the original seed.
    refined = deepcopy(original); refined.update(x=2., recording_start_time_s=101.)
    assert identify_mode(refined) == identity


def test_every_retention_stage_contributes_to_distinct_discard_bound(tmp_path):
    ledger = RetentionLedger(tmp_path / "retention.sqlite", "run", KIND)
    a, b, c, d = row(0, .90), row(1, .89), row(2, .895), row(3, .8)
    first = merge_candidates([a, b], 1, ledger=ledger, stage="coarse:a")
    second = merge_candidates([c, d], 1, ledger=ledger, stage="coarse:b")
    kept = merge_candidates(first+second, 1, ledger=ledger, stage="global:a")
    improved = deepcopy(kept[0]); improved["score"] = .92
    kept = merge_candidates(kept+[improved], 1, ledger=ledger, stage="fine:a")
    result = evidence(ledger, kept)
    assert result["complete"] and result["pruning_accounted_for"]
    assert result["evaluated_modes"] == 4 and result["discarded_count"] == 3
    assert result["best_discarded_score"] == .895
    assert result["retained_modes"][0]["score"] == .92
    assert result["stages"]["fine"]["exact_duplicates"] == 1
    # Deterministic stage replay replaces its rows, without inflating totals.
    checksum = ledger.checksum("coarse:a")
    merge_candidates([a, b], 1, ledger=ledger, stage="coarse:a")
    assert ledger.stage_valid("coarse:a", checksum)
    assert evidence(ledger, kept)["discarded_count"] == 3


def test_exact_duplicates_are_not_competing_discarded_modes(tmp_path):
    ledger = RetentionLedger(tmp_path / "retention.sqlite", "run", KIND)
    a = row(0, 1.)
    kept = merge_candidates([a, deepcopy(a)], 1, ledger=ledger, stage="coarse:a")
    result = evidence(ledger, kept)
    assert result["discarded_count"] == 0 and result["best_discarded_score"] is None
    assert result["stages"]["coarse"]["exact_duplicates"] == 1


def test_missing_or_corrupt_accounting_cannot_become_zero_discards(tmp_path):
    ledger = RetentionLedger(tmp_path / "retention.sqlite", "run", KIND)
    kept = merge_candidates([row(0, 1.), row(1, .99)], 1, ledger=ledger, stage="coarse:a")
    with sqlite3.connect(ledger.path) as db:
        db.execute("DELETE FROM records WHERE mode_id<>?", (kept[0]["mode_id"],))
    result = evidence(ledger, kept)
    assert not result["complete"] and not result["pruning_accounted_for"]
    assert result["discarded_count"] is None and result["best_discarded_score"] is None
    assert not ledger.stage_valid("coarse:a", ledger.checksum("coarse:a"))


def test_ledger_rejects_wrong_run_or_score_units_and_missing_stages(tmp_path):
    path = tmp_path / "retention.sqlite"
    ledger = RetentionLedger(path, "run", KIND)
    kept = merge_candidates([row(0, 1.)], 1, ledger=ledger, stage="coarse:a")
    with pytest.raises(DataUnavailable, match="identity mismatch"):
        RetentionLedger(path, "different-run", KIND)
    wrong = row(1, 2.); wrong["score_kind"] = "negative_robust_ridge_loss_hz"
    with pytest.raises(DataUnavailable, match="score units"):
        merge_candidates([wrong], 1, ledger=ledger, stage="global:a")
    result = evidence(ledger, kept, expected_stages={"coarse": 1, "global": 1})
    assert not result["pruning_accounted_for"] and result["discarded_count"] is None


def test_a_finite_best_score_does_not_hide_unknown_optimizer_trials():
    good = {"complete": True, "evaluated_trials": 5, "rejected_trials": 2, "unknown_trials": 0}
    assert classified_assessment({"score": .9, "scoring_assessment": good})
    assert not classified_assessment({"score": .9})
    for change in [{"complete": False}, {"unknown_trials": 1}, {"evaluated_trials": None}, {"rejected_trials": -1}]:
        assert not classified_assessment({"score": .9, "scoring_assessment": dict(good, **change)})
    for score in [float("nan"), float("inf"), -float("inf")]:
        assert not classified_assessment({"score": score, "scoring_assessment": good})
    empty = dict(good, evaluated_trials=0, rejected_trials=0)
    assert not classified_assessment({"score": .9, "scoring_assessment": empty})
    assert not classified_assessment({"score": -float("inf"), "scoring_assessment": empty})
    rejected = dict(empty, rejected_trials=3)
    assert classified_assessment({"score": -float("inf"), "scoring_assessment": rejected})
