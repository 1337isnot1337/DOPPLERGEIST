"""Finite-scope transport controls; producers are controlled, not location evidence."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from dopplergeist import automatic, matching
from dopplergeist.jobs import read_json


@pytest.mark.parametrize("bad_core", [None, "partial_support", "missing_core", "missing_id", "near_cluster",
                                      "producer_unassessed_core", "missing_assessment_map", "malformed_assessment_map"])
def test_finite_scope_assesses_supported_frozen_seeds_and_preserves_ids(tmp_path, monkeypatch, bad_core):
    events = [{"event_id": f"event-{i}", "start_s": i*100., "end_s": i*100.+20., "band_hz": [90., 200.],
               "ridge": [{"time_s": i*100.+t, "frequency_hz": 140.-t} for t in (0., 10., 20.)]} for i in range(2)]
    rows = []
    for identity, lat, score in (("mode-a", 40., -.1), ("mode-b", 41., -10.)):
        fit = {"score": score/2, "rmse_hz": abs(score/2), "support_fraction": 1.,
               "outlier_fraction": 0., "drift_at_bound": False}
        rows.append({"mode_id": identity, "lat": lat, "lon": -100., "score": score,
                     "score_kind": "negative_robust_ridge_loss_hz", "flight_ids": ["a", "b"],
                     "recording_start_time_s": 1790000000., "event_diagnostics": [dict(fit), dict(fit)]})
    if bad_core == "partial_support":
        rows[1]["event_diagnostics"][0]["support_fraction"] = .5
    elif bad_core == "missing_core":
        rows[1]["event_diagnostics"] = []
    elif bad_core == "missing_id":
        rows[1].pop("mode_id")
    elif bad_core == "near_cluster":
        rows[1].update(lat=40.001, score=-.2)
        rows[1]["event_diagnostics"] = [dict(fit, score=-.1) for fit in rows[1]["event_diagnostics"]]
    evidence = {"schema_version": 1, "scope": "evaluated_finite_grid", "complete": True,
                "score_kind": "negative_robust_ridge_loss_hz", "spacing_m": 1000., "refine_spacing_m": 100.,
                "max_event_groups": 2, "retained_modes": [{"mode_id": "mode-a", "score": -.1, "event_groups": 2},
                                                          {"mode_id": "mode-b", "score": rows[1]["score"], "event_groups": 2}],
                "discarded_count": 0, "best_discarded_score": None, "pruning_accounted_for": True,
                "limitations": ["Evaluated points only; unperformed refinements and continuous space are not covered."]}
    search = {"ranked": rows, "status": "complete", "scoring_time_is_locked": True,
              "alternative_modes_exhaustively_assessed": False, "finite_search_evidence": evidence,
              "core_assessed_mode_ids": ["mode-a", "mode-b"]}
    if bad_core == "producer_unassessed_core":
        search["core_assessed_mode_ids"] = ["mode-a"]
    elif bad_core == "missing_assessment_map":
        search.pop("core_assessed_mode_ids")
    elif bad_core == "malformed_assessment_map":
        search["core_assessed_mode_ids"] = "mode-a"
    before = deepcopy(search)
    state = {"recording": {"time_window": {"start_utc": "2026-09-21T14:13:20Z", "end_utc": "2026-09-21T14:13:20Z", "source": "user"}},
             "coverage": {"search_complete": True, "data_status": "available", "limitations": []}}
    tracks = [SimpleNamespace(id=name, time=[0., 1.], altitude_basis=["ellipsoidal"]) for name in ("a", "b")]
    index = SimpleNamespace(query=lambda *args: tracks)
    # Deliberately omit mode_id in producer returns: the orchestrator must retain
    # the source seed identity without recomputing it from optimized coordinates.
    def refine(row, *args, **kwargs):
        return {key: value for key, value in row.items() if key != "mode_id"}
    def profile(row, *args, **kwargs):
        return dict(refine(row), sensitivity={"radius_m": 80., "kind": "sensitivity", "method": "declared_perturbation_profiles",
                    "complete": True, "boundary_limited": False, "sources": ["frequency", "clock", "altitude", "sound_speed"],
                    "settings": {"clock_bounds_s": [1790000000., 1790000000.]}})
    monkeypatch.setattr(matching, "refine_candidate", refine)
    monkeypatch.setattr(matching, "profile_candidate", profile)
    def finish(status, reason_code=None, message=None, **fields):
        return dict(status=status, reason_code=reason_code, **fields)
    final = automatic._decide(search, events, events, [None]*2, [index], None, state, tmp_path,
                              {"refine_finalists": 1}, finish, lambda: None)
    receipt = read_json(tmp_path/"refined-candidates.json")
    diagnostics = receipt["matching_diagnostics"]
    assert search == before
    assert diagnostics["finite_search_evidence"] == evidence
    assert diagnostics["alternatives_evaluated"] is False
    assert diagnostics["unrefined_hypotheses"] == 1
    assert len(diagnostics["candidate_mode_ids"]) == len(final["candidates"])
    assert diagnostics["candidate_mode_ids"].count("mode-a") == 2
    if bad_core in (None, "near_cluster"):
        assert final["status"] == "succeeded", final
        assert diagnostics["assessed_mode_ids"] == ["mode-a", "mode-b"]
        decision = read_json(tmp_path/"decision.json")
        assert decision["diagnostics"]["finite_search"]["continuous_space_uniqueness"] == "not established"
        assert decision["candidates"] == final["candidates"]
        if bad_core == "near_cluster":
            uncertainty = final["candidates"][0]["uncertainty"]
            assert uncertainty["method"] == "finite_mode_and_tested_profile_union"
            assert 110. < uncertainty["radius_m"] < 112.
            assert final["candidates"][0]["lat"] == 40.
            assert final["candidates"][0]["score"] == -.1
    else:
        assert final["status"] == "inconclusive", final
        expected = [] if bad_core in ("missing_assessment_map", "malformed_assessment_map") else ["mode-a"]
        assert diagnostics["assessed_mode_ids"] == expected


def test_finite_scope_limitations_are_visible_in_coverage():
    limit = "Only evaluated parameter points, not continuous uniqueness."
    coverage = automatic._coverage({"search": {"coverage": "conus"}},
        {"tiles_total": 1, "tiles_completed": 1, "data_scope_complete": True,
         "finite_search_evidence": {"limitations": [limit]}}, {})
    assert limit in coverage["limitations"]
