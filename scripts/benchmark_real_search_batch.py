"""Replay the two recorded scoring workloads with complete source isolation.

Each revision runs in a separate interpreter. Exact candidate, accounting and
retention-ledger equality is required before reporting a speedup. The shared
fixture contains measured ridges once; aircraft come from the restored real
index. Receiver settings are development hypotheses, not independent truth.

Use --prepare-only to check the restored inputs without running a benchmark.
The final report is OUTPUT/runs/comparison.json. Input loading is not timed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    # This import is used only to freeze the observed query inventory. Both
    # scoring revisions are loaded by the existing isolated-process worker.
    sys.path.insert(0, str(args.current_source.resolve()))
    import dopplergeist
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.matching import prepare_events
    from dopplergeist.tiled_search import SearchBudget

    if Path(dopplergeist.__file__).resolve().parent != args.current_source.resolve() / "dopplergeist":
        raise RuntimeError("Preparation imported a different source tree")
    shared = json.loads(args.fixture.read_text())
    if args.case not in shared["cases"]:
        raise ValueError(f"Unknown recorded workload: {args.case}")
    selected = shared["cases"][args.case]
    index = FlightIndex(args.index)
    if index.report["coverage"] != shared["index_coverage"]:
        raise ValueError("The restored index has different coverage declarations")
    identity = shared["index_identity"]
    for key, expected in identity.items():
        actual = index.report[key]
        if key == "sources":
            # File locations may change after a clean checkout. Content and
            # normalization settings must still identify the same real inputs.
            actual = [{k: source[k] for k in ("sha256", "bytes")} for source in actual]
        if actual != expected:
            raise ValueError(f"The restored trajectory index has a different {key}")
    budget = SearchBudget(**shared["budget"])
    tracks, samples = [], 0
    for track in index.query(selected["query_bounds"], shared["query_time_s"]):
        tracks.append(track)
        samples += len(track.time)
        if len(tracks) > budget.max_tracks_per_tile or samples > budget.max_track_samples_per_tile:
            raise ValueError("The recorded trajectory query exceeds the declared budget")
    events, _ = prepare_events(shared["events"])
    observed = {"trajectories": len(tracks), "trajectory_samples": samples,
                "ridge_records": len(shared["events"]), "independent_groups": len(events)}
    if observed != selected["expected_inputs"]:
        raise ValueError(f"Restored inputs changed the workload: {observed}")
    fixture = {key: value for key, value in shared.items()
               if key not in ("cases", "expected_counts")}
    fixture.update({key: value for key, value in selected.items() if key != "expected_inputs"})
    fixture.update(real_index=str(args.index.resolve()), index_input_hash=index.report["input_hash"],
                   track_ids=[track.id for track in tracks], budget=asdict(budget),
                   expected_counts=shared["expected_counts"][args.case])
    args.output.mkdir(parents=True, exist_ok=False)
    destination = args.output / "workload.json"
    destination.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"fixture": str(destination.resolve()), "case": args.case,
                      "counts": observed, "scope": shared["scope"]}), flush=True)
    return destination, shared["expected_counts"][args.case]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "tests/data/real-search-workloads.json")
    parser.add_argument("--case", choices=("previous-fit", "offset"), default="previous-fit")
    parser.add_argument("--index", required=True, type=Path, help="Restored historical trajectory index")
    parser.add_argument("--baseline-source", required=True, type=Path, help="Baseline src/ directory")
    parser.add_argument("--current-source", type=Path, default=ROOT / "src")
    parser.add_argument("--repeats", type=int, default=3, help="Alternating baseline/current pairs")
    parser.add_argument("--timeout-s", type=float, default=600.0, help="Timeout for each scoring worker")
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--prepare-only", action="store_true", help="Check real inputs without timing scoring")
    args = parser.parse_args()
    if args.repeats < 1 or args.timeout_s <= 0:
        parser.error("--repeats and --timeout-s must be positive")
    if args.output.exists():
        parser.error("Choose a new --output directory; existing evidence is preserved")
    for source in (args.baseline_source, args.current_source):
        if not (source / "dopplergeist/__init__.py").is_file():
            parser.error(f"Source directory is missing the dopplergeist package: {source}")
    fixture, expected = prepare(args)
    if args.prepare_only:
        return
    output = args.output / "runs"
    command = [sys.executable, str(ROOT / "scripts/benchmark_prepared_measurements.py"),
               "compare", "--fixture", str(fixture.resolve()),
               "--baseline-source", str(args.baseline_source.resolve()),
               "--current-source", str(args.current_source.resolve()),
               "--repeats", str(args.repeats), "--timeout-s", str(args.timeout_s),
               "--output", str(output.resolve())]
    subprocess.run(command, check=True)
    results = sorted(output.glob("*-*/results.json"))
    if len(results) != 2 * args.repeats:
        raise AssertionError("The comparison did not produce every requested scoring result")
    print(json.dumps({"comparison": str((output / "comparison.json").resolve()),
                      "case": args.case, "workload_counts": expected,
                      "exact_candidates_accounting_and_ledger": True}), flush=True)


if __name__ == "__main__":
    main()
