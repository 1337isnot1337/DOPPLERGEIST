#!/usr/bin/env python3
"""Run the registered forty-file public Pathak discovery development control.

Discovery subprocesses receive only an opaque original WAV and an output path.
Publisher harmonic labels are loaded only by the later evaluation command.
No flight association, clock validation or geolocation is performed.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

import numpy as np

RECORD = "https://zenodo.org/records/24075029"
ARCHIVE_MD5 = "3f41bfd6ebaaddb86bdc50ae306c4093"
DETECTOR_REF = "463834f5bc9b839a74593b429dd88e92c7ad5779"
DEADLINE_S = 120


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def prepare(data, output):
    digest = hashlib.md5()
    with (data / "raw_flight_data.zip").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != ARCHIVE_MD5:
        raise ValueError("Archive does not match the pinned public release")
    extracted = data / "extracted"
    if not extracted.exists():
        with zipfile.ZipFile(data / "raw_flight_data.zip") as archive:
            if any(name.startswith("/") or ".." in Path(name).parts for name in archive.namelist()):
                raise ValueError("Unsafe archive member")
            archive.extractall(extracted)
    sources = sorted(extracted.rglob("*.wav"))
    publisher = read_csv(data / "final_results_40_cases.csv")
    if (len(sources) != 40 or len(publisher) != 40
            or len({row["audio_file"] for row in publisher}) != 40
            or {source.name for source in sources} != {row["audio_file"] for row in publisher}):
        raise ValueError("Expected exactly the forty published WAVs and matching metadata rows")
    output.mkdir(parents=True, exist_ok=False)
    population = []
    for index, source in enumerate(sources, 1):
        case_id = f"P{index:02d}"
        destination = output / f"{case_id}.wav"
        shutil.copyfile(source, destination)
        population.append({"case_id": case_id, "input_audio": str(destination.resolve()),
                           "published_audio": str(source.relative_to(extracted))})
    write_json(output / "population.json", {"source": RECORD, "cases": population})
    print(f"Prepared all {len(population)} unmodified public WAVs with opaque names", flush=True)


def run_case(audio, output):
    from dopplergeist.discovery import discover_events
    from dopplergeist.intake import intake_recording

    recording = intake_recording(audio, output / "intake")
    events = discover_events(recording, output_dir=output / "discovery",
                             plot_summary=False, plot_event_details=False, event_audio=False)
    print(f"Completed automatic discovery: {len(events)} events", flush=True)


def discover(inputs, output, source_ref=DETECTOR_REF):
    repository = Path(__file__).resolve().parents[1]
    source_ref = subprocess.check_output(
        ["git", "rev-parse", "--verify", source_ref + "^{commit}"], cwd=repository, text=True).strip()
    # A future checkout must not silently mislabel changed production code.
    subprocess.run(["git", "diff", "--quiet", source_ref, "--", "src/dopplergeist"],
                   cwd=repository, check=True)
    population = json.loads((inputs / "population.json").read_text())
    if len(population["cases"]) != 40:
        raise ValueError("Expected all forty registered cases")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "population.json", population)
    outcomes = []
    for case in population["cases"]:
        destination = output / case["case_id"]
        row = {"case_id": case["case_id"], "status": "failed", "returncode": "",
               "elapsed_s": 0.0, "source_seconds": "", "events": "", "groups": ""}
        started = time.perf_counter()
        command = [sys.executable, str(Path(__file__).resolve()), "case", "--audio", case["input_audio"],
                   "--output", str(destination)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=DEADLINE_S)
            row["returncode"] = result.returncode
            row["status"] = "completed" if result.returncode == 0 else "failed"
            (output / f"{case['case_id']}.stdout.txt").write_text(result.stdout)
            (output / f"{case['case_id']}.stderr.txt").write_text(result.stderr)
        except subprocess.TimeoutExpired as error:
            row["status"] = "timeout"
            for name, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                if isinstance(value, bytes):
                    value = value.decode(errors="replace")
                (output / f"{case['case_id']}.{name}.txt").write_text(value or "")
        row["elapsed_s"] = time.perf_counter() - started
        metadata = destination / "intake/recording.json"
        if metadata.exists():
            row["source_seconds"] = json.loads(metadata.read_text())["duration_s"]
        saved = destination / "discovery/discovery.json"
        if saved.exists():
            result = json.loads(saved.read_text())
            row.update(events=len(result["events"]), groups=len(result["proposals"]))
        outcomes.append(row)
        write_csv(output / "outcomes.csv", outcomes)
        print(json.dumps(row), flush=True)
    write_json(output / "frozen-predictions.json",
               {"detector_ref": source_ref, "deadline_s_per_case": DEADLINE_S,
                "runner_ref": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip(),
                "cases": len(outcomes), "labels_loaded": False, "location_search": False})


def epoch(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Publisher time must explicitly identify UTC")
    return parsed.timestamp()


def trace_coverage(events, times, frequencies):
    tolerance = np.maximum(2.0, 0.01 * frequencies)
    covered = np.zeros(len(times), dtype=bool)
    nearest_error = np.full(len(times), np.inf)
    best_single = 0
    for event in events:
        points = sorted((point["time_s"], point["frequency_hz"]) for point in event["ridge"])
        if len(points) < 2:
            continue
        measured_t, measured_f = np.asarray(points).T
        right = np.clip(np.searchsorted(measured_t, times), 1, len(measured_t) - 1)
        left = right - 1
        supported = ((times >= measured_t[0]) & (times <= measured_t[-1])
                     & ((measured_t[right] - measured_t[left] <= 1.0)
                        | (np.minimum(abs(times - measured_t[left]), abs(times - measured_t[right])) <= 1e-6)))
        error = np.abs(np.interp(times, measured_t, measured_f) - frequencies)
        nearest_error = np.minimum(nearest_error, np.where(supported, error, np.inf))
        matched = supported & (error <= tolerance)
        covered |= matched
        best_single = max(best_single, int(matched.sum()))
    return covered, nearest_error, best_single


def evaluate(data, predictions, output):
    frozen = json.loads((predictions / "frozen-predictions.json").read_text())
    outcomes = read_csv(predictions / "outcomes.csv")
    population = json.loads((predictions / "population.json").read_text())["cases"]
    if frozen["cases"] != 40 or len(outcomes) != 40 or len(population) != 40:
        raise ValueError("Evaluation requires every planned outcome, including failures")
    publisher = {row["audio_file"]: row for row in read_csv(data / "final_results_40_cases.csv")}
    output.mkdir(parents=True, exist_ok=False)
    rows, point_rows = [], []
    for case, outcome in zip(population, outcomes):
        if case["case_id"] != outcome["case_id"]:
            raise ValueError("Prediction population/order changed")
        row = {**outcome, "reference_points": "", "out_of_audio_points": "",
               "union_matched_points": "", "union_fraction": "", "best_single_ridge_fraction": "",
               "coverage_criterion_met": "", "evaluation_error": ""}
        try:
            if outcome["status"] != "completed":
                raise ValueError("Discovery did not complete; outcome retained without scoring")
            original = data / "extracted" / case["published_audio"]
            metadata = publisher[original.name]
            reference = read_csv(original.parent / "frequency_vs_time_used.csv")
            zero = epoch(metadata["audio_start_utc"])
            times = np.asarray([epoch(item["time_utc"]) - zero for item in reference])
            frequencies = np.asarray([float(item["frequency_hz"]) for item in reference])
            if not len(times) or not np.isfinite(times).all() or not np.isfinite(frequencies).all() or np.any(frequencies <= 0):
                raise ValueError("Invalid publisher trace")
            result = json.loads((predictions / case["case_id"] / "discovery/discovery.json").read_text())
            covered, errors, best_single = trace_coverage(result["events"], times, frequencies)
            inside = (times >= 0) & (times <= float(outcome["source_seconds"]))
            union = int(covered.sum()) / len(times)
            single = best_single / len(times)
            row.update(reference_points=len(times), out_of_audio_points=int((~inside).sum()),
                       union_matched_points=int(covered.sum()), union_fraction=union,
                       best_single_ridge_fraction=single, coverage_criterion_met=union >= 0.8 and single >= 0.6)
            for t, f, ok, error, within in zip(times, frequencies, covered, errors, inside):
                point_rows.append({"case_id": case["case_id"], "audio_time_s": float(t),
                                   "reference_frequency_hz": float(f), "inside_audio": bool(within),
                                   "matched": bool(ok), "nearest_supported_error_hz": float(error) if np.isfinite(error) else ""})
        except (OSError, ValueError, KeyError) as error:
            row["evaluation_error"] = type(error).__name__ + ": " + str(error)
        rows.append(row)
    write_csv(output / "cases.csv", rows)
    if point_rows:
        write_csv(output / "reference-points.csv", point_rows)
    summary = {"source": RECORD, "cases": len(rows),
               "completed_discoveries": sum(row["status"] == "completed" for row in rows),
               "scored_cases": sum(row["reference_points"] != "" for row in rows),
               "coverage_criterion_met": sum(row["coverage_criterion_met"] is True for row in rows),
               "evaluation_failures": [{"case_id": row["case_id"], "error": row["evaluation_error"]}
                                       for row in rows if row["evaluation_error"]],
               "out_of_audio_points": sum(row["out_of_audio_points"] or 0 for row in rows),
               "scope": "Presegmented public development recordings and publisher-traced harmonic coverage; no exhaustive false-positive labels, identity, clock calibration or geolocation acceptance"}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "case", "discover", "evaluate"))
    parser.add_argument("--data", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--source-ref", default=DETECTOR_REF,
                        help="Explicit production source pin for a newly registered discovery run")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    required = {"prepare": ("data",), "case": ("audio",), "discover": ("inputs",),
                "evaluate": ("data", "predictions")}[args.command]
    if any(getattr(args, name) is None for name in required):
        parser.error("Required: " + ", ".join("--" + name for name in required))
    if args.command == "prepare":
        prepare(args.data, args.output)
    elif args.command == "case":
        run_case(args.audio, args.output)
    elif args.command == "discover":
        discover(args.inputs, args.output, args.source_ref)
    else:
        evaluate(args.data, args.predictions, args.output)


if __name__ == "__main__":
    main()
