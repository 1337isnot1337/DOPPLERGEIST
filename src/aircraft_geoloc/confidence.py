"""Conservative, uncalibrated evidence checks for the shared result contract.

Scores rank hypotheses; no score is interpreted as a probability. This module
never reads benchmark truth or changes event clocks/candidates. Detailed decision
diagnostics belong in a job artifact, outside the strict JobResult fields.
"""
from dataclasses import asdict, dataclass
import math

from pyproj import Geod

from .contracts import utc_timestamp, validate_result


@dataclass(frozen=True)
class DecisionPolicy:
    """Predeclared engineering limits, not fitted confidence calibration."""
    target_radius_m: float = 100.0
    min_independent_events: int = 2
    max_event_rmse_hz: float = 3.0
    max_outlier_fraction: float = 0.25
    min_support_fraction: float = 0.95
    near_tie_loss_per_event_hz: float = 0.5
    near_tie_support_per_group: float = 0.2

    def __post_init__(self):
        for name in ("target_radius_m", "max_event_rmse_hz", "near_tie_loss_per_event_hz", "near_tie_support_per_group"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if type(self.min_independent_events) is not int or self.min_independent_events < 2:
            raise ValueError("At least two independent events are required by this policy")
        for name in ("max_outlier_fraction", "min_support_fraction"):
            if not math.isfinite(getattr(self, name)) or not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must lie in [0, 1]")


def decide_location(events, candidates, coverage, *, matching_diagnostics=None, policy=None):
    """Return status/reason_code/message/diagnostics without modifying inputs.

    ``matching_diagnostics`` uses W3/W5's event-ID keys, plus clock_locked,
    refinement_boundary_limited, alternatives_evaluated and sensitivity.
    A known-clock single event requires recording_start_window_s and complete
    sensitivity across that whole input window (settings.clock_bounds_s). Partial
    associations explicitly enumerate original unmatched_event_ids; these remain
    unconfirmed acoustic proposals. Sensitivity must list tested
    sources: frequency, clock, altitude and sound_speed. An altitude-only profile
    cannot justify 100 m spatial precision. The orchestrator owns execution errors
    and missing recording-clock needs_input; malformed evidence is failed here.
    """
    policy = policy or DecisionPolicy()
    if not isinstance(policy, DecisionPolicy):
        raise TypeError("policy must be a DecisionPolicy")
    diagnostics = {"policy": asdict(policy), "policy_version": "engineering-v2",
                   "calibration": "uncalibrated", "probability": None,
                   "limitations": ["Archive availability does not establish capture of every aircraft.",
                                   "Sensitivity checks are not a calibrated confidence interval."]}

    def result(reason, message, status="inconclusive"):
        return {"status": status, "reason_code": reason, "message": message, "diagnostics": diagnostics}

    try:
        envelope = {"schema_version": 1, "job_id": "decision-validation", "status": "running",
                    "events": events, "candidates": candidates}
        if coverage is not None:
            envelope["coverage"] = coverage
        validated = validate_result(envelope)
    except (ValueError, TypeError, KeyError) as exc:
        diagnostics["validation_error"] = str(exc)
        return result("invalid_evidence", "The analysis produced malformed evidence.", "failed")
    events, candidates = validated["events"], validated["candidates"]
    evidence = matching_diagnostics or {}
    if not isinstance(evidence, dict):
        return result("invalid_evidence", "Matching diagnostics must be a mapping.", "failed")
    if not events:
        return result("no_doppler_events", "No supported Doppler event was discovered in the recording.")
    if coverage is None:
        return result("coverage_unknown", "Search completion and flight-data coverage are not established.")
    if coverage["data_status"] == "unavailable":
        return result("missing_flight_data", "Historical flight data are unavailable for this recording window.")
    if not coverage["search_complete"]:
        return result("search_incomplete", "The search did not finish the entire requested area and time window.")
    if coverage["data_status"] != "available" or coverage.get("missing_data"):
        return result("partial_flight_coverage", "Required flight or terrain data are missing from the searched scope.")
    if not candidates:
        return result("no_matching_flights", "No candidate flight association supports the discovered events.")

    best = candidates[0]
    lookup = {event["event_id"]: event for event in events}
    matched = [lookup[key] for key in best["event_ids"]]
    groups = {}
    for event, flight in zip(matched, best["flight_ids"]):
        key = event.get("harmonic_group_id", event["event_id"])
        if key in groups and groups[key][1] != flight:
            return result("inconsistent_harmonic_association", "Harmonics of one event map to different flight segments.")
        groups[key] = (event, flight)
    diagnostics["independent_event_groups"] = len(groups)
    sensitivity = evidence.get("sensitivity", {})
    window = evidence.get("recording_start_window_s")

    def interval(value):
        return (isinstance(value, (list, tuple)) and len(value) == 2 and
                all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in value)
                and value[0] <= value[1])

    if window is not None:
        if not interval(window):
            return result("invalid_evidence", "The trusted recording-start window must have two finite ordered endpoints.", "failed")
        fitted = utc_timestamp(best["recording_start_utc"]).timestamp()
        if not window[0] <= fitted <= window[1]:
            return result("recording_clock_mismatch", "The fitted recording start lies outside the trusted recording window.")
        diagnostics["recording_start_window_s"] = list(window)
    settings = sensitivity.get("settings", {}) if isinstance(sensitivity, dict) else {}
    tested_clock = settings.get("clock_bounds_s") if isinstance(settings, dict) else None
    known_clock = (interval(window) and interval(tested_clock) and
                   tested_clock[0] <= window[0] and tested_clock[1] >= window[1])
    diagnostics["known_clock_single_event"] = bool(len(groups) == 1 and known_clock)
    if len(groups) < policy.min_independent_events and not (len(groups) == 1 and
            policy.min_independent_events == 2 and known_clock):
        return result("insufficient_independent_events", "Too few independent flyovers constrain location; harmonics count once.")
    unmatched = set(lookup) - set(best["event_ids"])
    if unmatched:
        declared = evidence.get("unmatched_event_ids")
        if (best["score_kind"] != "matched_group_support_minus_normalized_residual" or
                not isinstance(declared, list) or not all(isinstance(key, str) for key in declared) or
                len(set(declared)) != len(declared) or set(declared) != unmatched):
            return result("unexplained_events", "Unmatched acoustic proposals need an explicit subset-association record.")
        if any(lookup[key].get("harmonic_group_id", key) in groups for key in unmatched):
            return result("incomplete_harmonic_group", "A matched flyover omits one of its measured harmonic ridges.")
    diagnostics["unmatched_event_ids"] = sorted(unmatched)
    diagnostics["unmatched_proposal_status"] = "unconfirmed acoustic proposals; not labelled aircraft misses"
    if evidence.get("clock_locked") is not True:
        return result("timing_not_established", "One shared recording clock has not been verified across all events.")
    for event, _ in groups.values():
        key = event["event_id"]
        fit = evidence.get(key)
        if not isinstance(fit, dict):
            return result("matching_diagnostics_missing", "Per-event residual and trajectory-support evidence is missing.")
        names = ("rmse_hz", "outlier_fraction", "support_fraction")
        values = [fit.get(name) for name in names]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            return result("matching_diagnostics_missing", "Per-event measurement diagnostics are incomplete or nonfinite.")
        rmse, outliers, support = values
        if rmse < 0 or not 0 <= outliers <= 1 or not 0 <= support <= 1:
            return result("invalid_evidence", "Per-event diagnostics contain impossible values.", "failed")
        if support < policy.min_support_fraction:
            return result("insufficient_track_support", "A flight trajectory does not cover enough of its observed event.")
        if rmse > policy.max_event_rmse_hz or outliers > policy.max_outlier_fraction:
            return result("inconsistent_event_match", "Residuals or outliers exceed the predeclared event-fit limits.")
        if fit.get("drift_at_bound") is not False:
            return result("source_drift_unresolved", "The source-frequency drift model is missing or reaches its allowed bound.")

    subset_scores = best["score_kind"] == "matched_group_support_minus_normalized_residual"
    if best["score_kind"] != "negative_robust_ridge_loss_hz" and not subset_scores:
        return result("unsupported_score_kind", "This ranking score has no declared ambiguity threshold in the decision policy.")
    # Alternatives must fit inside the envelope around the returned point.
    # Two overlapping target-radius circles do not establish that containment.
    ambiguity_radius_m = min(policy.target_radius_m,
                             best.get("uncertainty", {}).get("radius_m", policy.target_radius_m))
    for alternative in candidates[1:]:
        # Raw losses require equal event sets; subset support has declared units.
        if not subset_scores and set(alternative["event_ids"]) != set(best["event_ids"]):
            return result("incomparable_candidates", "Competing candidates do not explain the same event set.")
        separation = abs(Geod(ellps="WGS84").inv(best["lon"], best["lat"], alternative["lon"], alternative["lat"])[2])
        same_flights = dict(zip(best["event_ids"], best["flight_ids"])) == dict(zip(alternative["event_ids"], alternative["flight_ids"]))
        alternative_groups = {lookup[key].get("harmonic_group_id", key) for key in alternative["event_ids"]}
        gap = (best["score"] - alternative["score"]) / max(len(groups), len(alternative_groups))
        threshold = policy.near_tie_support_per_group if subset_scores else policy.near_tie_loss_per_event_hz
        units = "support_units_per_group" if subset_scores else "loss_hz_per_group"
        if (separation > ambiguity_radius_m or not same_flights) and gap <= threshold:
            diagnostics["competing_hypothesis"] = {"separation_m": separation, "score_gap": gap, "gap_units": units,
                                                   "same_flight_association": same_flights, "checked_radius_m": ambiguity_radius_m}
            return result("ambiguous_locations" if separation > ambiguity_radius_m else "ambiguous_flight_match",
                          "Competing hypotheses fit nearly as well; no unique precise location is supported.")
    if evidence.get("alternatives_evaluated") is not True:
        return result("alternatives_not_assessed", "The retained competing hypotheses have not all been assessed.")
    sensitivity = evidence.get("sensitivity", {})
    if not isinstance(sensitivity, dict):
        return result("uncertainty_not_established", "Measurement and model sensitivity are not established.")
    required = {"frequency", "clock", "altitude", "sound_speed"}
    sources = sensitivity.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(x, str) for x in sources):
        return result("invalid_evidence", "Sensitivity source names must be a list of strings.", "failed")
    diagnostics["sensitivity_sources"] = sources
    if not required <= set(sources) or sensitivity.get("complete") is not True:
        return result("uncertainty_not_established", "Full ridge, clock, altitude and sound-speed sensitivity has not been tested.")
    if sensitivity.get("boundary_limited") is not False or evidence.get("refinement_boundary_limited") is not False:
        return result("refinement_boundary_limited", "Refinement or sensitivity reaches a search boundary.")
    uncertainty = best.get("uncertainty")
    if uncertainty is None:
        return result("uncertainty_not_established", "The leading candidate has no supported spatial sensitivity estimate.")
    if uncertainty["kind"] != "sensitivity":
        return result("calibration_not_verified", "This policy has no independent evidence verifying the candidate's calibration claim.")
    radius = sensitivity.get("radius_m")
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius < 0:
        return result("uncertainty_not_established", "The full perturbation envelope has no valid spatial radius.")
    if uncertainty["radius_m"] < radius:
        return result("uncertainty_not_established", "The candidate radius does not cover the tested perturbation envelope.")
    diagnostics["radius_m"] = uncertainty["radius_m"]
    if uncertainty["radius_m"] > policy.target_radius_m:
        return result("location_uncertainty_too_large", "Spatial sensitivity exceeds the declared precision target.")
    return result("supported_by_evidence_checks", "Location passes the declared evidence checks; its sensitivity remains uncalibrated.", "succeeded")
