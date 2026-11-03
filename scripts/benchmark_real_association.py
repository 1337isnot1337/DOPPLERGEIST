"""Compare association traversal with a Git revision on an observed CPA fixture.

Use the real JSON fixture accepted by benchmark_real_clock_batch.py. No audio,
flight observations or proposal measurements are generated. This measures the
join, not whole-search runtime or localization accuracy.
"""
import argparse
import gc
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import ModuleType

import numpy as np
import pandas as pd

from dopplergeist.matching import association_candidates, prepare_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path, help="New JSON output file")
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new output file")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(
        ["git", "show", f"{args.baseline_ref}:src/dopplergeist/matching.py"],
        cwd=root, text=True)
    baseline = ModuleType("dopplergeist._association_reference")
    baseline.__package__ = "dopplergeist"
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, "<baseline matching.py>", "exec"), baseline.__dict__)
    fixture = json.loads(args.fixture.read_text())
    # Archived CPA fixtures contain either original discovery records or their
    # already prepared association settings. Preserve both observed formats.
    recorded_events = fixture["events"]
    if recorded_events and "ridge" in recorded_events[0]:
        events, _ = prepare_events(recorded_events)
    else:
        events = recorded_events
    table = pd.DataFrame(fixture["cpa_rows"])
    reference, counts = baseline.association_candidates(table, events)
    if not reference:
        raise ValueError("Fixture must have real association hypotheses")
    first = reference[0]
    clock = sum(first["recording_start_bounds_s"])/2
    anchor = first["passes"][0]["receive_time"] - events[first["event_indices"][0]]["cpa_receive_s"]
    cases = [
        ("all_events", table, events, {}),
        ("minimum_two", table, events, {"min_events": 2}),
        ("minimum_four", table, events, {"min_events": 4}),
        ("explicit_cap_one", table, events, {"max_events": 1}),
        ("explicit_cap_two", table, events, {"max_events": 2}),
        ("fixed_clock", table, events, {"time_origin": clock, "time_tolerance_s": 0}),
        ("clock_boundary", table, events, {"time_origin": first["recording_start_bounds_s"][0],
                                            "time_tolerance_s": 0}),
        ("anchor_exact_start", table, events,
         {"anchor_window": [anchor, float(np.nextafter(anchor, np.inf))]}),
        ("anchor_excludes_start", table, events,
         {"anchor_window": [float(np.nextafter(anchor, -np.inf)), anchor]}),
        ("silence", table, events, {"silence": {"edge_margin_s": 60}}),
        ("silence_no_margin", table, events, {"silence": {"edge_margin_s": 0}}),
        ("candidate_budget_one", table, events, {"max_candidates": 1}),
        ("candidate_budget_hundred", table, events, {"max_candidates": 100}),
        ("no_observations", table.iloc[:0], events, {}),
        ("last_proposal", table, events[-1:], {}),
    ]

    def outcome(function, observed, proposals, settings):
        try:
            return {"result": function(observed, proposals, **settings)}
        except ValueError as error:
            return {"error": str(error)}

    checks = []
    for name, observed, proposals, settings in cases:
        expected = outcome(baseline.association_candidates, observed, proposals, settings)
        actual = outcome(association_candidates, observed, proposals, settings)
        if actual != expected:
            raise AssertionError(f"Candidate order, bounds, counts or error differ: {name}")
        check = {"case": name, "exact_parity": True}
        if "error" in actual:
            check["error"] = actual["error"]
        else:
            check["counts"] = actual["result"][1]
        checks.append(check)
        print(f"Parity passed: {name}", flush=True)
    runs = []
    functions = {"baseline": baseline.association_candidates, "optimized": association_candidates}
    for repeat in range(args.repetitions):
        order = ("baseline", "optimized") if repeat % 2 == 0 else ("optimized", "baseline")
        for name in order:
            # Release the previous result and begin each measured call at the
            # same garbage-collector state. Otherwise a prior run can choose
            # which arm pays for collecting thousands of candidate objects.
            actual = None
            gc.collect()
            wall, cpu = time.perf_counter(), time.process_time()
            actual = functions[name](table, events)
            run = {"implementation": name, "cpu_s": time.process_time()-cpu,
                   "wall_s": time.perf_counter()-wall}
            if actual != (reference, counts):
                raise AssertionError(f"Timing replay differed: {name}")
            runs.append(run)
            print(json.dumps(run), flush=True)
    medians = {name: statistics.median(r["cpu_s"] for r in runs if r["implementation"] == name)
               for name in functions}
    report = {"fixture": str(args.fixture), "baseline_ref": args.baseline_ref,
              "garbage_collection_reset_before_each_run": True,
              "events": len(events), "cpa_rows": len(table), "candidates": len(reference),
              "exact_candidate_order_and_work_accounting": True, "checks": checks, "runs": runs,
              "median_cpu_s": medians, "cpu_speedup": medians["baseline"]/medians["optimized"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({"median_cpu_s": medians, "cpu_speedup": report["cpu_speedup"]}))


if __name__ == "__main__":
    main()
