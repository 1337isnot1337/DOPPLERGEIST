"""Compare a complete search stage on saved real-audio and observed-flight inputs.

The receiver point and clock window are development settings, not independent
location truth. No recordings, ridges or aircraft observations are generated.
The baseline search module shares unchanged matching/geometry implementations
with the current search so this isolates source-fit batching, not ingestion.
"""
import argparse
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import statistics
import time

import numpy as np
import pandas as pd

from dopplergeist import batch_ridge, matching, search, tiled_search
from dopplergeist.data_access import FlightIndex
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.geometry import Track


def json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def serialized(value):
    return json.dumps(value, sort_keys=True, allow_nan=True, default=json_default)


def ledger_rows(ledger):
    with ledger.connect() as db:
        names = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: sorted(db.execute('SELECT * FROM "' + name + '"').fetchall(), key=serialized)
                for name in names}


@contextmanager
def count_computations(baseline_batch):
    counts = {"scalar_fits": 0, "batch_calls": 0, "batched_fits": 0,
              "acoustic_calls": 0, "acoustic_samples": 0}
    scalar = matching._fit_ridge_uncached
    guarded_scalar = batch_ridge._fit_ridge_uncached
    baseline_scalar = baseline_batch._fit_ridge_uncached
    batch = batch_ridge.first_event_fits
    acoustic = Track.acoustic

    def counted_scalar(*args, **kwargs):
        counts["scalar_fits"] += 1
        return scalar(*args, **kwargs)

    def counted_batch(*args, **kwargs):
        counts["batch_calls"] += 1
        result = batch(*args, **kwargs)
        if result is not None:
            counts["batched_fits"] += len(result)
        return result

    def counted_acoustic(track, receive, *args, **kwargs):
        counts["acoustic_calls"] += 1
        counts["acoustic_samples"] += np.asarray(receive).size
        return acoustic(track, receive, *args, **kwargs)

    matching._fit_ridge_uncached = batch_ridge._fit_ridge_uncached = counted_scalar
    baseline_batch._fit_ridge_uncached = counted_scalar
    batch_ridge.first_event_fits = counted_batch
    Track.acoustic = counted_acoustic
    try:
        yield counts
    finally:
        matching._fit_ridge_uncached = scalar
        batch_ridge._fit_ridge_uncached = guarded_scalar
        baseline_batch._fit_ridge_uncached = baseline_scalar
        batch_ridge.first_event_fits = batch
        Track.acoustic = acoustic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path,
                        default=Path(__file__).resolve().parents[1] / "tests/data/real-search-workloads.json")
    parser.add_argument("--case", default="previous-fit", help="Case in a shared recorded-input fixture")
    parser.add_argument("--index", type=Path, help="Restored real trajectory index; overrides fixture path")
    parser.add_argument("--baseline-repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("Need at least one paired run")
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = json.loads(args.fixture.read_text())
    if "cases" in fixture:
        if args.case not in fixture["cases"]:
            parser.error("Unknown real workload case: " + args.case)
        fixture = dict(fixture, **fixture["cases"][args.case])
    index_path = args.index or fixture.get("real_index")
    if index_path is None:
        parser.error("Supply --index with the restored real trajectory index")
    events, measurements = matching.prepare_events(fixture["events"])
    tracks = list(FlightIndex(index_path).query(fixture["query_bounds"], fixture["query_time_s"]))
    point = dict({"x": 0., "y": 0.}, **fixture["point"])
    points = pd.DataFrame([point])
    parameters = dict({"mode": "robust_ridge"}, **fixture.get("scoring", {}))
    budget = tiled_search.SearchBudget(**fixture.get("budget", {}))
    start_window = fixture.get("recording_start_window_s")
    # Warm the track's deterministic motion cache equally before both scorers.
    for track in tracks:
        track._unsupported_motion_intervals(parameters.get("c", 343.))
    baseline_path = args.baseline_repository / "src/dopplergeist/search.py"
    spec = importlib.util.spec_from_file_location("dopplergeist._comparison_search", baseline_path)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    batch_spec = importlib.util.spec_from_file_location("dopplergeist._comparison_batch_ridge",
        args.baseline_repository / "src/dopplergeist/batch_ridge.py")
    baseline_batch = importlib.util.module_from_spec(batch_spec)
    batch_spec.loader.exec_module(baseline_batch)
    functions = {"baseline": baseline.score_candidate, "current": search.score_candidate}
    original = tiled_search.score_candidate
    original_batch_fit = batch_ridge.first_event_fits
    reference = None
    reports = []
    try:
        for repeat in range(args.repeats):
            order = ("baseline", "current") if repeat % 2 == 0 else ("current", "baseline")
            for name in order:
                tiled_search.score_candidate = functions[name]
                batch_ridge.first_event_fits = (baseline_batch.first_event_fits if name == "baseline"
                                                else original_batch_fit)
                ledger = RetentionLedger(args.output / f"{name}-{repeat}.sqlite", "real-search-batch",
                                         "matched_group_support_minus_normalized_residual")
                with count_computations(baseline_batch) as counts:
                    wall, cpu = time.perf_counter(), time.process_time()
                    rows, accounting = tiled_search._score(points, tracks, events, measurements, budget,
                        parameters, fixture.get("filters", {}), start_window, ledger=ledger,
                        stage="coarse:real-recording")
                    cpu, wall = time.process_time()-cpu, time.perf_counter()-wall
                full_result = serialized((rows, accounting, ledger_rows(ledger)))
                if reference is None:
                    reference = full_result
                identical = full_result == reference
                report = {"mode": name, "repeat": repeat, "wall_s": wall, "cpu_s": cpu,
                          "computations": counts, "cpa_rows": accounting["cpa_rows"],
                          "associations": accounting["candidates"], "retained": len(rows),
                          "identical_payload_and_ledger": identical}
                expected = fixture.get("expected_counts", {}).get(args.case, {})
                if any(report[key] != value for key, value in expected.items()):
                    raise RuntimeError("Restored inputs changed the declared real workload counts")
                reports.append(report)
                print(json.dumps(report), flush=True)
                if not identical:
                    (args.output / "reference-result.json").write_text(reference + "\n")
                    (args.output / "different-result.json").write_text(full_result + "\n")
                    raise RuntimeError("Candidate payload, accounting or retention ledger changed")
    finally:
        tiled_search.score_candidate = original
        batch_ridge.first_event_fits = original_batch_fit
    medians = {name: {key: statistics.median(r[key] for r in reports if r["mode"] == name)
                      for key in ("wall_s", "cpu_s")} for name in functions}
    summary = {"scope": "complete development receiver search stage; no location-accuracy claim",
               "fixture": str(args.fixture.resolve()), "baseline_repository": str(args.baseline_repository.resolve()),
               "case": args.case, "index": str(Path(index_path).resolve()),
               "groups": len(events), "tracks": len(tracks), "runs": reports, "medians": medians,
               "cpu_speedup": medians["baseline"]["cpu_s"]/medians["current"]["cpu_s"],
               "wall_speedup": medians["baseline"]["wall_s"]/medians["current"]["wall_s"],
               "identical_payload_and_ledger": True}
    (args.output / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in
                     ("cpu_speedup", "wall_speedup", "identical_payload_and_ledger")}), flush=True)


if __name__ == "__main__":
    main()
