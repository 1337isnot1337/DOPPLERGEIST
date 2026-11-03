"""Independently check saved six-event records without executing a decision."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re

from pyproj import Geod


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    hashes = {}

    def read(name):
        data = (args.evidence / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    result = read("terminal-result.json")
    decision = read("terminal-decision.json")
    search = read("terminal-search-search-report.json")
    run = read("terminal-run-receipt.json")
    labels = read("postrun-truth.json")
    published = read("postrun-evaluation.json")
    access = read("postrun-truth-access-receipt.json")
    request = read("terminal-request.json")
    assert result["candidates"] == decision["candidates"]
    assert result["status"] == decision["status"] == published["pipeline_status"] == "inconclusive"
    assert result["reason_code"] == decision["reason_code"] == published["reason_code"] == "ambiguous_locations"
    assert published["accepted_location_returned"] is False
    assert published["accepted_location_error_m"] is None
    assert published["full_job_peak_rss_mib"] is None
    assert "finite_search_evidence" not in search
    assert search["alternative_modes_exhaustively_assessed"] is False
    assert search["tiles_completed"] == search["tiles_total"] == 76328
    assert search["unsearched_tiles"] == 0 and search["tile_failures"] == []
    assert search["refinement_failure"] is None
    assert search["all_event_groups_considered"] and search["event_limit_reason"] is None
    assert datetime.fromisoformat(access["truth_opened_utc"]) > datetime.fromisoformat(run["finished_utc"])
    assert hashes["postrun-truth.json"] == access["truth_sha256"]

    def overlap(a, b):
        intersection = max(0., min(a[1], b[1]) - max(a[0], b[0]))
        union = (a[1] - a[0]) + (b[1] - b[0]) - intersection
        return intersection / union if union else 0.

    events = result["events"]
    assert len(events) == len(labels["events"]) == 6
    joined = []
    for event in events:
        scores = [overlap((event["start_s"], event["end_s"]),
                          (truth["start_s"], truth["end_s"])) for truth in labels["events"]]
        target = max(range(len(scores)), key=scores.__getitem__)
        joined.append({"event_id": event["event_id"], "truth_event_index": target,
                       "true_flight_id": labels["events"][target]["flight_id"], "interval_iou": scores[target]})
    assert len({j["truth_event_index"] for j in joined}) == 6
    for actual, expected in zip(joined, published["event_truth_join"], strict=True):
        assert all(actual[k] == expected[k] for k in ("event_id", "truth_event_index", "true_flight_id"))
        assert math.isclose(actual["interval_iou"], expected["interval_iou"], abs_tol=1e-12)
    truth_by_event = {j["event_id"]: j["true_flight_id"] for j in joined}
    groups_by_event = {e["event_id"]: e.get("harmonic_group_id", e["event_id"]) for e in events}
    geod = Geod(ellps="WGS84")
    latitude, longitude = labels["location"]
    epoch = datetime.fromisoformat(labels["recording_start_utc"].replace("Z", "+00:00")).timestamp()
    stage_summaries = {}
    all_errors = {}
    for stage, rows, expected_rows in [
        ("product", result["candidates"], published["all_product_candidates"]),
        ("fine", search["ranked"], published["all_search_candidates"]),
        ("coarse", search["coarse_ranked"], published["all_coarse_candidates"]),
    ]:
        errors, counts, correct_count = [], Counter(), 0
        for index, (row, expected) in enumerate(zip(rows, expected_rows, strict=True)):
            error = abs(geod.inv(longitude, latitude, row["lon"], row["lat"])[2])
            assert math.isclose(error, expected["point_error_m"], rel_tol=0., abs_tol=1e-7)
            event_ids = row.get("event_ids") or [events[i]["event_id"] for i in row["event_indices"]]
            assert event_ids == expected["event_ids"]
            correct = [flight == truth_by_event[event] for event, flight in zip(event_ids, row["flight_ids"], strict=True)]
            assert correct == expected["correct_flight_associations"]
            assert all(correct) == expected["all_reported_associations_correct"]
            correct_count += int(all(correct))
            if stage == "product":
                assert all(correct)
            count = len({groups_by_event[e] for e in event_ids})
            assert count == expected["matched_groups"]
            clock = (datetime.fromisoformat(row["recording_start_utc"].replace("Z", "+00:00")).timestamp()
                     if "recording_start_utc" in row else row["recording_start_time_s"])
            assert clock - epoch == expected["clock_offset_from_supplied_truth_s"] == 0.
            assert row["score"] == expected["score"]
            assert expected["rank"] == index + 1
            for threshold in (100, 500, 1000):
                assert (error <= threshold) == expected["point_within_m"][str(threshold)]
            errors.append(error)
            counts[count] += 1
        stage_summaries[stage] = {"records": len(rows), "leading_point_error_m": errors[0],
            "minimum_point_error_m": min(errors), "maximum_point_error_m": max(errors),
            "group_count_histogram": dict(sorted(counts.items())),
            "point_counts_within_m": {str(t): sum(e <= t for e in errors) for t in (100, 500, 1000)},
            "all_reported_associations_correct": correct_count == len(rows),
            "correct_association_records": correct_count,
            "incorrect_association_records": len(rows) - correct_count,
            "all_clocks_match_supplied_epoch": True}
        all_errors[stage] = errors
    actual_records = sum(s["records"] for s in stage_summaries.values())
    document = (args.evidence / "SIX_EVENT_RESULT.md").read_bytes()
    hashes["SIX_EVENT_RESULT.md"] = hashlib.sha256(document).hexdigest()
    count_match = re.search(r"all\s+(\d+)\s+retained product/fine/coarse candidate", document.decode())
    documented_records = int(count_match.group(1)) if count_match else None

    best = result["candidates"][0]
    radius = best["uncertainty"]["radius_m"]
    competitor = decision["diagnostics"]["competing_hypothesis"]
    matched = []
    for i, row in enumerate(result["candidates"][1:], 1):
        distance = abs(geod.inv(best["lon"], best["lat"], row["lon"], row["lat"])[2])
        count = max(len({groups_by_event[e] for e in best["event_ids"]}),
                    len({groups_by_event[e] for e in row["event_ids"]}))
        gap = (best["score"] - row["score"]) / count
        if math.isclose(distance, competitor["separation_m"], abs_tol=1e-7) and math.isclose(gap, competitor["score_gap"], abs_tol=1e-12):
            matched.append(i)
    assert matched and competitor["same_flight_association"] is True
    assert competitor["checked_radius_m"] == radius
    output = {"scope": "Passive independent recomputation of saved candidate points and joins; no scientific or decision rerun",
        "evidence_commit": "0ea65162092f854ad0f872133ae12b83a127edea",
        "runtime_source_commit": run["runtime_manifest"]["git_commit"], "pyproj_version": version("pyproj"),
        "original_status": result["status"], "original_reason_code": result["reason_code"],
        "accepted_localization_at_threshold_m": {str(t): False for t in (100, 500, 1000)},
        "event_truth_join": joined, "stages": stage_summaries,
        "native_records_verified": actual_records,
        "documented_record_count": documented_records,
        "documentation_count_matches_native": documented_records == actual_records,
        "saved_competitor_matching_indices": matched, "saved_competing_hypothesis": competitor,
        "search_stage_peak_rss_mib": search["process_peak_rss_mib"], "full_job_peak_rss_mib": None,
        "truth_access_after_terminal": True, "used_file_sha256": hashes,
        "limitations": ["Finite synthetic population with a supplied exact clock, not independent real national validation.",
                        "Coarse tile payloads require a separate archive audit; summary counts alone do not verify them.",
                        "Recorded runtime isolation is not an experimenter-blind holdout."]}
    args.output.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": output["original_status"], "stages": stage_summaries}, indent=2))


if __name__ == "__main__":
    main()
