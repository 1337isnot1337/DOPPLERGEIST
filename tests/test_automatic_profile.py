"""Orchestration regressions for authoritative full-profile evidence.

Physical producers are controlled here to isolate score roundoff and failures;
the real candidate contracts, persisted receipts and confidence gates still run.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aircraft_geoloc import automatic, matching
from aircraft_geoloc.jobs import read_json


@pytest.fixture
def run_profile(tmp_path, monkeypatch):
    events = [{"event_id": f"event-{i}", "start_s": i * 100., "end_s": i * 100. + 20,
               "band_hz": [90., 200.], "harmonic_group_id": f"group-{i}",
               "ridge": [{"time_s": i * 100. + t, "frequency_hz": 140. - t}
                         for t in (0., 10., 20.)]} for i in range(2)]
    event_fit = {"rmse_hz": .1, "outlier_fraction": 0., "support_fraction": 1., "drift_at_bound": False}
    base = {"point_id": 23, "lat": 40., "lon": -100., "elev_m": 120.,
            "score": -.2720691034013313, "score_kind": "negative_robust_ridge_loss_hz",
            "recording_start_time_s": 1790000000., "flight_ids": ["a", "b"],
            "pass_emission_times_s": [1790000010., 1790000110.],
            "event_diagnostics": [dict(event_fit), dict(event_fit)]}
    # Keep another spatial mode for the same association and another association.
    raw = [base, dict(base, point_id=24, lat=41., score=-4.,
                     pass_emission_times_s=[1790000030., 1790000130.]),
           dict(base, point_id=25, lat=42., score=-5., flight_ids=["c", "d"])]
    search = {"status": "complete", "scoring_time_is_locked": True,
              "alternative_modes_exhaustively_assessed": True, "ranked": raw}
    state = {"recording": {"time_window": {"start_utc": "2026-09-21T14:13:20Z",
                                            "end_utc": "2026-09-21T14:13:20Z", "source": "user"}},
             "coverage": {"search_complete": True, "data_status": "available", "limitations": []}}
    tracks = [SimpleNamespace(id=identity, time=[0., 1.], altitude_basis=["ellipsoidal"])
              for identity in ("a", "b", "c", "d")]
    index = SimpleNamespace(query=lambda bounds, time_range: tracks)

    def refine(candidate, *args, **kwargs):
        return dict(candidate, score=candidate["score"] + .1,
                    sensitivity={"radius_m": 42.84, "method": "profiled_relative_altitude_offsets",
                                 "kind": "sensitivity", "complete": True, "boundary_limited": False})

    monkeypatch.setattr(matching, "refine_candidate", refine)

    def run(*, score_change=-2.99e-13, complete=True, error=None):
        before = deepcopy(search)

        def profile(candidate, *args, **kwargs):
            if error is not None:
                raise error
            failures = [] if complete else [{"source": "altitude", "scenario": "terrain",
                                            "reason": "Ellipsoidal terrain datum is not established"}]
            return dict(candidate, score=candidate["score"] + score_change,
                        sensitivity={"radius_m": 42.83, "method": "declared_perturbation_profiles",
                                     "kind": "sensitivity", "complete": complete, "boundary_limited": False,
                                     "sources": ["frequency", "clock", "altitude", "sound_speed"],
                                     "failures": failures})

        monkeypatch.setattr(matching, "profile_candidate", profile)

        def finish(status, reason_code=None, message=None, **fields):
            return dict(status=status, reason_code=reason_code, message=message, **fields)

        final = automatic._decide(search, events, events, [None] * 2, [index], None,
                                  state, tmp_path, {"refine_finalists": 3}, finish, lambda: None)
        receipt = read_json(tmp_path / "refined-candidates.json")
        assert search == before
        # Replacing validation evidence must not remove another retained mode.
        for row in raw:
            assert row in receipt["ranked"]
        for point_id in (24, 25):
            assert any(row["point_id"] == point_id and "sensitivity" in row for row in receipt["ranked"])
        return final, receipt

    return run


def test_full_profile_replaces_nominal_despite_score_roundoff(run_profile):
    final, receipt = run_profile()
    assert final["status"] == "succeeded", final
    assert len(receipt["ranked"]) == 6
    assert final["candidates"][0]["uncertainty"]["method"] == "declared_perturbation_profiles"
    assert receipt["matching_diagnostics"]["sensitivity"] == receipt["ranked"][0]["sensitivity"]


@pytest.mark.parametrize("score_change", [-2.99e-13, 0.])
def test_incomplete_full_profile_cannot_fall_back_to_complete_altitude_profile(run_profile, score_change):
    final, receipt = run_profile(score_change=score_change, complete=False)
    assert final["status"] == "inconclusive"
    assert final["reason_code"] == "uncertainty_not_established"
    assert "uncertainty" not in final["candidates"][0]
    assert len(receipt["ranked"]) == 6
    sensitivity = receipt["matching_diagnostics"]["sensitivity"]
    assert sensitivity["method"] == "declared_perturbation_profiles"
    assert sensitivity["complete"] is False
    assert sensitivity["failures"][0]["scenario"] == "terrain"


@pytest.mark.parametrize("error", [ValueError("Profile trajectory support is missing"), KeyError("profile input")])
def test_profile_exception_invalidates_previous_uncertainty(run_profile, error):
    final, receipt = run_profile(error=error)
    assert final["status"] == "inconclusive"
    assert "uncertainty" not in final["candidates"][0]
    assert len(receipt["ranked"]) == 6
    diagnostics = receipt["matching_diagnostics"]
    assert diagnostics["sensitivity"]["complete"] is False
    assert not diagnostics["sensitivity"].get("sources")
    assert str(error) in diagnostics["sensitivity"]["failures"][0]["reason"]
    assert any(str(error) in failure for failure in diagnostics["refinement_failures"])


def test_reranking_does_not_transfer_full_profile_to_another_candidate(run_profile):
    final, receipt = run_profile(score_change=-1.)
    assert final["status"] == "inconclusive"
    assert final["reason_code"] == "uncertainty_not_established"
    assert not receipt["matching_diagnostics"]["sensitivity"].get("sources")
    assert any(row.get("sensitivity", {}).get("method") == "declared_perturbation_profiles"
               for row in receipt["ranked"][1:])


def test_decision_candidate_copy_is_preserved_for_evidence_derived_envelopes(run_profile, monkeypatch):
    from aircraft_geoloc import confidence
    original = confidence.decide_location
    def decision(events, candidates, coverage, **kwargs):
        result = original(events, candidates, coverage, **kwargs)
        returned = deepcopy(candidates)
        returned[0]["uncertainty"] = {"radius_m": 120., "method": "finite_modes_and_tested_profiles", "kind": "sensitivity"}
        result["candidates"] = returned
        return result
    monkeypatch.setattr(confidence, "decide_location", decision)
    final, _ = run_profile()
    assert final["candidates"][0]["uncertainty"]["radius_m"] == 120.
    assert final["candidates"][0]["uncertainty"]["method"] == "finite_modes_and_tested_profiles"
