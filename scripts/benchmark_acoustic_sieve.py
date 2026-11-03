"""Compare acoustic screening on a saved real-observation CPA diagnostic.

The fixture contains events with measured ridges, cpa_rows, one receiver point,
and real_index (a local FlightIndex). This is a computation replay, not a location
accuracy test. Neither audio nor aircraft observations are generated here.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd

from dopplergeist import matching, search, tiled_search
from dopplergeist.data_access import FlightIndex
from dopplergeist.finite_search import bounded_assessment, classified_assessment
from dopplergeist.geometry import Track


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--fixture", type=Path, required=True)
parser.add_argument("--index", type=Path, help="Override the fixture FlightIndex path")
parser.add_argument("--baseline", default="origin/main", help="Git revision before the sieve change")
parser.add_argument("--associations", type=int, default=256, help="Deterministically spaced real associations")
parser.add_argument("--output", type=Path, required=True, help="New result directory; never overwritten")
args = parser.parse_args()
if args.associations < 1:
    parser.error("--associations must be positive")

base_commit = subprocess.check_output(["git", "rev-parse", args.baseline], text=True).strip()
baseline_geometry = subprocess.check_output(
    ["git", "show", f"{base_commit}:src/dopplergeist/geometry.py"], text=True)
geometry = Path(__file__).resolve().parents[1] / "src/dopplergeist/geometry.py"
if baseline_geometry != geometry.read_text():
    parser.error("The shared geometry must match the baseline for this focused comparison")

# Isolate both baseline modules, so they cannot accidentally use the new fitter.
for name in ("matching", "search"):
    module = types.ModuleType("dopplergeist._point_baseline_" + name)
    module.__package__ = "dopplergeist"
    sys.modules[module.__name__] = module
    source = subprocess.check_output(
        ["git", "show", f"{base_commit}:src/dopplergeist/{name}.py"], text=True)
    source = source.replace("from .matching import ", "from ._point_baseline_matching import ")
    exec(compile(source, "baseline-" + name + ".py", "exec"), module.__dict__)
base_matching = sys.modules["dopplergeist._point_baseline_matching"]
base_search = sys.modules["dopplergeist._point_baseline_search"]

fixture = json.loads(args.fixture.read_text())
events, measurements = matching.prepare_events(fixture["events"])
all_candidates, _ = matching.association_candidates(
    pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
if not all_candidates or any(row["point_id"] != fixture["point"]["point_id"] for row in all_candidates):
    parser.error("Need actual associations for exactly the fixture receiver point")
# Fixed spacing through the associations; selection does not use their scores.
indices = np.linspace(0, len(all_candidates) - 1, min(args.associations, len(all_candidates)), dtype=int)
candidates = [all_candidates[index] for index in indices]
identities = sorted({entry["flight_id"] for row in candidates for entry in row["passes"]})
tracks = {track.id: track for track in FlightIndex(args.index or fixture["real_index"]).lookup(identities)}
point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
args.output.mkdir(parents=True, exist_ok=False)
runs, retained, all_rows = [], [], []

for name, backend, scorer in [("baseline", base_matching, base_search), ("screened", matching, search)]:
    stats = {"source_fits": 0, "acoustic_calls": 0, "acoustic_samples": 0}
    rows = []
    leader = tiled_search._RetainedScoreFloor(100, 0.0)
    original_fit = backend._fit_ridge_uncached
    original_acoustic = Track.acoustic

    def counted_fit(*args, **kwargs):
        stats["source_fits"] += 1
        return original_fit(*args, **kwargs)

    def counted_acoustic(track, receive, *args, **kwargs):
        stats["acoustic_calls"] += 1
        stats["acoustic_samples"] += np.asarray(receive).size
        return original_acoustic(track, receive, *args, **kwargs)

    @backend._cache_ridge_fits
    def run():
        for candidate in sorted(candidates, key=lambda row: -len(row["event_indices"])):
            settings = {"score_floor": leader.value} if name == "screened" else {}
            row = scorer.score_candidate(candidate, point, tracks, events, measurements,
                                         mode="robust_ridge", **settings)
            row["pass_emission_times_s"] = [float(entry["emission_time"]) for entry in candidate["passes"]]
            row["core_assessment_complete"] = (classified_assessment(row) and row["score"] is not None
                                                and math.isfinite(row["score"]))
            rows.append(row)
            if name == "screened":
                leader.observe(row)

    backend._fit_ridge_uncached = counted_fit
    Track.acoustic = counted_acoustic
    began, cpu = time.perf_counter(), time.process_time()
    try:
        run()
    finally:
        backend._fit_ridge_uncached = original_fit
        Track.acoustic = original_acoustic
    wall, used_cpu = time.perf_counter() - began, time.process_time() - cpu
    finite = [row for row in rows if row["score"] is not None and math.isfinite(row["score"])]
    kept = tiled_search.merge_candidates(finite, 100)
    retained.append(kept)
    all_rows.append(rows)
    result = dict(name=name, seconds=wall, cpu_seconds=used_cpu, **stats,
                  associations=len(candidates), finite=len(finite), retained=len(kept),
                  bounded=sum(bounded_assessment(row) for row in rows),
                  unknown=sum(row["scoring_assessment"]["unknown_trials"] for row in rows))
    runs.append(result)
    print(json.dumps(result), flush=True)

assert retained[0] == retained[1], "Retained diagnostics changed"
for baseline, screened in zip(*all_rows):
    if baseline["score"] is not None and math.isfinite(baseline["score"]) and bounded_assessment(screened):
        upper = screened["scoring_assessment"]["unknown_score_upper_bound"]
        actual = screened["score"] if screened["score"] is not None else -math.inf
        assert baseline["score"] <= max(actual, -math.inf if upper is None else upper)
summary = dict(baseline_commit=base_commit, total_associations=len(all_candidates),
               sampled_associations=len(candidates), same_retained=True, runs=runs,
               scope="Actual associations at one saved receiver point; computation only, no location accuracy claim")
(args.output / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
print("Same retained results and conservative upper bounds", flush=True)
