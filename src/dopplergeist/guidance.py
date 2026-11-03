"""Conservative next steps derived from a completed job's retained evidence.

This module does not alter the decision. Evidence paths refer to JSON fields in
existing job artifacts; absence of evidence means no corresponding suggestion.
"""


def guidance(result, decision=None):
    """Return unordered suggestions for evidence-supported next steps.

    ``decision`` is the optional decision.json object for this same job. Benefits
    of the suggestions are not measured or guaranteed.
    """
    if result.get("status") not in {"needs_input", "inconclusive"}:
        return []
    reason = result.get("reason_code")
    if not isinstance(decision, dict) or decision.get("status") != result["status"] or decision.get("reason_code") != reason:
        decision = None
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
        add("no_events", "No supported Doppler events were found.",
            "Try a longer portion of the original recording if available; another independent flyover may provide more evidence.",
            ["result.json#/reason_code", "result.json#/events"])
    elif reason == "insufficient_independent_events" and isinstance(decision, dict):
        diagnostics = decision.get("diagnostics", {})
        count = diagnostics.get("independent_event_groups")
        if type(count) is int and count >= 0:
            add("more_flyovers", f"The leading hypothesis has {count} independent flyover group(s); harmonics count once.",
                "Try more of the original recording if it contains another independent flyover.",
                ["result.json#/reason_code", "decision.json#/diagnostics/independent_event_groups"])
    elif reason in {"partial_flight_coverage", "missing_flight_data", "data_unavailable"}:
        coverage = result.get("coverage", {})
        if coverage.get("data_status") in {"partial", "unavailable"} and coverage.get("limitations"):
            add("missing_data", "The required historical data are incomplete or unavailable; see the coverage limitations.",
                "Ask the operator to restore the missing historical data before repeating the analysis.",
                ["result.json#/reason_code", "result.json#/coverage/data_status", "result.json#/coverage/limitations"])
    elif reason == "work_limit" and result.get("coverage", {}).get("search_complete") is False:
        add("work_limit", "The configured wall-time limit ended the analysis before it completed.",
            "The operator can allow more time and rerun the analysis; completion is not guaranteed.",
            ["result.json#/reason_code", "result.json#/coverage/search_complete"])
    elif reason in {"ambiguous_locations", "ambiguous_flight_match"} and isinstance(decision, dict):
        competitor = decision.get("diagnostics", {}).get("competing_hypothesis", {})
        separation = competitor.get("separation_m")
        if type(separation) in (int, float) and 0 <= separation < float("inf"):
            add("competing_hypotheses", f"A competing hypothesis is about {separation:.0f} m from the leading one.",
                "More of the original recording may contain another independent flyover that helps distinguish the alternatives.",
                ["result.json#/reason_code", "decision.json#/diagnostics/competing_hypothesis/separation_m"])
    return items
