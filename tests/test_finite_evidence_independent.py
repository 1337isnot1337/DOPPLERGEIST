"""Independent decision-contract controls; these do not simulate a national run."""
from copy import deepcopy

from aircraft_geoloc.confidence import decide_location


def bundle():
    events = [
        {"event_id": f"event-{i}", "start_s": 100.0*i, "end_s": 100.0*i+20.0,
         "band_hz": [90.0, 200.0], "harmonic_group_id": f"flyover-{i}",
         "ridge": [{"time_s": 100.0*i+t, "frequency_hz": 160.0-t}
                   for t in (0.0, 10.0, 20.0)]}
        for i in range(2)
    ]
    candidates = [{"lat": 40.0, "lon": -100.0, "score": 1.8,
                   "score_kind": "matched_group_support_minus_normalized_residual",
                   "event_ids": ["event-0", "event-1"], "flight_ids": ["a", "b"],
                   "recording_start_utc": "2026-09-21T14:13:20Z",
                   "uncertainty": {"kind": "sensitivity", "radius_m": 100.0,
                                   "method": "independent_contract_control"}}]
    coverage = {"search_complete": True, "data_status": "available",
                "limitations": ["This is a decision-only control."]}
    diagnostics = {"clock_locked": True, "alternatives_evaluated": False,
                   "refinement_boundary_limited": False,
                   "sensitivity": {"complete": True, "boundary_limited": False,
                                   "radius_m": 100.0,
                                   "sources": ["frequency", "clock", "altitude", "sound_speed"]},
                   "assessed_mode_ids": ["seed-a"], "candidate_mode_ids": ["seed-a"],
                   "finite_search_evidence": {
                       "schema_version": 1, "scope": "evaluated_finite_grid", "complete": True,
                       "score_kind": candidates[0]["score_kind"],
                       "spacing_m": 1000.0, "refine_spacing_m": 100.0,
                       "max_event_groups": 2,
                       "retained_modes": [{"mode_id": "seed-a", "score": 1.8, "event_groups": 2}],
                       "discarded_count": 0, "best_discarded_score": None,
                       "pruning_accounted_for": True,
                       "limitations": ["Only declared evaluated finite points are compared."]}}
    for event in events:
        diagnostics[event["event_id"]] = {"rmse_hz": 0.2, "outlier_fraction": 0.0,
                                          "support_fraction": 1.0, "drift_at_bound": False}
    return events, candidates, coverage, diagnostics


def decide(case):
    return decide_location(*case[:3], matching_diagnostics=case[3])


def test_refinement_improvement_does_not_rewrite_immutable_seed_evidence():
    case = bundle()
    original = deepcopy(case[1][0])
    case[1][0]["score"] = 1.95
    case[1].append(original)
    case[3]["candidate_mode_ids"].append("seed-a")
    before = deepcopy(case)
    assert decide(case)["status"] == "succeeded"
    assert case == before
    assert case[3]["finite_search_evidence"]["retained_modes"][0]["score"] == 1.8


def test_a_worse_refinement_cannot_erase_the_better_original_seed():
    case = bundle()
    case[1][0]["score"] = 1.6
    assert decide(case)["reason_code"] == "finite_candidate_scores_inconsistent"


def test_full_finite_accounting_does_not_hide_same_association_distant_mode():
    case = bundle()
    alternative = dict(case[1][0], lat=45.0, score=1.7)
    case[1].append(alternative)
    case[3]["candidate_mode_ids"].append("seed-b")
    case[3]["assessed_mode_ids"].append("seed-b")
    case[3]["finite_search_evidence"]["retained_modes"].append(
        {"mode_id": "seed-b", "score": 1.7, "event_groups": 2})
    result = decide(case)
    assert result["status"] == "inconclusive"
    assert result["reason_code"] == "ambiguous_locations"


def test_global_group_bound_is_used_for_a_potentially_larger_discarded_subset():
    case = bundle()
    for i in range(2, 6):
        event = deepcopy(case[0][0])
        event.update(event_id=f"event-{i}", harmonic_group_id=f"flyover-{i}",
                     start_s=100.0*i, end_s=100.0*i+20.0)
        for point in event["ridge"]:
            point["time_s"] += 100.0*i
        case[0].append(event)
    case[3]["unmatched_event_ids"] = [f"event-{i}" for i in range(2, 6)]
    finite = case[3]["finite_search_evidence"]
    finite.update(max_event_groups=6, discarded_count=1, best_discarded_score=0.9)
    # 0.9/2 would pass, but 0.9/6 cannot exclude a six-group competitor.
    assert decide(case)["reason_code"] == "retention_may_hide_alternatives"


def test_exact_declared_discard_margin_remains_competitive():
    case = bundle()
    finite = case[3]["finite_search_evidence"]
    finite.update(discarded_count=1, best_discarded_score=1.4)
    # The declared real-valued gap is (1.8-1.4)/2 == 0.2. Rounding cannot
    # promote equality across the existing strict-more-than retention gate.
    result = decide(case)
    assert result["status"] == "inconclusive"
    assert result["reason_code"] == "retention_may_hide_alternatives"


def test_a_resolved_discard_margin_remains_distinct_from_equality():
    case = bundle()
    case[3]["finite_search_evidence"].update(discarded_count=1, best_discarded_score=1.399999)
    assert decide(case)["status"] == "succeeded"


def test_exact_declared_retained_margin_remains_competitive():
    case = bundle()
    case[1].append(dict(case[1][0], lat=45.0, score=1.4))
    case[3]["candidate_mode_ids"].append("seed-b")
    case[3]["assessed_mode_ids"].append("seed-b")
    case[3]["finite_search_evidence"]["retained_modes"].append(
        {"mode_id": "seed-b", "score": 1.4, "event_groups": 2})
    result = decide(case)
    assert result["status"] == "inconclusive"
    assert result["reason_code"] == "ambiguous_locations"
