"""Replay the three historical failed scale-fixture tiles, without audio truth.

Compare preserved scores with a per-track oracle on the unchanged canonical
index. This is a fault-isolation regression, not a localization benchmark.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np

from aircraft_geoloc.audio import Spectrum
from aircraft_geoloc.data_access import FlightIndex, sha256, write_json
from aircraft_geoloc.geometry import AcousticSupportError
from aircraft_geoloc.search import cpa_table, pair_candidates, score_candidate
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import SearchBudget, _expanded_bounds, _record_support, _score, _tracks, grid_tiles, merge_candidates, tile_points


def signature(rows):
    return [(r["flight_ids"], r["x"], r["y"], r["score"], r["recording_start_time_s"],
             r["pass_emission_times_s"]) for r in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index")
    parser.add_argument("output")
    parser.add_argument("--manifest", default="evidence/w2-data-scale-20261102/scale-v2-manifest.json")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads(Path(args.manifest).read_text())["configuration"]
    index = FlightIndex(args.index)
    assert sha256(index.path) == config["indexes"][0]["file_sha256"], "Require the unchanged historical index"
    assert index.report["input_hash"] == config["indexes"][0]["input_hash"]
    budget = SearchBudget(**config["budget"])
    event, = config["events"]
    t = np.linspace(event["start_s"], event["end_s"], 41)
    ridge = 120 * (1 - .12 * np.tanh((t - event["cpa_receive_s"]) / 12))
    spec = Spectrum(t, np.array([80., 160.]), np.zeros((2, len(t))), np.zeros((2, len(t))))
    measurements = [(spec, ridge, np.ones(len(t)), {})]
    radius, began, reports = event["slant_range_m"][1], time.monotonic(), []
    selected = {"5_13", "9_9", "7_15"}
    for name, cells in grid_tiles(config["bounds"], budget.spacing_m, budget.tile_cells):
        if name not in selected:
            continue
        points = tile_points(cells, budget.spacing_m, config["bounds"], Terrain(constant_m=0), config["crs"])
        tracks = _tracks([index], _expanded_bounds(cells, budget.spacing_m, radius, config["crs"]), config["time_range_s"], budget)
        ranked, counts = _score(points, tracks, [event], measurements, budget, config["scoring"], {})
        summary = dict(unsupported_cpa_track_evaluations=0, unclassified_score_candidates=0,
                       evaluated_trials=0, rejected_trials=0, unknown_trials=0, unreported_trial_envelopes=0)
        _record_support(output, f"coarse:{name}", counts, summary)
        # Independently enumerate/score each track. A failure cannot interrupt
        # unrelated tracks in this oracle; retain every finite result before k.
        reference, failures, nonfinite = [], [], 0
        lookup = {p.point_id: p for p in points.itertuples()}
        for track in tracks:
            table = cpa_table([track], points, radius, config["scoring"].get("c", 343.), budget.cpa_step_s)
            candidates, _ = pair_candidates(table, [event], time_origin=config["scoring"]["time_origin"], time_tolerance_s=5.)
            for candidate in candidates:
                try:
                    row = score_candidate(candidate, lookup[candidate["point_id"]], {track.id: track},
                                          [event], measurements, **config["scoring"])
                except AcousticSupportError as error:
                    failures.append({"flight_id": track.id, "point_id": int(candidate["point_id"]), "reason": error.reason})
                    continue
                if np.isfinite(row["score"]):
                    row["pass_emission_times_s"] = [float(p["emission_time"]) for p in candidate["passes"]]
                    reference.append(row)
                else:
                    nonfinite += 1
        kept = merge_candidates(reference, budget.top_k)
        assert signature(ranked) == signature(kept), f"Clean candidate change at {name}"
        assert counts["unclassified_score_candidates"] == len(failures) + nonfinite
        assert failures and ranked, "Each historical failure tile must preserve valid diagnostics"
        report = {"tile": name, "tracks": len(tracks), "points": len(points), "finite_oracle_rows": len(reference),
                  "retained_rows": len(ranked), "typed_candidate_failures": failures, "nonfinite_oracle_rows": nonfinite,
                  "model_support_complete": False, "model_support": summary, "clean_scores_equal_oracle": True,
                  "ranked": ranked}
        write_json(output / f"tile-{name}.json", report)
        reports.append({k: v for k, v in report.items() if k != "ranked"})
        print(json.dumps({k: v for k, v in report.items() if k not in ("ranked", "typed_candidate_failures")}), flush=True)
    assert {r["tile"] for r in reports} == selected
    root = Path(__file__).resolve().parents[1]
    write_json(output / "report.json", {"scope": "Historical three failed analytic-ridge scale tiles; no localization truth",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "index_sha256": sha256(index.path), "index_input_hash": index.report["input_hash"],
        "old_manifest_sha256": sha256(args.manifest), "code_sha256": {p.name: sha256(p) for p in (root / "src/aircraft_geoloc").glob("*.py")},
        "runner_sha256": sha256(__file__), "elapsed_s": time.monotonic()-began, "tiles": reports,
        "limitations": ["Diagnostic tiles were selected from preserved historical model failures, not recorder truth.",
                        "Same legacy derivatives/altitudes and constant ground; no raw normalization repair.",
                        "This does not certify continuous motion, complete national coverage or geolocation accuracy."]})


if __name__ == "__main__":
    main()
