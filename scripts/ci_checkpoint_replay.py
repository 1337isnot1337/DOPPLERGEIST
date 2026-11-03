#!/usr/bin/env python3
"""Replay the configured methodology checkpoint; this is not product acceptance.

Default: copy the independent synthetic generator unchanged into a fresh fixture
tree, run BOTH configured cases through the real CLI, then open evaluation truth.
--real-config: run only that restored regional configuration, then compare its
result with the checked-in public-platform reference. Restore real inputs first.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time


TARGET_ERROR_M = 100.0
THREAD_ENV = {name: "1" for name in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
LIMITATIONS = [
    "Configured event windows and frequency bands; automatic discovery is not exercised.",
    "The MP3 upload interface and automatic product pipeline are not exercised.",
    "No independent nationwide real-recording accuracy claim is established.",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_record(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": checksum}


def pipeline_source_digest(source_root):
    """Match the existing pipeline's implementation digest byte for byte."""
    source_root = Path(source_root)
    checksum = hashlib.sha256()
    for source in sorted(source_root.rglob("*.py")):
        checksum.update(str(source.relative_to(source_root)).encode())
        checksum.update(source.read_bytes())
    return checksum.hexdigest()


def runtime_record():
    versions = {}
    for name in ("numpy", "scipy", "pandas", "soundfile", "pyproj", "rasterio",
                 "matplotlib", "requests", "pyarrow", "pytest", "setuptools", "pip"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    external = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            completed = subprocess.run([name, "-version"], capture_output=True, text=True, timeout=10)
            external[name] = {"returncode": completed.returncode,
                              "version": (completed.stdout or completed.stderr).splitlines()[:1]}
        except (OSError, subprocess.SubprocessError) as exc:
            external[name] = {"error": str(exc)}
    return {"python": sys.version, "executable": sys.executable,
            "implementation": platform.python_implementation(), "platform": platform.platform(),
            "machine": platform.machine(), "packages": versions, "external_tools": external,
            "subprocess_thread_settings": THREAD_ENV}


def code_snapshot(repo, output):
    """Use one fixed source snapshot even if another worker edits the checkout."""
    destination = output / "implementation"
    destination.mkdir()
    shutil.copytree(repo / "src", destination / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(repo / "pyproject.toml", destination / "pyproject.toml")
    shutil.copy2(Path(__file__), destination / "ci_checkpoint_replay.py")
    records = {}
    combined = hashlib.sha256()
    for path in sorted(destination.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(destination).as_posix()
        record = file_record(path)
        records[name] = record
        combined.update(name.encode() + b"\0" + record["sha256"].encode() + b"\0")
    git = {"commit": None, "status": "no_git_metadata"}
    if (repo / ".git").exists():
        for field, args in (("commit", ["rev-parse", "HEAD"]), ("status", ["status", "--porcelain"])):
            try:
                result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10)
                git[field] = result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
            except (OSError, subprocess.SubprocessError) as exc:
                git[field] = str(exc)
    return destination, {"checkout": str(repo), "git": git,
                         "snapshot_sha256": combined.hexdigest(), "files": records,
                         "expected_pipeline_implementation_sha256": pipeline_source_digest(destination / "src")}


def sampled_tree_rss(pid):
    """Linux process-tree RSS sample, not a kernel high-water-mark measurement."""
    if sys.platform != "linux":
        return None
    total, pending, seen = 0, [pid], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            total += int(Path(f"/proc/{current}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
            children = Path(f"/proc/{current}/task/{current}/children").read_text().split()
            pending.extend(int(child) for child in children)
        except (OSError, ValueError, IndexError):
            continue
    return total


def execute(command, cwd, log_path, env, timeout_s):
    result = {"command": [str(part) for part in command], "cwd": str(cwd),
              "log": str(log_path), "started_utc": utc_now(), "timeout_s": timeout_s}
    began = time.monotonic()
    peak = None
    try:
        with Path(log_path).open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"))
            while process.poll() is None:
                sample = sampled_tree_rss(process.pid)
                if sample is not None:
                    peak = max(peak or 0, sample)
                if time.monotonic() - began > timeout_s:
                    result["timed_out"] = True
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                        process.wait()
                    break
                time.sleep(0.2)
            result["returncode"] = process.returncode
    except OSError as exc:
        result.update(returncode=None, error=f"{type(exc).__name__}: {exc}")
    result.update(elapsed_s=time.monotonic() - began, finished_utc=utc_now(),
                  peak_sampled_process_tree_rss_bytes=peak,
                  memory_measurement="Linux process-tree RSS sampled every 0.2 s; may miss peaks; shared pages may be counted twice")
    return result


def config_inputs(config_path):
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    paths = [config_path, config_path.parent / config["audio"]]
    paths.extend(config_path.parent / path for path in config["tracks"])
    if config.get("type_database"):
        paths.append(config_path.parent / config["type_database"])
    terrain = config.get("terrain", {})
    if not terrain.get("copernicus_cache"):
        paths.extend(config_path.parent / path for path in terrain.get("rasters", []))
    if terrain.get("geoid_raster"):
        paths.append(config_path.parent / terrain["geoid_raster"])
    if terrain.get("copernicus_cache"):
        cache = config_path.parent / terrain["copernicus_cache"]
        paths.append(cache / "tileList.txt")
    paths.extend(config_path.parent / event["ridge_csv"] for event in config["events"] if event.get("ridge_csv"))
    return [file_record(path) for path in dict.fromkeys(path.resolve() for path in paths)]


def evaluate_best(best, truth, expected_flights=None):
    """Evaluation-only oracle. Caller must finish every search before calling."""
    from pyproj import Geod

    for field in ("lat", "lon"):
        if not isinstance(best.get(field), (int, float)) or not math.isfinite(best[field]):
            raise ValueError(f"Best candidate lacks a finite {field}")
    error_m = abs(Geod(ellps="WGS84").inv(truth["lon"], truth["lat"], best["lon"], best["lat"])[2])
    if not math.isfinite(error_m):
        raise ValueError("Non-finite location error")
    result = {"error_m": error_m, "distance_metric": "horizontal WGS84 geodesic",
              "threshold_m": TARGET_ERROR_M, "meets_threshold": error_m < TARGET_ERROR_M}
    if expected_flights is not None:
        result["expected_flight_ids"] = expected_flights
        result["flight_ids_correct"] = best.get("flight_ids") == expected_flights
    if "recording_start_time_s" in truth and "recording_start_time_s" in best:
        result["clock_error_s"] = best["recording_start_time_s"] - truth["recording_start_time_s"]
    result["passed"] = result["meets_threshold"] and result.get("flight_ids_correct", True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing paths are refused")
    parser.add_argument("--real-config", type=Path, help="Run only this restored source-informed regional config")
    parser.add_argument("--case-timeout-s", type=float, default=1800, help="Per CLI case timeout (default: 1800)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.case_timeout_s) or args.case_timeout_s <= 0:
        parser.error("--case-timeout-s must be finite and positive")
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Refusing to overwrite existing output: {output}")
    if output.is_relative_to(repo / "src"):
        parser.error("Output must be outside src so the source snapshot cannot copy itself")
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    began = time.monotonic()
    receipt = {"schema_version": 1, "started_utc": utc_now(),
               "scope": "configured_methodology_checkpoint_replay", "runtime": runtime_record(),
               "limitations": list(LIMITATIONS), "automatic_upload_verified": False,
               "independent_real_accuracy_verified": False, "nationwide_search_verified": False,
               "evaluation_truth_loaded_after_all_searches": False, "cases": [], "passed": False}
    try:
        snapshot, receipt["implementation"] = code_snapshot(repo, output)
        env = os.environ.copy()
        env.update(THREAD_ENV)
        env["PYTHONPATH"] = str(snapshot / "src")
        env["MPLBACKEND"] = "Agg"
        if args.real_config:
            config = args.real_config.resolve()
            cases = [("reference-regional", config)]
            truth_path = repo / "evidence/results/reference-local/evaluation.json"
            receipt["limitations"].extend([
                "Real replay uses source-informed event settings and regional geographic bounds.",
                "The published public-platform coordinate is not surveyed ground truth.",
                "The real recording clock is not independently established.",
                "Only the supplied regional configuration is evaluated, not the full real benchmark corpus."])
        else:
            generator = output / "generated/scripts/make_synthetic_cases.py"
            generator.parent.mkdir(parents=True)
            shutil.copy2(repo / "scripts/make_synthetic_cases.py", generator)
            receipt["generator_source"] = file_record(generator)
            receipt["original_generator_source"] = file_record(repo / "scripts/make_synthetic_cases.py")
            receipt["generation"] = execute([sys.executable, str(generator)], output,
                output / "logs/generator.log", env, min(args.case_timeout_s, 600))
            fixture = generator.parent.parent / "data/synthetic"
            cases = [("synthetic-two-events", fixture / "two-events.json"),
                     ("synthetic-known-minute", fixture / "known-time-minute.json")]
            truth_path = output / "evaluation/truth.json"
            truth_path.parent.mkdir()
            # Move bytes without opening/parsing truth. Search configs do not point here.
            if (fixture / "truth.json").exists():
                (fixture / "truth.json").replace(truth_path)
        receipt["requested_cases"] = [name for name, _ in cases]
        for name, config in cases:
            case = {"case_id": name, "config": str(config), "passed": False}
            receipt["cases"].append(case)
            try:
                case["inputs"] = config_inputs(config)
                if read_json(config).get("terrain", {}).get("copernicus_cache"):
                    case["input_provenance_limitations"] = [
                        "Copernicus catalogue and configured geoid are hashed; actual sampled DEM tile identities and hashes are not captured by the legacy pipeline. Cache contents are not asserted to be used inputs."]
                if any(Path(item["path"]) == truth_path.resolve() for item in case["inputs"]):
                    raise ValueError("Evaluation truth cannot be a CLI data input")
                case_output = output / "cases" / name
                case_output.parent.mkdir(exist_ok=True)
                case["report_path"] = str(case_output / "report.json")
                case["execution"] = execute(
                    [sys.executable, "-m", "aircraft_geoloc.cli", "run", str(config),
                     "--output", str(case_output)], snapshot,
                    output / "logs" / f"{name}.log", env, args.case_timeout_s)
                if case["execution"].get("returncode") != 0 or case["execution"].get("timed_out"):
                    case["error"] = "CLI execution failed; inspect the retained log"
            except Exception as exc:
                case["error"] = f"{type(exc).__name__}: {exc}"
            # Intermediate receipts contain execution facts only, never evaluation truth.
            write_json(output / "acceptance.json", receipt)
        receipt["all_searches_finished_utc"] = utc_now()
        # No truth contents have been opened above. Evaluate only after ALL cases ran.
        raw_truth = read_json(truth_path)
        receipt["evaluation_truth_loaded_after_all_searches"] = True
        receipt["evaluation_truth_loaded_utc"] = utc_now()
        receipt["evaluation_reference"] = file_record(truth_path)
        truth = ({"lat": raw_truth["reference_coordinate"][0],
                  "lon": raw_truth["reference_coordinate"][1]} if args.real_config else raw_truth)
        if args.real_config:
            receipt["reference_qualifications"] = raw_truth
        for case in receipt["cases"]:
            if case.get("error"):
                continue
            try:
                report = read_json(case["report_path"])
                case["report_sha256"] = file_record(case["report_path"])["sha256"]
                case["best"] = report["best"]
                case["pipeline_elapsed_s"] = report.get("elapsed_s")
                case["pipeline_implementation_sha256"] = report.get("implementation_sha256")
                case["expected_pipeline_implementation_sha256"] = receipt["implementation"]["expected_pipeline_implementation_sha256"]
                if case["pipeline_implementation_sha256"] != case["expected_pipeline_implementation_sha256"]:
                    raise ValueError("CLI implementation digest does not match the frozen source snapshot")
                expected = None if args.real_config else truth["flight_ids"][:1 if case["case_id"] == "synthetic-known-minute" else 2]
                case["evaluation"] = evaluate_best(case["best"], truth, expected)
                case["passed"] = case["evaluation"]["passed"]
            except Exception as exc:
                case["error"] = f"{type(exc).__name__}: {exc}"
        generation_ok = (args.real_config is not None or
                         (receipt["generation"].get("returncode") == 0 and not receipt["generation"].get("timed_out")))
        receipt["passed"] = generation_ok and all(case["passed"] for case in receipt["cases"])
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        receipt.update(finished_utc=utc_now(), elapsed_s=time.monotonic() - began)
        write_json(output / "acceptance.json", receipt)
    print(json.dumps({"acceptance": str(output / "acceptance.json"), "passed": receipt["passed"],
                      "scope": receipt["scope"], "cases": [
                          {"case_id": case["case_id"], "passed": case["passed"],
                           "evaluation": case.get("evaluation"), "error": case.get("error")}
                          for case in receipt["cases"]]}, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
