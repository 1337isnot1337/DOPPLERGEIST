"""Read-only next steps derived from a completed job's retained evidence.

Evidence references are artifact-relative JSON pointers. No recommendation changes
the decision or claims a measured benefit. Missing diagnostics suppress advice.
"""
import json
import math
from pathlib import Path

from .contracts import validate_result


def guidance(result, decision=None):
    """Return unordered, conditional suggestions without modifying either input."""
    if result.get("status") not in {"needs_input", "inconclusive", "failed"}:
        return []
    reason = result.get("reason_code")
    # A saved decision from a different result (for example, before a resume)
    # must not supply the current result's observations.
    if (not isinstance(decision, dict)
            or decision.get("status") != result["status"]
            or decision.get("reason_code") != reason
            or not result.get("candidates")
            or decision.get("candidates") != result["candidates"]):
        decision = {}
    diagnostics = decision.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    coverage = result.get("coverage", {})
    items = []

    def add(code, observation, suggestion, evidence):
        items.append({"code": code, "observation": observation,
                      "suggestion": suggestion, "evidence": evidence,
                      "benefit": "unmeasured"})

    if reason == "recording_time_required" and "time_window" in result.get("required_fields", []):
        add("recording_time", "The recording start time is not established.",
            "Provide a defensible UTC window for the start of the original recording, then run the analysis again.",
            ["result.json#/reason_code", "result.json#/required_fields"])

    if reason in {"recording_time_required", "no_supported_events", "no_doppler_events"} and result.get("events") == []:
        add("no_events", "No supported Doppler events were found in this recording.",
            "If available, try more of the original recording. It may contain another usable event; this has not been assessed.",
            ["result.json#/reason_code", "result.json#/events"])

    if reason == "insufficient_independent_events":
        overlap = diagnostics.get("possible_harmonic_overlap")
        count = diagnostics.get("independent_event_groups")
        if (isinstance(overlap, dict) and overlap and count is None
                and "independent_event_groups" in diagnostics):
            add("event_independence", "The matched acoustic groups may share one flyover; their independence is not established.",
                "Inspect the overlapping ridges. More of the original recording may contain a separate flyover, but improvement is unmeasured.",
                ["result.json#/reason_code", "decision.json#/diagnostics/possible_harmonic_overlap",
                 "decision.json#/diagnostics/independent_event_groups"])
        elif type(count) is int and count >= 0:
            add("more_events", f"The leading hypothesis has {count} matched acoustic group(s), below the decision's event requirement.",
                "If available, try more of the original recording containing a separate flyover. Another usable event is not guaranteed.",
                ["result.json#/reason_code", "decision.json#/diagnostics/independent_event_groups"])

    # Coverage and the primary reason can describe different simultaneous limits.
    # The initial unavailable state, before acquisition, is not an archive gap.
    missing = coverage.get("missing_data", [])
    data_problem = coverage.get("data_status") == "partial" or bool(missing)
    if data_problem and (coverage.get("limitations") or missing):
        evidence = ["result.json#/coverage/data_status"]
        if coverage.get("limitations"):
            evidence.append("result.json#/coverage/limitations")
        if missing:
            evidence.append("result.json#/coverage/missing_data")
        add("missing_data", "Required flight or terrain data are incomplete or unavailable; the coverage report identifies the limits.",
            "Ask the operator to restore the missing data before repeating the analysis. Downloaded archives do not guarantee receiver coverage.",
            evidence)
    elif (reason in {"missing_flight_data", "data_unavailable"}
          and coverage.get("data_status") == "unavailable" and coverage.get("limitations")):
        # The automatic producer also uses data_unavailable for acquisition
        # budgets and invalid provider settings. This is not proof of a gap.
        add("data_access_limit", "Required data could not be obtained or assessed; the coverage report records the limiting condition.",
            "Ask the operator to inspect the recorded data-access or configuration limit before repeating the analysis.",
            ["result.json#/reason_code", "result.json#/coverage/data_status", "result.json#/coverage/limitations"])

    if reason == "work_limit" and coverage.get("search_complete") is not True:
        evidence = ["result.json#/reason_code"]
        if coverage.get("search_complete") is False:
            evidence.append("result.json#/coverage/search_complete")
        add("work_limit", "The configured wall-time limit ended the analysis before completion.",
            "Ask the operator to allow more time. If a compatible saved checkpoint exists, resume it. Otherwise, run the analysis again. Completion is not guaranteed.",
            evidence)
    elif reason == "search_incomplete" and coverage.get("search_complete") is False:
        add("incomplete_assessment", "Search coverage or assessment of competing hypotheses is incomplete.",
            "Ask the operator to inspect unfinished work and unsupported model assessments. More runtime alone may not address these limits.",
            ["result.json#/reason_code", "result.json#/coverage/search_complete"])
    elif (reason == "finite_search_incomplete" and coverage.get("search_complete") is True
          and isinstance(diagnostics.get("finite_search"), dict)):
        # Completed tile coverage is distinct from assessment of every retained
        # or discarded competitor. The decision checks these separately.
        add("incomplete_assessment", "Assessment of competing hypotheses is incomplete, even though the requested search scope was processed.",
            "Ask the operator to inspect unassessed hypotheses and unsupported model assessments. More runtime alone may not address these limits.",
            ["result.json#/reason_code", "result.json#/coverage/search_complete",
             "decision.json#/diagnostics/finite_search"])

    if reason in {"ambiguous_locations", "ambiguous_flight_match"}:
        competitor = diagnostics.get("competing_hypothesis", {})
        if isinstance(competitor, dict):
            separation = competitor.get("separation_m")
            if type(separation) in (int, float) and math.isfinite(separation) and separation >= 0:
                observation = f"A competing hypothesis is about {separation:.0f} m from the leading one."
                evidence = ["result.json#/reason_code", "decision.json#/diagnostics/competing_hypothesis/separation_m"]
                if competitor.get("same_flight_association") is False:
                    observation += " It assigns the acoustic events to different flight segments."
                    evidence.append("decision.json#/diagnostics/competing_hypothesis/same_flight_association")
                add("competing_hypotheses", observation,
                    "Inspect both alternatives. Whether a narrower recording-start window or more audio separates them has not been assessed.",
                    evidence)
    return items


def explain_job(job_dir):
    """Read an existing job; return an additive API envelope without writing it."""
    directory = Path(job_dir)
    result = validate_result(json.loads((directory / "result.json").read_text()))
    decision = None
    limitations = ["Suggestions are not ranked. Their benefit has not been measured; they do not change the job's decision."]
    try:
        decision = json.loads((directory / "decision.json").read_text())
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        limitations.append("The saved decision could not be read; suggestions requiring its diagnostics are omitted.")
    return {"schema_version": 1, "job_id": result["job_id"], "status": result["status"],
            "reason_code": result.get("reason_code"), "ranked": False,
            "items": guidance(result, decision), "limitations": limitations}
