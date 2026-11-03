#!/usr/bin/env python3
"""Run alternating fresh regional HTTP pairs in one unchanged environment.

Every arm uses the same interpreter, inputs, verifier, plotting policy and thread
limit, with inherited CPU affinity. Exact comparisons precede pooled statistics.
This measures regional runtime; it makes no location-accuracy claim.
"""
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys


def stats(values):
    return ({"count": len(values), "median": statistics.median(values),
             "min": min(values), "max": max(values)} if values else None)


def save(output, summary):
    pairs = [trial for trial in summary["trials"] if trial.get("exact_comparison")]
    summary["exact_comparison_count"] = len(pairs)
    summary["status"] = ("failed" if "error" in summary else
                         "passed" if len(pairs) == summary["requested_pairs"] else "running")
    summary["statistics"] = {
        role: {metric: stats([trial["arms"][role][metric] for trial in pairs])
               for metric in ("wall_s", "cpu_s")} for role in ("baseline", "current")}
    summary["statistics"].update({
        metric: stats([trial[metric] for trial in pairs])
        for metric in ("paired_wall_speedup", "paired_cpu_speedup")})
    temporary = output / "summary.json.tmp"
    temporary.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    temporary.replace(output / "summary.json")


def run(command, output, label, record):
    stdout, stderr = (output / "logs" / f"{label}.{kind}.log" for kind in ("stdout", "stderr"))
    record.update(command=command, stdout=str(stdout), stderr=str(stderr), returncode=None)
    with stdout.open("x") as out, stderr.open("x") as err:
        record["returncode"] = subprocess.run(command, stdout=out, stderr=err, check=False).returncode
    if record["returncode"]:
        raise RuntimeError(f"{label} exited {record['returncode']}; see {stderr}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline-source", "current-source", "audio", "request", "operator", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--verifier", type=Path, default=Path(__file__).with_name("verify_upload_http.py"))
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--expected-ridges", type=int, default=17)
    parser.add_argument("--expected-groups", type=int, default=15)
    parser.add_argument("--expected-detail-plots", choices=("all", "none"), default="all")
    parser.add_argument("--expected-baseline-backend", choices=("any", "python", "native"), default="any")
    parser.add_argument("--expected-current-backend", choices=("any", "python", "native"), default="native")
    parser.add_argument("--timeout-s", type=float, default=7200)
    parser.add_argument("--poll-interval-s", type=float, default=0.25)
    args = parser.parse_args()
    if min(args.pairs, args.threads, args.expected_ridges, args.expected_groups) < 1 or any(
            not math.isfinite(value) or value <= 0 for value in (args.timeout_s, args.poll_interval_s)):
        parser.error("Pair counts, thread limits, recording counts and time limits must be positive")
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error("Use a new output directory")
    sources = {role: getattr(args, role + "_source").expanduser().resolve()
               for role in ("baseline", "current")}
    inputs = {key: str(getattr(args, key).expanduser().resolve())
              for key in ("audio", "request", "operator", "verifier")}
    settings = {key: getattr(args, key) for key in
                ("threads", "expected_ridges", "expected_groups", "expected_detail_plots",
                 "timeout_s", "poll_interval_s")}
    expected = {role: getattr(args, "expected_" + role + "_backend") for role in sources}
    runner = Path(__file__).with_name("benchmark_real_regional_upload.py").resolve()
    command = [sys.executable, str(runner)]
    common = [part for key, value in {**inputs, **settings}.items()
              for part in ("--" + key.replace("_", "-"), str(value))]
    summary = {"scope": __doc__.strip(), "requested_pairs": args.pairs, "trials": [],
               "sources": {role: str(path) for role, path in sources.items()}, "inputs": inputs,
               "settings": settings, "expected_backends": expected, "python_executable": sys.executable,
               "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None}
    environment_keys = ("python", "sqlite", "numerical_threads", "cpu_affinity", "numerical_package_versions")
    common_keys = (*environment_keys, "audio_sha256", "audio_bytes", "request_sha256", "operator_sha256",
                   "verifier_sha256", "expected_detail_plots", "source_detail_plot_default")
    implementation_keys = ("source_revision", "tracked_src_sha256", "tracked_src_file_count",
                           "backend_kind", "ridge_fit_backend", "native_binary_sha256", "native_binaries")
    common_identity, implementations = None, {}
    output.mkdir(parents=True)
    (output / "logs").mkdir()
    save(output, summary)
    try:
        for number in range(1, args.pairs + 1):
            order = ["baseline", "current"] if number % 2 else ["current", "baseline"]
            trial = {"pair": number, "order": order, "arms": {}, "exact_comparison": False}
            summary["trials"].append(trial)
            for role in order:
                label = f"pair-{number:03d}-{role}"
                arm = output / label
                record = trial["arms"][role] = {"output": str(arm), "timing": str(arm / "timing.json")}
                save(output, summary)
                run(command + common + ["--source", str(sources[role]), "--output", str(arm),
                    "--expected-backend", expected[role]], output, label, record)
                timing = json.loads((arm / "timing.json").read_text())
                record.update({key: timing[key] for key in
                               ("wall_s", "cpu_s", "source_revision", "backend_kind", "ridge_fit_backend")})
                if any(not math.isfinite(record[key]) or record[key] <= 0 for key in ("wall_s", "cpu_s")):
                    raise ValueError(f"Invalid timing for {label}")
                identity = {key: timing[key] for key in common_keys}
                if common_identity is not None and identity != common_identity:
                    raise ValueError(f"Environment, input or verifier changed at {label}; pooling refused")
                common_identity = identity
                summary["environment"] = {key: timing[key] for key in environment_keys}
                implementation = {key: timing[key] for key in implementation_keys}
                if role in implementations and implementation != implementations[role]:
                    raise ValueError(f"{role} implementation changed at {label}; pooling refused")
                implementations[role] = implementation
                save(output, summary)
            comparison = output / f"pair-{number:03d}-comparison.json"
            record = trial["comparison"] = {"report": str(comparison)}
            run(command + ["--compare", *(trial["arms"][role]["output"] for role in ("baseline", "current")),
                "--output", str(comparison), "--expected-detail-plots", args.expected_detail_plots,
                "--expected-ridges", str(args.expected_ridges), "--expected-groups", str(args.expected_groups)],
                output, f"pair-{number:03d}-compare", record)
            report = json.loads(comparison.read_text())
            if report.get("passed") is not True or report["differences"]["count"] != 0:
                raise ValueError(f"Pair {number} did not preserve exact scientific outputs")
            trial["exact_comparison"] = True
            for metric in ("wall", "cpu"):
                trial[f"paired_{metric}_speedup"] = (
                    trial["arms"]["baseline"][metric + "_s"] / trial["arms"]["current"][metric + "_s"])
            save(output, summary)
    except (OSError, ValueError, KeyError, RuntimeError, KeyboardInterrupt) as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        save(output, summary)
        print(json.dumps({"summary": str(output / "summary.json"), "error": summary["error"]}), flush=True)
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    print(json.dumps({"summary": str(output / "summary.json"),
                      "exact_comparison_count": summary["exact_comparison_count"],
                      "statistics": summary["statistics"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
