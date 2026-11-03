"""Compare uncached vectorized and native ridge batches on recorded inputs.

Accept the captured tests/data/real-ridge-batch-arithmetic.json fixture or a
real CPA fixture in the benchmark_real_clock_batch.py format. CPA fixtures use
the first five available rows per event and 21 clock trials from -5 to +5 s.
All observations and trajectories come from the supplied fixture. Input loading
and acoustic propagation are outside timing. This is a component benchmark,
not a localization-accuracy or whole-pipeline measurement.
"""
import argparse
import inspect
import json
from pathlib import Path
import statistics
import time

import numpy as np

from dopplergeist import matching
from dopplergeist.batch_ridge import _first_event_fits_uncached


def _positive_int(value):
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError("Use a positive integer")
    return count


def _load_batches(path):
    fixture = json.loads(path.read_text())
    if "factors" in fixture and "emissions" in fixture:
        measurement = (matching.RidgeTimes(np.asarray(fixture["times"], dtype=float)),
                       np.asarray(fixture["ridge"], dtype=float),
                       np.asarray(fixture["weight"], dtype=float), {})
        batch = (measurement, fixture["event"],
                 np.asarray(fixture["factors"], dtype=float),
                 np.asarray(fixture["emissions"], dtype=float))
        return [batch], {"input_kind": "captured recorded-ridge acoustic arrays"}

    import pandas as pd
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.geometry import ecef
    from dopplergeist.search import filter_association_event

    events, measurements = matching.prepare_events(fixture["events"])
    table = pd.DataFrame(fixture["cpa_rows"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    batches, unavailable_rows, unsupported_clocks = [], 0, 0
    for event, measurement in zip(events, measurements):
        rows = list(filter_association_event(table, event, 5., None, 5.).itertuples())[:5]
        for row in rows:
            if row.flight_id not in tracks:
                unavailable_rows += 1
                continue
            starts = row.receive_time - event["cpa_receive_s"] + np.linspace(-5, 5, 21)
            acoustic = matching.batch_acoustic_trials(
                [tracks[row.flight_id]], [measurement], observer, starts)[0]
            if acoustic is None:
                unsupported_clocks += len(starts)
                continue
            factors, emissions = acoustic
            complete = np.all(np.isfinite(factors) & np.isfinite(emissions) & (factors > 0), axis=1)
            unsupported_clocks += int((~complete).sum())
            if np.any(complete):
                batches.append((measurement, event, factors[complete], emissions[complete]))
    return batches, {"input_kind": "recorded ridges and historical-flight CPA rows",
                     "selected_rows_per_event_limit": 5, "clock_trials_per_row": 21,
                     "clock_offsets_s": [-5.0, 5.0], "unavailable_flight_rows": unavailable_rows,
                     "unsupported_clock_trials": unsupported_clocks}


def _run(batches, backend, rounds):
    previous = matching._native_fit_irls
    matching._native_fit_irls = backend
    try:
        cpu, wall = time.process_time(), time.perf_counter()
        results = [[_first_event_fits_uncached(*batch) for batch in batches]
                   for _ in range(rounds)]
        timing = {"process_cpu_s": time.process_time() - cpu,
                  "wall_s": time.perf_counter() - wall}
    finally:
        matching._native_fit_irls = previous
    return timing, results


def _assert_exact(results, expected):
    for round_index, rows in enumerate(results):
        assert len(rows) == len(expected)
        for batch_index, (actual, reference) in enumerate(zip(rows, expected)):
            if json.dumps(actual, sort_keys=True) != reference:
                raise AssertionError(f"Diagnostic mismatch in round {round_index}, batch {batch_index}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path, help="New output JSON file")
    parser.add_argument("--repeats", type=_positive_int, default=5, help="Alternating timing pairs")
    parser.add_argument("--rounds", type=_positive_int, default=10, help="Complete batch passes per arm")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new output file to preserve previous measurements")
    native = matching._native_fit_irls
    module = matching._native_ridge_module
    if (module is None or native is None or native is not module.fit_irls
            or not inspect.isbuiltin(native) or not matching.RIDGE_FIT_BACKEND.startswith("native-c-")):
        raise RuntimeError("Build and load the optional native ridge extension before this benchmark")
    batches, scope = _load_batches(args.fixture)
    if not batches:
        raise ValueError("The real fixture produced no supported acoustic batches")

    _, baseline = _run(batches, None, 1)
    expected = [json.dumps(row, sort_keys=True) for row in baseline[0]]
    native_calls = 0

    def counted(*values):
        nonlocal native_calls
        native_calls += 1
        return native(*values)

    _, actual = _run(batches, counted, 1)
    _assert_exact(actual, expected)
    if not native_calls:
        raise ValueError("No batch reached the native fitter; use canonical supported inputs")

    trials = []
    for repeat in range(args.repeats):
        order = ("vectorized", "native_rows") if repeat % 2 == 0 else ("native_rows", "vectorized")
        for arm in order:
            timing, results = _run(batches, native if arm == "native_rows" else None, args.rounds)
            _assert_exact(results, expected)
            trials.append({"pair": repeat + 1, "arm": arm, **timing})
    medians = {arm: {metric: statistics.median(
        trial[metric] for trial in trials if trial["arm"] == arm)
        for metric in ("process_cpu_s", "wall_s")}
        for arm in ("vectorized", "native_rows")}
    report = {"fixture": str(args.fixture), "scope": scope,
              "measurement": ("Uncached batch fitting, including shared preprocessing; "
                              "fixture loading and acoustic propagation excluded"),
              "numpy_version": np.__version__, "ridge_fit_backend": matching.RIDGE_FIT_BACKEND,
              "batch_count": len(batches),
              "clock_rows": sum(len(batch[2]) for batch in batches),
              "sample_counts": sorted({int(batch[2].shape[1]) for batch in batches}),
              "vectorized_fallback_batches": sum(result is None for result in baseline[0]),
              "native_calls_in_verified_pass": native_calls,
              "all_diagnostics_exact": True, "repeats": args.repeats, "rounds_per_arm": args.rounds,
              "trials": trials, "medians": medians,
              "speedup": {metric: medians["vectorized"][metric] / medians["native_rows"][metric]
                          for metric in ("process_cpu_s", "wall_s")}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(f"{report['batch_count']} real batches / {report['clock_rows']} clocks: "
          f"all diagnostics exact; {report['speedup']['process_cpu_s']:.2f}x CPU speedup")


if __name__ == "__main__":
    main()
