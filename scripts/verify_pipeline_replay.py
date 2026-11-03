"""Replay frozen methodology cases and write independent verification receipts.

This checks the manually configured research pipeline. It deliberately does not
assert that automatic event discovery, upload, or national validation is complete.
Truth/reference files are opened only after the search subprocess has exited.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "synthetic-two-events": {
        "config": "data/synthetic/two-events.json",
        "truth": "data/synthetic/truth.json",
        "baseline": "evidence/results/synthetic-two-events/report.json",
        "scope": "synthetic; manual event windows/bands; three candidate regions",
    },
    "synthetic-known-minute": {
        "config": "data/synthetic/known-time-minute.json",
        "truth": "data/synthetic/truth.json",
        "baseline": "evidence/results/synthetic-known-minute/report.json",
        "scope": "synthetic; manual event window/band; known recording start",
    },
    "reference-local": {
        "config": "data/source/reproduce-local.json",
        "baseline": "evidence/results/reference-local-fast/report.json",
        "scope": "real; source-informed event windows/bands and regional bounds",
    },
    "reference-faint": {
        "config": "data/source/reproduce-faint-alltypes-local.json",
        "baseline": "evidence/results/reference-faint-alltypes-local/report.json",
        "scope": "real; manual faint event window/band; regional; clock from two-event result",
    },
}


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def digest(path):
    path = Path(path)
    with path.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256}


def input_files(config_path):
    """Include terrain, type data and supplied ridge files omitted by old reports."""
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text())
    paths = [config_path, config_path.parent / config["audio"]]
    paths.extend(config_path.parent / name for name in config["tracks"])
    if config.get("type_database"):
        paths.append(config_path.parent / config["type_database"])
    terrain = config["terrain"]
    paths.extend(config_path.parent / name for name in terrain.get("rasters", []))
    if terrain.get("geoid_raster"):
        paths.append(config_path.parent / terrain["geoid_raster"])
    if terrain.get("copernicus_cache"):
        paths.extend(sorted((config_path.parent / terrain["copernicus_cache"]).rglob("*.tif")))
    paths.extend(config_path.parent / event["ridge_csv"] for event in config["events"]
                 if event.get("ridge_csv"))
    return sorted({path.resolve() for path in paths})


def distance_m(first, second):
    from pyproj import Geod
    return float(Geod(ellps="WGS84").inv(first["lon"], first["lat"],
                                        second["lon"], second["lat"])[2])


def evaluate(name, report):
    """Evaluate only a completed run; no truth is passed to the child command."""
    case = CASES[name]
    baseline_path = ROOT / case["baseline"]
    baseline = json.loads(baseline_path.read_text())["best"]
    best = report["best"]
    displacement = distance_m(best, baseline)
    result = {
        "evaluation_inputs": [digest(baseline_path)],
        "baseline_displacement_m": displacement,
        "baseline_flight_ids_match": best["flight_ids"] == baseline["flight_ids"],
        "baseline_score_delta": best["score"] - baseline["score"],
        "baseline_clock_delta_s": best["recording_start_time_s"] - baseline["recording_start_time_s"],
    }
    if case.get("truth"):
        truth_path = ROOT / case["truth"]
        truth = json.loads(truth_path.read_text())
        result["evaluation_inputs"].append(digest(truth_path))
        result["position_error_m"] = distance_m(best, truth)
        result["clock_error_s"] = best["recording_start_time_s"] - truth["recording_start_time_s"]
        expected_flights = truth["flight_ids"][:len(best["flight_ids"])]
        result["flight_ids_correct"] = best["flight_ids"] == expected_flights
        result["reference_kind"] = "independent synthetic renderer truth"
    else:
        # PROGRESS.md explicitly labels this as a public-platform coordinate,
        # not surveyed ground truth or an independent recording-clock source.
        result["reference_coordinate"] = {"lat": 40.8766, "lon": -73.5247}
        result["position_error_m"] = distance_m(best, result["reference_coordinate"])
        result["reference_kind"] = "published public-platform coordinate; physical uncertainty unquantified"
    for threshold in (100, 500, 1000):
        result[f"within_{threshold}_m"] = result["position_error_m"] <= threshold
    result["baseline_reproduced"] = bool(
        displacement <= 2 and result["baseline_flight_ids_match"]
        and abs(result["baseline_score_delta"]) <= 1e-4
        and abs(result["baseline_clock_delta_s"]) <= 0.05)
    return result


def execute(command, output, timeout_s):
    """Preserve logs and kill the whole subprocess group on timeout."""
    metrics = output / "resource-usage.txt"
    timer = shutil.which("time")
    wrapped = ([timer, "-f", "max_rss_kib=%M\nuser_cpu_s=%U\nsystem_cpu_s=%S", "-o", str(metrics), "--"]
               if timer else []) + command
    environment = dict(os.environ, MPLBACKEND="Agg", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    began = time.monotonic()
    timed_out = False
    with (output / "pipeline.log").open("wb") as log:
        child = subprocess.Popen(wrapped, stdout=log, stderr=subprocess.STDOUT,
                                 cwd=ROOT, env=environment, start_new_session=True)
        try:
            child.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
    usage = {}
    if metrics.exists():
        for line in metrics.read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                usage[key] = float(value)
    return {"command": command, "exit_code": child.returncode, "timed_out": timed_out,
            "elapsed_s": time.monotonic() - began, "resource_usage": usage}


def verify_case(name, output, timeout_s):
    output.mkdir()
    receipt = {"case": name, "scope": CASES[name]["scope"], "status": "failed"}
    try:
        config = ROOT / CASES[name]["config"]
        receipt["search_inputs"] = [digest(path) for path in input_files(config)]
        command = [sys.executable, "-m", "aircraft_geoloc.cli", "run", str(config),
                   "--output", str(output / "pipeline")]
        receipt.update(execute(command, output, timeout_s))
        if receipt["exit_code"] == 0:
            report_path = output / "pipeline/report.json"
            report = json.loads(report_path.read_text())
            receipt["report"] = digest(report_path)
            receipt["evaluation"] = evaluate(name, report)
            receipt["status"] = "passed" if receipt["evaluation"]["baseline_reproduced"] else "baseline_changed"
    except Exception as exc:
        # A missing fixture or failed case must not suppress later cases.
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    dump(output / "verification.json", receipt)
    return receipt


def runtime():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    sources = [digest(path) for path in sorted((ROOT / "src").rglob("*.py"))]
    return {"git_commit": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
            "python": sys.version, "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in
                         ["numpy", "scipy", "pandas", "soundfile", "pyproj", "rasterio", "matplotlib", "requests", "pyarrow"]},
            "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
            "sources": sources, "runner": digest(__file__)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=CASES, dest="cases")
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing paths are refused")
    parser.add_argument("--timeout-s", type=float, default=1800)
    args = parser.parse_args(argv)
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    summary = {"schema_version": 1, "started_utc": datetime.now(timezone.utc).isoformat(),
               "runtime": runtime(), "cases": [], "automatic_upload_goal_verified": False,
               "accuracy_policy": {"report_thresholds_m": [100, 500, 1000],
                                   "acceptable_error_m": 1000, "preferred_error_m": 500},
               "limitations": ["Manual event settings remain search inputs in these replays.",
                               "Synthetic and regional reference replays do not establish national real-audio accuracy.",
                               "The historical faint reference missed 100 m; new point-error metrics also report 500/1000 m without rewriting its original outcome.",
                               "Evaluation inputs are read after search; filesystem sandboxing is not asserted."]}
    for name in dict.fromkeys(args.cases or CASES):
        receipt = verify_case(name, output / name, args.timeout_s)
        summary["cases"].append(receipt)
        dump(output / "verification.json", summary)
        print(json.dumps({"case": name, "status": receipt["status"],
                          "evaluation": receipt.get("evaluation"), "error": receipt.get("error")}), flush=True)
    summary["baseline_replays_passed"] = all(row["status"] == "passed" for row in summary["cases"])
    dump(output / "verification.json", summary)
    return 0 if summary["baseline_replays_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
