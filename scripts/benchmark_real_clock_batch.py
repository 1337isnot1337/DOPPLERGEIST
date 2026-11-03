"""Measure clock-trial scoring on real recorded ridges and historical flights.

The fixture must provide real events, CPA rows, a development receiver point,
query bounds/time and a flight-index path. This is a scoped performance check,
not an end-to-end localization or location-accuracy benchmark.
"""
import argparse
import json
import math
from pathlib import Path
import random
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import Track
from dopplergeist.matching import _cache_ridge_fits, association_candidates, prepare_events
from dopplergeist.search import score_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path, help="New output JSON file")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new output file to preserve previous measurements")
    fixture = json.loads(args.fixture.read_text())
    events, measurements = prepare_events(fixture["events"])
    candidates, counts = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
    selected = sorted(random.Random(20261103).sample(range(len(candidates)), 100))
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
    acoustic = Track.acoustic
    calls = {"calls": 0, "samples": 0}

    def counted(track, times, observer, c=343.0):
        calls["calls"] += 1
        calls["samples"] += np.asarray(times).size
        return acoustic(track, times, observer, c)

    @_cache_ridge_fits
    def run():
        rows = []
        for index in selected:
            result = score_candidate(candidates[index], point, tracks, events, measurements, mode="robust_ridge")
            score = result["score"]
            rows.append({"candidate_index": index, "group_count": len(candidates[index]["event_indices"]),
                         "score": float(score) if math.isfinite(score) else None,
                         "recording_start_time_s": result.get("recording_start_time_s"),
                         "scoring_assessment": result["scoring_assessment"]})
        return rows

    Track.acoustic = counted
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        rows = run()
    finally:
        Track.acoustic = acoustic
    report = {"source": str(args.fixture), "candidate_count": len(candidates), "selection_seed": 20261103,
              "association_counts": counts, "acoustic": calls, "wall_s": time.perf_counter() - wall,
              "process_cpu_s": time.process_time() - cpu, "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(f"Scored {len(rows)} real associations in {report['wall_s']:.3f} s; "
          f"{calls['calls']} acoustic calls / {calls['samples']} samples")


if __name__ == "__main__":
    main()
