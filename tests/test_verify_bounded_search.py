"""Recorded score ceilings must survive the independent retention audit."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from dopplergeist.data_access import content_hash
from dopplergeist.finite_search import RetentionLedger, identify_mode


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("verify_bounded_http", ROOT / "scripts/verify_upload_http.py")
HTTP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HTTP)
KIND = "matched_group_support_minus_normalized_residual"


@pytest.fixture
def bounded_search(tmp_path):
    directory = tmp_path / "job"
    (directory / "search/support").mkdir(parents=True)
    configuration = {"events": [{"event_id": "e0"}], "budget": {"spacing_m": 1000., "refine_spacing_m": 100.},
        "scoring": {"recording_start_window_s": [100., 100.], "time_step_s": .5, "time_sweep_s": 0.},
        "code": {"matching.py": "fit-code", "search.py": "score-code"}}
    rows = []
    for index, score in enumerate((.95, .94, .1)):
        row = {"point_id": index, "x": float(index), "y": 0., "lat": 40. + index*.001,
            "lon": -100., "elev_m": 0., "recording_start_time_s": 100., "score": score, "score_kind": KIND,
            "event_indices": [0], "flight_ids": ["flight-0"], "pass_emission_times_s": [104.],
            "scoring_assessment": {"complete": True, "scheduled_trials": 1, "evaluated_trials": 1,
                "rejected_trials": 0, "unknown_trials": 0, "empty_clock_domain": False, "reasons": [],
                "trial_count_semantics": "disjoint_evaluated_rejected_unknown"},
            "core_assessment_complete": True, "event_diagnostics": [{"support_fraction": 1., "score": -.1}]}
        identify_mode(row)
        rows.append(row)
    certificates = []
    for index, upper in enumerate((.5, None)):
        detail = {"point_id": index + 3, "envelope_index": index + 1, "score_kind": KIND,
            "receiver": {"x": float(index+3), "y": 0., "lat": 41., "lon": -100., "elev_m": 0.},
            "event_indices": [0], "flight_ids": ["flight-1"], "pass_emission_times_s": [104.],
            "recording_start_bounds_s": [100., 100.],
            "clock_settings": {"time_origin": None, "time_sweep_s": 0., "time_step_s": .5},
            "support_failure": None, "finite_best": False,
            "scoring_assessment": {"complete": False, "scheduled_trials": 1, "evaluated_trials": 0,
                "rejected_trials": 0, "unknown_trials": 1, "empty_clock_domain": False,
                "trial_count_semantics": "disjoint_evaluated_rejected_unknown",
                "reasons": ["incomplete_ridge_or_trajectory_support"], "bounded_unknown_trials": 1,
                "bounded_unknown_rejections": int(upper is None), "unknown_score_upper_bound": upper,
                "unknown_score_bound_kind": KIND,
                "unknown_score_bound_method": "nonnegative_loss_and_validated_event_fits"}}
        certificates.append({"bound_id": "bound-" + content_hash(detail), "upper_score": upper,
                             "groups_count": 1, "detail": detail})
    ledger = RetentionLedger(directory / "search/retention.sqlite", "run-control", KIND)
    checksum = ledger.record("coarse:0_0", rows, rows[:2], len(rows), bounds=certificates)
    ledger.record("global:0_0", rows[:2], rows[:2], 2)
    details = [item["detail"] for item in certificates]
    payload = {"ranked": rows[:2], "retention_checksum": checksum, "counts": {
        "unclassified_score_candidates": 2, "bounded_score_candidates": 2, "unbounded_score_candidates": 0,
        "unclassified_candidate_assessments": details, "unsupported_cpa_tracks": []}}
    (directory / "search/tile-0_0.json").write_text(json.dumps(
        {"run_hash": "run-control", "payload": payload, "payload_hash": content_hash(payload)}))
    (directory / "search/support/coarse-0_0.json").write_text(json.dumps({"stage": "coarse:0_0",
        "unclassified_candidate_assessments": details, "unsupported_cpa_tracks": []}))
    finite = ledger.evidence(rows[:2], complete=True, spacing_m=1000., refine_spacing_m=100., max_event_groups=1)
    finite.update(ledger_artifact="retention.sqlite", unclassified_score_candidates=2,
        unsupported_cpa_track_evaluations=0, discarded_bound_status="includes_bounded_unknown_trials",
        optimizer_domain={"run_hash": "run-control", "source_fit_code_sha256": "fit-code",
            "score_code_sha256": "score-code", "clock_window_s": [100., 100.],
            "time_step_s": .5, "declared_sweep_s": 0.})
    ids = [row["mode_id"] for row in rows[:2]]
    search = {"run_hash": "run-control", "status": "complete", "ranked": rows[:2], "tiles_completed": 1,
        "refinement_points_searched": 0, "core_assessed_mode_ids": ids, "finite_search_evidence": finite,
        "model_support_complete": False, "model_assessment_complete": True,
        "model_support": {"unsupported_cpa_track_evaluations": 0, "unclassified_score_candidates": 2,
            "bounded_score_candidates": 2, "unbounded_score_candidates": 0, "unknown_trials": 2,
            "evaluated_trials": 3, "rejected_trials": 0, "unreported_trial_envelopes": 0}}
    refinement = {"ranked": deepcopy(rows[:2]), "matching_diagnostics": {
        "finite_search_evidence": deepcopy(finite), "recording_start_window_s": [100., 100.],
        "assessed_mode_ids": sorted(ids), "candidate_mode_ids": ids, "core_assessment_mapping_status": "present"}}
    return directory, search, configuration, refinement


def inspect(fixture):
    directory, search, configuration, refinement = fixture
    return HTTP.inspect_finite_search(lambda name: directory / name,
        lambda name: json.loads((directory / name).read_text()), search, configuration, refinement)


def test_persisted_bounds_account_for_unknowns_without_claiming_supported_fits(bounded_search):
    directory, search, _, _ = bounded_search
    before = (directory / "search/retention.sqlite").read_bytes()
    report = inspect(bounded_search)
    assert report["complete"] is True
    assert report["unknown_score_bounds_verified"] is True
    assert report["bounded_unknown_envelopes"] == 2
    assert report["bounded_unknown_rejections"] == 1
    assert report["best_unknown_score_upper_bound"] == .5
    assert report["best_discarded_score"] == .5 and report["discarded_count"] == 2
    assert report["unclassified_score_candidates"] == 2
    assert report["physical_trials_independently_recomputed"] is False
    assert search["model_support_complete"] is False
    assert (directory / "search/retention.sqlite").read_bytes() == before


@pytest.mark.parametrize("defect", ["missing_support", "changed_support", "missing_bound", "changed_bound",
    "wrong_maximum", "wrong_rejections", "wrong_unknown_total", "wrong_unknown_trials", "false_support",
    "unbounded_model", "invented_core_id"])
def test_bounded_acceptance_rejects_missing_or_inconsistent_evidence(bounded_search, defect):
    directory, search, _, refinement = bounded_search
    finite = search["finite_search_evidence"]
    if defect == "missing_support":
        (directory / "search/support/coarse-0_0.json").unlink()
    elif defect == "changed_support":
        path = directory / "search/support/coarse-0_0.json"
        value = json.loads(path.read_text())
        value["unclassified_candidate_assessments"][0]["receiver"]["lat"] += .1
        path.write_text(json.dumps(value))
    elif defect in {"missing_bound", "changed_bound"}:
        with sqlite3.connect(directory / "search/retention.sqlite") as db:
            db.execute("DELETE FROM bounds" if defect == "missing_bound" else "UPDATE bounds SET upper_score=0.1 WHERE upper_score IS NOT NULL")
    elif defect in {"wrong_maximum", "wrong_rejections", "wrong_unknown_total"}:
        key, value = {"wrong_maximum": ("best_unknown_score_upper_bound", .1),
            "wrong_rejections": ("bounded_unknown_rejections", 2),
            "wrong_unknown_total": ("unclassified_score_candidates", 1)}[defect]
        finite[key] = value
        refinement["matching_diagnostics"]["finite_search_evidence"][key] = value
    elif defect == "wrong_unknown_trials":
        search["model_support"]["unknown_trials"] = 1
    elif defect == "false_support":
        search["model_support_complete"] = True
    elif defect == "unbounded_model":
        search["model_support"]["unbounded_score_candidates"] = 1
    else:
        search["core_assessed_mode_ids"].append("bound-is-not-a-mode")
    with pytest.raises(ValueError):
        inspect(bounded_search)


@pytest.mark.parametrize("key,value", [("scheduled_trials", 0), ("scheduled_trials", True),
    ("bounded_unknown_trials", 0), ("bounded_unknown_rejections", 2),
    ("unknown_score_upper_bound", 1.1), ("unknown_score_upper_bound", float("nan")),
    ("empty_clock_domain", True), ("complete", True)])
def test_clock_bound_certificate_requires_every_unknown_trial(bounded_search, key, value):
    path = bounded_search[0] / "search/support/coarse-0_0.json"
    detail = json.loads(path.read_text())["unclassified_candidate_assessments"][0]
    detail["scoring_assessment"][key] = value
    assert HTTP.bounded_finite_clock_assessment(detail, 1) is False
