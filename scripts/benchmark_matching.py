"""Replay both regional development cases before/after robust matching.

Truth is loaded only after every search completes. The original manually
configured windows/bounds are preserved and clearly labelled as development.
Run with PYTHONPATH=src python scripts/benchmark_matching.py --help.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from dopplergeist.geometry import ecef
from dopplergeist.pipeline import run


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def absolute_config(path):
    config = json.loads(path.read_text())
    def local(value):
        return str((path.parent / value).resolve())
    config["audio"] = local(config["audio"])
    config["tracks"] = [local(p) for p in config["tracks"]]
    if config.get("type_database"):
        config["type_database"] = local(config["type_database"])
    for name in ("geoid_raster", "copernicus_cache"):
        if config["terrain"].get(name):
            config["terrain"][name] = local(config["terrain"][name])
    config["terrain"]["rasters"] = [local(p) for p in config["terrain"].get("rasters", [])]
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="Restored data/source directory")
    parser.add_argument("--output", type=Path, required=True, help="New output directory; must not exist")
    parser.add_argument("--robust-only", action="store_true", help="Replay robust scoring only when baseline receipts already exist")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    cases = [("two-events", "reproduce-local.json", "reference-local"),
             ("faint", "reproduce-faint-alltypes-local.json", "reference-faint-alltypes-local")]
    outcomes = []
    for name, filename, evidence in cases:
        source = args.source_root / filename
        config = absolute_config(source)
        modes = ("robust_ridge",) if args.robust_only else (config["scoring"]["mode"], "robust_ridge")
        for mode in modes:
            directory = args.output / f"{name}-{mode}"
            directory.mkdir()
            configured = json.loads(json.dumps(config))
            configured["scoring"]["mode"] = mode
            path = directory / "config.json"
            path.write_text(json.dumps(configured, indent=2) + "\n")
            report = run(path, directory / "search")
            outcomes.append(dict(case=name, mode=mode, best=report["best"],
                elapsed_s=report["elapsed_s"], flight_combinations=report["flight_combinations"],
                implementation_sha256=report["implementation_sha256"],
                source_config_sha256=digest(source), config_sha256=digest(path), evidence=evidence))
    # Evaluation boundary: no reference coordinates were available to search.
    for result in outcomes:
        evaluation = json.loads((root / "evidence/results" / result.pop("evidence") / "evaluation.json").read_text())
        lat, lon = evaluation["reference_coordinate"]
        best = result["best"]
        result["error_m"] = float(np.linalg.norm(ecef(lat, lon, 0) - ecef(best["lat"], best["lon"], 0)))
        result["meets_100m"] = result["error_m"] <= 100
        combinations = json.loads((args.output / f"{result['case']}-{result['mode']}" / "search/flight-combinations.json").read_text())
        result["ranked_flight_combinations"] = [r["flight_ids"] for r in combinations]
    summary = dict(scope="regional, manually configured development replays; no independent/national accuracy claim",
                   truth_read_after_search=True,
                   commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                   working_tree_diff_sha256=hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=root)).hexdigest(),
                   outcomes=outcomes)
    path = args.output / "summary.json"
    path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(path)
    for result in outcomes:
        print(result["case"], result["mode"], f"{result['error_m']:.2f} m", result["best"]["flight_ids"])


if __name__ == "__main__":
    main()
