"""Decision diagnostics regression using frozen real-recording outputs."""
import json
from pathlib import Path

import pytest

from dopplergeist.confidence import decide_location


DATA = Path(__file__).parent / "data"
CASES = (
    ("real-eclipse-rochester-decision.json", "search_incomplete", 1, 6),
    ("real-eclipse-fort-worth-decision.json", "source_drift_unresolved", 3, 5),
    ("real-eclipse-east-texas-decision.json", "search_incomplete", 2, 6),
)


@pytest.mark.parametrize(("filename", "reason_code", "matched_group_count", "total_group_count"), CASES)
def test_real_saved_results_keep_ranked_candidate_diagnostics(
        filename, reason_code, matched_group_count, total_group_count):
    saved = json.loads((DATA / filename).read_text())
    result = decide_location(
        saved["events"], [saved["candidate"]], saved["coverage"],
        matching_diagnostics=saved["matching_diagnostics"],
    )

    assert result["status"] == saved["expected_status"] == "inconclusive"
    assert result["reason_code"] == saved["expected_reason_code"] == reason_code
    summary = result["diagnostics"]["candidate_evidence_summary"]
    candidate = saved["candidate"]
    event_lookup = {event["event_id"]: event for event in saved["events"]}
    matched_groups = {event_lookup[event_id].get("harmonic_group_id", event_id)
                      for event_id in candidate["event_ids"]}
    all_groups = {event.get("harmonic_group_id", event["event_id"])
                  for event in saved["events"]}

    assert summary["matched_event_ids"] == sorted(candidate["event_ids"])
    assert summary["matched_group_ids"] == sorted(matched_groups)
    assert summary["unmatched_group_ids"] == sorted(all_groups - matched_groups)
    assert summary["matched_group_count"] == matched_group_count
    assert summary["total_group_count"] == total_group_count
    assert summary["matched_group_fraction"] == matched_group_count / total_group_count
    assert summary["unmatched_event_ids"]
    assert {fit["event_id"] for fit in summary["event_fits"]} == set(candidate["event_ids"])
    assert all("drift_at_bound" in fit for fit in summary["event_fits"])

    if "fort-worth" in filename:
        assert summary["distinct_flight_segments"] == 2
        assert len(summary["flight_segments_with_multiple_groups"]) == 1
        assert all(fit["drift_at_bound"] for fit in summary["event_fits"][:2])
    elif "rochester" in filename:
        assert summary["distinct_flight_segments"] == 1
        assert len(summary["matched_group_ids"]) == 1
    else:
        assert summary["distinct_flight_segments"] == 2
