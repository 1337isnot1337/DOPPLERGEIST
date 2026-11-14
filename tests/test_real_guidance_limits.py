"""Guidance wiring from recorded ridges; no audio, tracks or location fits generated."""
import copy
import gzip
import json
from pathlib import Path

import pytest

from dopplergeist.confidence import _screen_harmonic_overlap
from dopplergeist.guidance import explain_job, guidance


ROOT = Path(__file__).resolve().parents[1]
SAVED_JOB = ROOT / "evidence/verification/local-integration-20261103/installed-wheel-needs-clock"
UNRECONCILED_JOB = ROOT / "tests/fixtures/real_unreconciled_guidance_result.json.gz"


def real_unreconciled_result():
    with gzip.open(UNRECONCILED_JOB, "rt") as stream:
        return json.load(stream)


def test_completed_nonjet_job_explains_acoustic_preparation_limit():
    result = real_unreconciled_result()
    original = copy.deepcopy(result)
    assert result["status"] == "inconclusive" and len(result["events"]) == 27
    items = guidance(result)
    assert [item["code"] for item in items] == ["acoustic_preparation"]
    assert items[0]["benefit"] == "unmeasured"
    for reference in items[0]["evidence"]:
        assert resolve({"result.json": result}, reference)
    assert result == original


@pytest.mark.parametrize("missing", ["events", "limitations"])
def test_preparation_advice_requires_saved_observations_and_error(missing):
    result = real_unreconciled_result()
    if missing == "events":
        result.pop("events")
    else:
        result["coverage"].pop("limitations")
    assert guidance(result) == []


def test_real_preparation_explanation_preserves_stored_result(tmp_path):
    with gzip.open(UNRECONCILED_JOB, "rb") as stream:
        original = stream.read()
    path = tmp_path / "result.json"
    path.write_bytes(original)
    result = json.loads(original)
    explanation = explain_job(tmp_path)
    assert explanation["status"] == result["status"]
    assert explanation["reason_code"] == result["reason_code"]
    assert explanation["ranked"] is False
    assert [item["code"] for item in explanation["items"]] == ["acoustic_preparation"]
    assert path.read_bytes() == original


def resolve(documents, reference):
    artifact, pointer = reference.split("#", 1)
    value = documents[artifact]
    for token in pointer.lstrip("/").split("/"):
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def overlap_case():
    recorded = json.loads((ROOT / "tests/data/shared-ridges-real.json").read_text())
    screen = _screen_harmonic_overlap(recorded["shared"]["events"], pair_budget=0)
    # Candidate identity is irrelevant to this advice. Use a presence sentinel
    # for the decision/result match guard rather than inventing a location.
    result = {"status": "inconclusive", "reason_code": "insufficient_independent_events",
              "candidates": [None]}
    decision = dict(result, diagnostics={"independent_event_groups": None,
                    "matched_group_overlap_assessment": screen["assessment"]})
    return result, decision


def test_recorded_ridge_budget_limit_is_not_reported_as_too_few_flyovers():
    result, decision = overlap_case()
    original = copy.deepcopy((result, decision))
    items = guidance(result, decision)
    assert [item["code"] for item in items] == ["event_assessment_limit"]
    assert "0 acoustic-group pair(s)" in items[0]["observation"]
    assert items[0]["benefit"] == "unmeasured"
    assert "not been shown" in items[0]["suggestion"]
    documents = {"result.json": result, "decision.json": decision}
    for reference in items[0]["evidence"]:
        resolve(documents, reference)
    assert (result, decision) == original
    assert guidance(result, dict(decision, candidates=[])) == []


@pytest.mark.parametrize("change", [
    {"conclusive": True}, {"exhaustive": True}, {"pairs_examined": True},
    {"pair_budget": -1}, {"pairs_examined": 1}, {"pair_budget": None},
])
def test_incomplete_or_contradictory_counters_do_not_justify_budget_advice(change):
    result, decision = overlap_case()
    decision["diagnostics"]["matched_group_overlap_assessment"].update(change)
    assert guidance(result, decision) == []


def test_saved_real_missing_clock_job_keeps_its_original_guidance():
    original = (SAVED_JOB / "result.json").read_bytes()
    advice = explain_job(SAVED_JOB)
    assert [item["code"] for item in advice["items"]] == ["recording_time"]
    assert (SAVED_JOB / "result.json").read_bytes() == original


def test_review_exclusions_are_distinct_from_failed_discovery(tmp_path):
    # Exercise the product review state by excluding the actual saved proposals;
    # their measured values are untouched and no search or detector is run.
    original = (SAVED_JOB / "result.json").read_bytes()
    result = json.loads(original)
    result["review"] = {"user_assisted": True,
                        "excluded_event_ids": [event["event_id"] for event in result["events"]],
                        "source_job_id": result["job_id"]}
    result["events"] = []
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result))
    before = path.read_bytes()
    advice = explain_job(tmp_path)
    assert [item["code"] for item in advice["items"]] == ["recording_time", "excluded_events"]
    assert advice["ranked"] is False
    for item in advice["items"]:
        for reference in item["evidence"]:
            resolve({"result.json": result}, reference)
    assert path.read_bytes() == before
    assert (SAVED_JOB / "result.json").read_bytes() == original


def test_empty_real_review_state_without_exclusions_still_reports_no_events():
    result = json.loads((SAVED_JOB / "result.json").read_text())
    result["events"] = []
    assert [item["code"] for item in guidance(result)] == ["recording_time", "no_events"]
