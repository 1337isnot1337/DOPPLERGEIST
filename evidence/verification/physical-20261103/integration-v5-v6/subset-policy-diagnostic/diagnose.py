from copy import deepcopy
import json
from aircraft_geoloc.confidence import DecisionPolicy, decide_location
from test_finite_evidence_independent import bundle

results = []
for count in range(2, 9):
    case = bundle()
    template = deepcopy(case[0][0])
    case[0].clear()
    for i in range(count):
        event = deepcopy(template)
        event.update(event_id=f"event-{i}", harmonic_group_id=f"flyover-{i}", start_s=100.*i, end_s=100.*i+20.)
        for point in event["ridge"]:
            point["time_s"] += 100.*i
        case[0].append(event)
        case[3][event["event_id"]] = {"rmse_hz": 0., "outlier_fraction": 0., "support_fraction": 1., "drift_at_bound": False}
    leading = case[1][0]
    leading.update(score=float(count), event_ids=[e["event_id"] for e in case[0]], flight_ids=[f"flight-{i}" for i in range(count)])
    finite = case[3]["finite_search_evidence"]
    finite.update(max_event_groups=count, retained_modes=[{"mode_id": "seed-a", "score": float(count), "event_groups": count}])
    alone = decide_location(*case[:3], matching_diagnostics=case[3])
    subset = deepcopy(leading)
    subset.update(score=float(count-1), event_ids=leading["event_ids"][:-1], flight_ids=leading["flight_ids"][:-1])
    case[1].append(subset)
    case[3]["assessed_mode_ids"].append("seed-b")
    case[3]["candidate_mode_ids"].append("seed-b")
    finite["retained_modes"].append({"mode_id": "seed-b", "score": float(count-1), "event_groups": count-1})
    before = deepcopy(case)
    compared = decide_location(*case[:3], matching_diagnostics=case[3])
    assert case == before
    assert alone["status"] == "succeeded"
    results.append({"independent_groups": count, "leading_score": leading["score"], "nested_subset_score": subset["score"],
                    "score_gap_per_max_group": 1./count, "same_point_clock": True, "all_shared_event_flight_assignments_identical": True,
                    "leading_only_status": alone["status"], "with_nested_subset_status": compared["status"], "reason_code": compared["reason_code"],
                    "competing_hypothesis": compared["diagnostics"].get("competing_hypothesis")})
print(json.dumps({"scope": "Decision-only structural diagnostic; no acoustic search or new accepted localization", "policy_margin": DecisionPolicy().near_tie_support_per_group, "cases": results}, indent=2))
