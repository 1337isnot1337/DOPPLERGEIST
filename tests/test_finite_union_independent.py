"""Independent geometric controls for the agreed finite-point/profile union.

These are decision-contract fixtures, not an acoustic or national benchmark.
The accepted rule is in discussion 39; production ownership remains with W4.
"""
from copy import deepcopy

from pyproj import Geod
import pytest

from test_finite_evidence_independent import bundle, decide


def shifted(case, distance_m, *, score, radius_m=None, mode_id="seed-b"):
    original = case[1][0]
    lon, lat, _ = Geod(ellps="WGS84").fwd(original["lon"], original["lat"], 90.0, distance_m)
    row = deepcopy(original)
    row.update(lat=lat, lon=lon, score=score)
    row.pop("uncertainty", None)
    if radius_m is not None:
        row["uncertainty"] = {"kind": "sensitivity", "radius_m": radius_m,
                              "method": "explicit_independent_control_profile"}
    case[1].append(row)
    evidence = case[3]
    evidence["candidate_mode_ids"].append(mode_id)
    if mode_id not in evidence["assessed_mode_ids"]:
        evidence["assessed_mode_ids"].append(mode_id)
        evidence["finite_search_evidence"]["retained_modes"].append(
            {"mode_id": mode_id, "score": score, "event_groups": 2})


def check_successful_union(case, expected_radius_m):
    before = deepcopy(case)
    result = decide(case)
    assert result["status"] == "succeeded", result
    returned = result["candidates"]
    assert len(returned) == len(case[1])
    assert returned is not case[1]
    assert returned[0] is not case[1][0]
    assert case == before
    assert returned[1:] == before[1][1:]
    assert {k: v for k, v in returned[0].items() if k != "uncertainty"} == {
        k: v for k, v in before[1][0].items() if k != "uncertainty"
    }
    uncertainty = returned[0]["uncertainty"]
    assert uncertainty["kind"] == "sensitivity"
    assert uncertainty["radius_m"] == pytest.approx(expected_radius_m, abs=1e-5)
    assert "coverage_probability" not in uncertainty
    assert "calibration_reference" not in uncertainty
    return result


def test_union_contains_a_displaced_reported_profile_not_just_its_center():
    case = bundle()
    shifted(case, 600.0, score=1.75, radius_m=300.0)
    # A 300 m profile about a point 600 m from the unchanged return center
    # needs 900 m. max(600, 300, 100) would understate the declared union.
    check_successful_union(case, 900.0)


def test_a_nearby_point_can_have_a_reported_profile_exceeding_the_target():
    case = bundle()
    shifted(case, 800.0, score=1.75, radius_m=300.0)
    before = deepcopy(case)
    result = decide(case)
    # Every center and individual radius is below 1 km, but their union is not.
    assert result["status"] == "inconclusive", result
    assert case == before


def test_raw_and_refined_states_sharing_one_seed_id_both_enter_the_union():
    case = bundle()
    case[1][0]["score"] = 1.95
    shifted(case, 600.0, score=1.8, mode_id="seed-a")
    assert case[3]["candidate_mode_ids"] == ["seed-a", "seed-a"]
    assert len(case[3]["finite_search_evidence"]["retained_modes"]) == 1
    # Refinement preserves the seed's original score record and its raw state.
    # Grouping the returned array by mode ID would lose the distant raw point.
    check_successful_union(case, 600.0)


def test_an_unprofiled_finite_point_does_not_borrow_the_leading_profile():
    case = bundle()
    shifted(case, 150.0, score=1.75)
    # The scope contains this evaluated point. Its unperformed profile remains
    # unbounded; no extra 100 m profile can be invented from the leading one.
    check_successful_union(case, 150.0)
