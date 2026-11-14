#!/usr/bin/env python3
"""Paired full-recording replay for the held episode-linking performance repair."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--optimized-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if len(manifest["cases"]) != 28 or len(manifest.get("policy_exclusions", [])) != 4:
        parser.error("Expected all 28 registered cases and four explicit exclusions")
    roots = {"baseline": args.baseline_root.resolve(), "optimized": args.optimized_root.resolve()}
    for root in roots.values():
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src", "scripts"], cwd=root, check=True)
    args.output.mkdir(parents=True, exist_ok=False)
    pins = {name: subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            for name, root in roots.items()}
    (args.output / "protocol.json").write_text(json.dumps(
        {"sources": pins, "cases": [case["id"] for case in manifest["cases"]],
         "exclusions": manifest["policy_exclusions"], "deadline_s_per_case": 1800,
         "band_limit_hz": 1600, "arm_order": "alternates by case; serial execution",
         "comparison_omits_only_root_fields": ["code", "runtime_s", "cpu_time_s"]}, indent=2) + "\n")
    rows = []
    for index, case in enumerate(manifest["cases"]):
        destination = args.output / case["id"]
        destination.mkdir()
        row = {"case_id": case["id"], "baseline_status": "", "optimized_status": "",
               "baseline_wall_s": "", "optimized_wall_s": "", "baseline_cpu_s": "", "optimized_cpu_s": "",
               "baseline_proposals": "", "optimized_proposals": "", "baseline_children": "", "optimized_children": "",
               "exact_discovery_except_code_and_timing": ""}
        reports = {}
        order = ("baseline", "optimized") if index % 2 == 0 else ("optimized", "baseline")
        for name in order:
            root = roots[name]
            env = dict(os.environ, PYTHONPATH=str(root / "src"), OPENBLAS_NUM_THREADS="1",
                       OMP_NUM_THREADS="1", MPLBACKEND="Agg")
            command = [sys.executable, str(root / "scripts/validate_acoustic_episodes.py"),
                       "--manifest", str(args.manifest.resolve()), "--source-root", str(root),
                       "--output", str(destination / name), "--max-frequency-hz", "1600",
                       "--experimental-episodes", "--case", case["id"]]
            try:
                process = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                         text=True, timeout=1800)
                (destination / f"{name}.stdout.txt").write_text(process.stdout)
                (destination / f"{name}.stderr.txt").write_text(process.stderr)
                result = json.loads(process.stdout) if process.returncode == 0 else {"status": "failed"}
            except subprocess.TimeoutExpired as error:
                result = {"status": "timeout"}
                for kind, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                    if isinstance(value, bytes):
                        value = value.decode(errors="replace")
                    (destination / f"{name}.{kind}.txt").write_text(value or "")
            row[name + "_status"] = result["status"]
            row[name + "_wall_s"] = result.get("runtime_s", "")
            row[name + "_proposals"] = result.get("proposals", "")
            row[name + "_children"] = result.get("child_tracks", "")
            artifact = destination / name / "discovery/discovery.json"
            if artifact.exists():
                report = json.loads(artifact.read_text())
                row[name + "_cpu_s"] = report.get("cpu_time_s", "")
                for key in ("code", "runtime_s", "cpu_time_s"):
                    report.pop(key, None)
                reports[name] = report
            (destination / f"{name}.result.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"case_id": case["id"], "arm": name, "status": result["status"],
                              "wall_s": result.get("runtime_s"), "proposals": result.get("proposals")}), flush=True)
        if len(reports) == 2:
            row["exact_discovery_except_code_and_timing"] = reports["baseline"] == reports["optimized"]
        rows.append(row)
        write_csv(args.output / "outcomes.csv", rows)
    summary = {"cases": len(rows), "all_complete": all(row[name + "_status"] == "complete" for row in rows for name in roots),
               "exact_complete_cases": sum(row["exact_discovery_except_code_and_timing"] is True
                                           and all(row[name + "_status"] == "complete" for name in roots) for row in rows),
               "baseline_wall_s": sum(float(row["baseline_wall_s"] or 0) for row in rows),
               "optimized_wall_s": sum(float(row["optimized_wall_s"] or 0) for row in rows),
               "scope": "Acoustic implementation parity and one-shot cost; no aircraft, source-count or location acceptance"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
