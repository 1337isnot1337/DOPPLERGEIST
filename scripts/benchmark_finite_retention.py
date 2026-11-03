"""Measure disk retention accounting against an analytic unpruned reference.

This exercises retention only, with invented scored seeds and no aircraft/audio
truth. It does not measure candidate discovery, localization or confidence.
"""
import argparse
import json
from pathlib import Path
import platform
import time

from aircraft_geoloc.data_access import content_hash, sha256, write_json
from aircraft_geoloc.finite_search import RetentionLedger
from aircraft_geoloc.tiled_search import merge_candidates


def memory_mib(field):
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1]) / 1024
    raise RuntimeError(f"No Linux process-memory field {field}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--modes", type=int, default=131072)
    parser.add_argument("--stage-size", type=int, default=1024)
    parser.add_argument("--top-k", type=int, default=100)
    args = parser.parse_args()
    if not 0 < args.top_k < args.modes or args.stage_size < 1:
        parser.error("Require 0 < top-k < modes and a positive stage size")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    inputs = {"modes": args.modes, "stage_size": args.stage_size, "top_k": args.top_k,
              "code": {str(p.relative_to(root)): sha256(p) for p in [Path(__file__).resolve(),
                       root / "src/aircraft_geoloc/finite_search.py", root / "src/aircraft_geoloc/tiled_search.py"]}}
    kind = "matched_group_support_minus_normalized_residual"
    ledger = RetentionLedger(output / "retention.sqlite", content_hash(inputs), kind)
    began, baseline, kept, stages = time.monotonic(), memory_mib("VmRSS"), [], 0
    for first in range(0, args.modes, args.stage_size):
        rows = [{"x": float(i), "y": 0., "lat": 40., "lon": -100., "elev_m": 0.,
                 "recording_start_time_s": 100., "event_indices": [0, 1, 2, 3],
                 "flight_ids": ["a", "b", "c", "d"], "pass_emission_times_s": [110., 150., 190., 230.],
                 "score": i / args.modes, "score_kind": kind}
                for i in range(first, min(args.modes, first + args.stage_size))]
        # Repeat an identical seed: duplicate observations are not alternatives.
        rows.append(dict(rows[-1]))
        local = merge_candidates(rows, args.top_k, ledger=ledger, stage=f"coarse:{first}")
        kept = merge_candidates(kept + local, args.top_k, ledger=ledger, stage=f"global:{first}")
        stages += 1
    evidence = ledger.evidence(kept, complete=True, spacing_m=1000, refine_spacing_m=100,
                               max_event_groups=4, expected_stages={"coarse": stages, "global": stages})
    expected_bound = (args.modes - args.top_k - 1) / args.modes
    assert evidence["complete"] and evidence["pruning_accounted_for"]
    assert evidence["evaluated_modes"] == args.modes
    assert evidence["discarded_count"] == args.modes - args.top_k
    assert evidence["best_discarded_score"] == expected_bound
    assert [r["x"] for r in kept] == list(range(args.modes-1, args.modes-args.top_k-1, -1))
    assert evidence["stages"]["coarse"]["exact_duplicates"] == stages
    report = {"scope": "Invented scored-seed retention fixture; no audio/flight localization claim",
              "inputs": inputs, "python": platform.python_version(), "elapsed_s": time.monotonic()-began,
              "baseline_rss_mib": baseline, "current_rss_mib": memory_mib("VmRSS"),
              "process_high_water_rss_mib": memory_mib("VmHWM"),
              "ledger_bytes": ledger.path.stat().st_size, "ledger_sha256": sha256(ledger.path),
              "expected_discarded_score": expected_bound, "reference_checks_passed": True,
              "finite_search_evidence": evidence}
    write_json(output / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "finite_search_evidence"}, indent=2))


if __name__ == "__main__":
    main()
