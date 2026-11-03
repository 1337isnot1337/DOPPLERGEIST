"""Logical decision controls only; no audio, search, truth or calibration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from aircraft_geoloc import confidence, matching


def control(count, *, same_association=False, discarded=False):
    events = [{"event_id": f"e{i}", "harmonic_group_id": f"g{i}",
               "start_s": i*100., "end_s": i*100.+20., "band_hz": [90., 200.],
               "quality": {"frequency_sigma_hz": 1.},
               "ridge": [{"time_s": i*100.+t, "frequency_hz": 140.-t}
                         for t in (0., 10., 20.)]} for i in range(count)]
    def candidate(selected):
        core = matching.association_score(
            {"score": 0., "event_scores": [0.]*len(selected)}, selected)
        return {"lat": 40., "lon": -100., "score": core["score"],
                "score_kind": core["score_kind"],
                "event_ids": [e["event_id"] for e in selected],
                "flight_ids": [f"f{i}" for i in range(len(selected))],
                "recording_start_utc": "2026-09-21T14:13:20Z",
                "uncertainty": {"radius_m": 50., "kind": "sensitivity",
                                "method": "controlled_full_profile"}}
    best = candidate(events)
    other = candidate(events if same_association else events[:-1])
    candidates = [best] if discarded else [best, other]
    identities = ["all-groups"] if discarded else ["all-groups", "other"]
    modes = [{"mode_id": key, "score": row["score"], "event_groups": len(row["event_ids"])}
             for key, row in zip(identities, candidates)]
    finite = {"schema_version": 1, "scope": "evaluated_finite_grid", "complete": True,
              "score_kind": best["score_kind"], "spacing_m": 2000., "refine_spacing_m": 100.,
              "max_event_groups": count, "retained_modes": modes,
              "discarded_count": int(discarded),
              "best_discarded_score": other["score"] if discarded else None,
              "pruning_accounted_for": True,
              "limitations": ["Controlled finite decision evidence; no measured recording."]}
    evidence = {"clock_locked": True, "alternatives_evaluated": False,
                "recording_start_window_s": [1790000000., 1790000000.],
                "unmatched_event_ids": [], "refinement_boundary_limited": False,
                "sensitivity": {"complete": True, "boundary_limited": False, "radius_m": 50.,
                                "sources": ["frequency", "clock", "altitude", "sound_speed"]},
                "finite_search_evidence": finite,
                "candidate_mode_ids": identities, "assessed_mode_ids": identities}
    for event in events:
        evidence[event["event_id"]] = {"rmse_hz": 0., "outlier_fraction": 0.,
                                       "support_fraction": 1., "drift_at_bound": False}
    coverage = {"search_complete": True, "data_status": "available", "limitations": []}
    before = deepcopy((events, candidates, coverage, evidence))
    decision = confidence.decide_location(events, candidates, coverage, matching_diagnostics=evidence)
    assert before == (events, candidates, coverage, evidence)
    return {"groups": count, "same_association": same_association, "discarded": discarded,
            "best_score": best["score"], "other_score": other["score"],
            "normalized_gap": (best["score"]-other["score"])/count,
            "best_association": dict(zip(best["event_ids"], best["flight_ids"])),
            "other_association": dict(zip(other["event_ids"], other["flight_ids"])),
            "status": decision["status"], "reason_code": decision["reason_code"],
            "diagnostics": decision["diagnostics"]}


if __name__ == "__main__":
    cases = [control(n) for n in (4, 5, 6)]
    cases += [control(6, same_association=True), control(6, discarded=True)]
    report = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "source_sha256": {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                for module in (matching, confidence)},
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "Abstract perfect-fit policy controls, not detection/search/real accuracy.",
              "cases": cases}
    with Path(sys.argv[1]).open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    for case in cases:
        print(case["groups"], case["same_association"], case["discarded"],
              case["normalized_gap"], case["status"], case["reason_code"])
