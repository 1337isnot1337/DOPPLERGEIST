"""Compare native/Python ridge fitting on recorded audio and observed tracks.

The fixture is the real CPA diagnostic used by benchmark_real_clock_batch.py.
Both arms receive identical captured acoustic arrays; acquisition and geometry
are excluded. Every returned diagnostic must match exactly. This is a fitting
runtime check, not an end-to-end or location-accuracy benchmark.
"""
import argparse
import json
from pathlib import Path
import statistics
import time

import numpy as np
import pandas as pd

from dopplergeist import matching
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.search import filter_association_event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path, help="New summary JSON file")
    parser.add_argument("--index", type=Path, help="Override the fixture's local flight-index path")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tracks-per-event", type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1 or args.tracks_per_event < 1:
        parser.error("repeat and track counts must be positive")
    if args.output.exists():
        raise FileExistsError("Use a new output file to preserve prior measurements")
    native = getattr(matching, "_native_fit_irls", None)
    if native is None:
        raise RuntimeError("Build the optional native ridge extension before comparing it")
    fixture = json.loads(args.fixture.read_text())
    events, measurements = matching.prepare_events(fixture["events"])
    index = FlightIndex(args.index or fixture["real_index"])
    tracks = {track.id: track for track in index.query(fixture["query_bounds"], fixture["query_time_s"])}
    table = pd.DataFrame(fixture["cpa_rows"])
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    inputs, unsupported = [], 0
    for event, measurement in zip(events, measurements):
        rows = list(filter_association_event(table, event, 5., None, 5.).itertuples())[:args.tracks_per_event]
        for row in rows:
            if row.flight_id not in tracks:
                continue
            starts = row.receive_time - event["cpa_receive_s"] + np.linspace(-5, 5, 21)
            batch = matching.batch_acoustic_trials([tracks[row.flight_id]], [measurement], observer, starts)[0]
            if batch is None:
                unsupported += len(starts)
                continue
            factors, emissions = batch
            complete = np.all(np.isfinite(factors) & np.isfinite(emissions) & (factors > 0), axis=1)
            unsupported += int((~complete).sum())
            sigma = matching._frequency_scale(event)
            fraction = event.get("quality", {}).get("source_drift_fraction", .02)
            for factor, emitted in zip(factors[complete], emissions[complete]):
                inputs.append((measurement, event["f0_range_hz"], sigma, fraction, factor, emitted))
    if not inputs:
        raise RuntimeError("The real fixture supplied no supported acoustic fits")

    def run():
        return [matching._fit_ridge_uncached(None, None, measurement, 0., bounds, 343., sigma, fraction,
                    acoustic_result=(factor, emitted))
                for measurement, bounds, sigma, fraction, factor, emitted in inputs]

    trials = {"python": [], "native": []}
    reference = None
    try:
        for trial in range(args.repeats):
            order = ("python", "native") if trial % 2 == 0 else ("native", "python")
            for name in order:
                matching._native_fit_irls = native if name == "native" else None
                wall, cpu = time.perf_counter(), time.process_time()
                result = run()
                timing = {"wall_s": time.perf_counter() - wall, "cpu_s": time.process_time() - cpu}
                payload = json.dumps(result, sort_keys=True, allow_nan=True)
                if reference is None:
                    reference = payload
                if payload != reference:
                    raise AssertionError("Real ridge-fit diagnostic payload changed")
                trials[name].append(timing)
                print(json.dumps({"implementation": name, "trial": trial + 1, **timing}), flush=True)
    finally:
        matching._native_fit_irls = native
    summary = {name: {"trials": rows,
                      "median_wall_s": statistics.median(row["wall_s"] for row in rows),
                      "median_cpu_s": statistics.median(row["cpu_s"] for row in rows)}
               for name, rows in trials.items()}
    summary.update({"fixture": str(args.fixture), "fits": len(inputs),
        "unsupported_clock_fits": unsupported, "exact_diagnostic_payload_match": True,
        "native_backend": matching.RIDGE_FIT_BACKEND, "numpy_version": np.__version__,
        "wall_speedup": summary["python"]["median_wall_s"] / summary["native"]["median_wall_s"],
        "cpu_speedup": summary["python"]["median_cpu_s"] / summary["native"]["median_cpu_s"],
        "scope": "Real-input ridge fitting only; excludes geometry and does not establish location accuracy"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
