r"""Compare search implementations in fresh processes using saved real inputs.

Inputs must be actual recorded ridges and observed aircraft trajectories. Saved
candidate positions/clocks are development hypotheses, not location truth. This
replays preparation and one scoring stage; it does not measure audio discovery,
downloads, a national search, or localization accuracy. No data are generated.

Example:
  python scripts/benchmark_real_optimization.py --baseline ../baseline \
    --tracks /path/reference-region.parquet --discovery /path/discovery.json \
    --candidate evidence/results/reference-local/report.json \
    --clock-radius-s 120 --output results/real-speed-comparison --profile
"""
import argparse
from contextlib import ExitStack
import cProfile
from importlib.metadata import version
import itertools
import json
import math
import os
from pathlib import Path
import pstats
import sqlite3
import statistics
import subprocess
import sys
import time
from unittest.mock import patch


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=True) + "\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=True)


def source_state(source):
    result = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    status = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--", "src"],
                            capture_output=True, text=True)
    return {"revision": result.stdout.strip() if result.returncode == 0 else None,
            "source_changes": status.stdout.splitlines() if status.returncode == 0 else None}


def worker(spec_path, output):
    spec = json.loads(spec_path.read_text())
    import numpy as np
    import pandas as pd
    import dopplergeist
    from dopplergeist import batch_ridge, matching, tiled_search
    from dopplergeist.finite_search import RetentionLedger
    from dopplergeist.geometry import Track
    from dopplergeist.tracks import load_tracks

    source = Path(spec["source"])
    module = Path(dopplergeist.__file__).resolve()
    if not module.is_relative_to(source / "src"):
        raise RuntimeError(f"Wrong implementation imported: {module}")
    output.mkdir(parents=True, exist_ok=False)
    implementation = source_state(source)
    runtime_versions = {"python": sys.version.split()[0], **{
        name: version(name) for name in ("numpy", "scipy", "pandas", "pyarrow", "pyproj")}}
    started, cpu = time.perf_counter(), time.process_time()
    discovery = json.loads(Path(spec["discovery"]).read_text())
    proposals = discovery["events"]
    events, measurements = matching.prepare_events(proposals)
    if not events:
        raise ValueError("The real discovery input has no events to score")
    point_path = Path(spec["candidate"] or spec["point_file"])
    if point_path.suffix.lower() == ".csv":
        raw = pd.read_csv(point_path).to_dict("records")
    else:
        raw = json.loads(point_path.read_text())
        if isinstance(raw, dict):
            raw = raw.get("ranked", raw.get("points", raw.get("best", raw)))
        raw = raw if isinstance(raw, list) else [raw]
    if spec["candidate"]:
        raw = [raw[spec["candidate_rank"] - 1]]
    if not raw:
        raise ValueError("No receiver hypotheses supplied")
    points = pd.DataFrame(raw)
    for name in ("lat", "lon", "elev_m"):
        if name not in points or not np.isfinite(points[name].to_numpy(dtype=float)).all():
            raise ValueError(f"Every saved receiver needs a finite {name}")
    if "point_id" not in points:
        points["point_id"] = np.arange(len(points))
    if not points.point_id.is_unique:
        raise ValueError("Saved receiver point IDs must be unique")
    if "x" not in points or "y" not in points:
        from pyproj import Transformer
        points["x"], points["y"] = Transformer.from_crs(
            "EPSG:4326", "EPSG:5070", always_xy=True).transform(points.lon, points.lat)
    window = spec["clock_window"]
    if window is None:
        clocks = {row.get("recording_start_time_s") for row in raw}
        if None in clocks or len(clocks) != 1:
            raise ValueError("Supply --clock-window or saved hypotheses with one shared clock")
        clock = float(clocks.pop())
        window = [clock - spec["clock_radius_s"], clock + spec["clock_radius_s"]]
    if not all(math.isfinite(t) for t in window) or window[0] > window[1]:
        raise ValueError("Recording clock bounds must be finite and ordered")
    measured_end = max(float(event["end_s"]) for event in proposals)
    duration = spec["recording_duration_s"]
    if duration is None:
        # This bounds the measured support needed by this scorer, not the length
        # of the original recording or its discovery coverage.
        duration = measured_end
    if duration < measured_end:
        raise ValueError("Recording duration ends before a measured event")
    track_window = [window[0] - spec["time_padding_s"],
                    window[1] + duration + spec["time_padding_s"]]
    prepare = {"wall_s": time.perf_counter() - started, "cpu_s": time.process_time() - cpu}
    started, cpu = time.perf_counter(), time.process_time()
    tracks, imported = load_tracks(spec["tracks"], time_range=track_window)
    load = {"wall_s": time.perf_counter() - started, "cpu_s": time.process_time() - cpu}
    if not tracks:
        raise ValueError("No observed trajectories overlap the requested workload")
    budget = tiled_search.SearchBudget(top_k=spec["top_k"],
                                      max_candidates_per_tile=spec["max_candidates"])
    settings = {"mode": "robust_ridge", "time_sweep_s": spec["time_sweep_s"],
                "time_step_s": spec["time_step_s"]}
    if window[0] == window[1]:
        settings.update(time_origin=window[0], time_sweep_s=0.0)
    ledger = RetentionLedger(output / "retention.sqlite", "real-optimization-comparison",
                             "matched_group_support_minus_normalized_residual")
    operations = {"scalar_source_fit_calls": 0, "scalar_batch_validation_calls": 0,
                  "batch_fit_attempts": 0, "batch_fit_successes": 0, "batched_clock_fits": 0,
                  "acoustic_calls": 0, "acoustic_samples": 0}
    phases = {}

    def measured(function, name):
        phases[name] = {"calls": 0, "wall_s": 0.0, "cpu_s": 0.0}
        def wrapped(*args, **kwargs):
            began, used = time.perf_counter(), time.process_time()
            try:
                return function(*args, **kwargs)
            finally:
                phases[name]["calls"] += 1
                phases[name]["wall_s"] += time.perf_counter() - began
                phases[name]["cpu_s"] += time.process_time() - used
        return wrapped

    original_fit, original_acoustic = matching._fit_ridge_uncached, Track.acoustic
    original_validation = getattr(batch_ridge, "_fit_ridge_uncached", None)
    operations["scalar_validation_hook_present"] = original_validation is not None
    original_batch = batch_ridge.first_event_fits
    def fit(*args, **kwargs):
        operations["scalar_source_fit_calls"] += 1
        return original_fit(*args, **kwargs)

    def validation(*args, **kwargs):
        operations["scalar_source_fit_calls"] += 1
        operations["scalar_batch_validation_calls"] += 1
        return original_validation(*args, **kwargs)

    def batch_fit(*args, **kwargs):
        operations["batch_fit_attempts"] += 1
        result = original_batch(*args, **kwargs)
        if result is not None:
            operations["batch_fit_successes"] += 1
            operations["batched_clock_fits"] += len(result)
        return result

    def acoustic(track, receive, *args, **kwargs):
        operations["acoustic_calls"] += 1
        operations["acoustic_samples"] += np.asarray(receive).size
        return original_acoustic(track, receive, *args, **kwargs)

    profiler = cProfile.Profile() if spec["profile"] else None
    with ExitStack() as stack:
        stack.enter_context(patch.object(matching, "_fit_ridge_uncached", fit))
        if original_validation is not None:
            stack.enter_context(patch.object(batch_ridge, "_fit_ridge_uncached", validation))
        stack.enter_context(patch.object(batch_ridge, "first_event_fits", batch_fit))
        stack.enter_context(patch.object(Track, "acoustic", acoustic))
        for owner, name in ((tiled_search, "cpa_table"), (matching, "association_candidates"),
                            (tiled_search, "score_candidate")):
            stack.enter_context(patch.object(owner, name, measured(getattr(owner, name), name)))
        started, cpu = time.perf_counter(), time.process_time()
        if profiler:
            profiler.enable()
        try:
            ranked, counts = tiled_search._score(
                points, tracks, events, measurements, budget, settings, {},
                start_window=tuple(window), ledger=ledger, stage="coarse:real-replay")
        finally:
            if profiler:
                profiler.disable()
        score = {"wall_s": time.perf_counter() - started, "cpu_s": time.process_time() - cpu}
    if profiler:
        profiler.dump_stats(str(output / "score.prof"))
        with (output / "profile.txt").open("w") as stream:
            pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)
    # Keep scientific outputs separate from all measurements of execution time.
    write_json(output / "result.json", {"ranked": ranked, "counts": counts})
    report = {"source": str(source), **implementation, "runtime_versions": runtime_versions,
              "profiled": bool(profiler),
              "prepare": prepare, "load_tracks": load, "score": score,
              "phases_inclusive_do_not_sum": phases, "operations": operations,
              "workload": {"proposals": len(proposals), "groups": len(events), "points": len(points),
                           "tracks": len(tracks), "observations": imported["rows"],
                           "clock_window_s": window, "track_window_s": track_window,
                           "candidates": counts.get("candidates", 0), "retained": len(ranked)}}
    write_json(output / "timing.json", report)
    print(json.dumps({"run": output.name, "score": score, "workload": report["workload"]}), flush=True)


def compare_outputs(first, second):
    left, right = [json.loads((directory / "result.json").read_text()) for directory in (first, second)]
    checks = {name + "_exact": canonical(left[name]) == canonical(right[name])
              for name in ("ranked", "counts")}
    timings = [json.loads((directory / "timing.json").read_text()) for directory in (first, second)]
    checks["workload_exact"] = canonical(timings[0]["workload"]) == canonical(timings[1]["workload"])
    if all("runtime_versions" in item for item in timings):
        checks["runtime_versions_exact"] = timings[0]["runtime_versions"] == timings[1]["runtime_versions"]
    with sqlite3.connect(first / "retention.sqlite") as a, sqlite3.connect(second / "retention.sqlite") as b:
        for table, order in (("records", "stage,mode_id"), ("bounds", "stage,bound_id"), ("stages", "name")):
            query = f"SELECT * FROM {table} ORDER BY {order}"
            checks["ledger_" + table + "_exact"] = all(
                x == y for x, y in itertools.zip_longest(a.execute(query), b.execute(query)))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worker-spec", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--compare-results", type=Path, nargs=2, metavar=("BASELINE_RUN", "CURRENT_RUN"),
                        help="Compare saved worker outputs without repeating either computation")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Checkout root containing src/dopplergeist")
    parser.add_argument("--baseline", type=Path, help="Compare this checkout with --source")
    parser.add_argument("--dependencies", type=Path, action="append", default=[], help="Additional Python import directory")
    parser.add_argument("--tracks", type=Path)
    parser.add_argument("--discovery", type=Path)
    point = parser.add_mutually_exclusive_group()
    point.add_argument("--candidate", type=Path, help="Saved ranked JSON, report with best, or one candidate")
    point.add_argument("--point-file", type=Path, help="Saved receiver points, JSON or CSV, with elevations")
    parser.add_argument("--candidate-rank", type=int, default=1)
    clock = parser.add_mutually_exclusive_group()
    clock.add_argument("--clock-window", type=float, nargs=2, metavar=("START_UNIX", "END_UNIX"))
    clock.add_argument("--clock-radius-s", type=float, default=0.0, help="Around the candidate's shared clock")
    parser.add_argument("--recording-duration-s", type=float, help="Otherwise load through the last measured event")
    parser.add_argument("--time-padding-s", type=float, default=120.0)
    parser.add_argument("--time-sweep-s", type=float, default=5.0)
    parser.add_argument("--time-step-s", type=float, default=0.5)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--max-candidates", type=int, default=20000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--profile", action="store_true", help="Extra fresh profiled run, excluded from timing medians")
    parser.add_argument("--timeout-s", type=float, default=1800.0, help="Each child process deadline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.worker_spec:
        worker(args.worker_spec, args.worker_output)
        return
    if args.compare_results:
        checks = compare_outputs(*args.compare_results)
        timings = [json.loads((directory / "timing.json").read_text()) for directory in args.compare_results]
        print(json.dumps({"checks": checks, "score_speedup": {
            name: timings[0]["score"][name] / timings[1]["score"][name]
            for name in ("wall_s", "cpu_s")}}, indent=2))
        if not all(checks.values()):
            raise SystemExit("Saved outputs or workloads differ")
        return
    if not args.tracks or not args.discovery or not (args.candidate or args.point_file) or not args.output:
        parser.error("--tracks, --discovery, --candidate/--point-file and --output are required")
    if min(args.repeats, args.candidate_rank, args.top_k, args.max_candidates) < 1:
        parser.error("Repeats, rank, top-k and candidate budget must be positive")
    for name in ("clock_radius_s", "time_padding_s", "time_sweep_s", "time_step_s", "timeout_s"):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0 or (name in ("time_step_s", "timeout_s") and value == 0):
            parser.error(f"Invalid --{name.replace('_', '-')}")
    if args.recording_duration_s is not None and (
            not math.isfinite(args.recording_duration_s) or args.recording_duration_s <= 0):
        parser.error("Recording duration must be finite and positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = {name: getattr(args, name) for name in (
        "candidate_rank", "clock_window", "clock_radius_s", "recording_duration_s", "time_padding_s",
        "time_sweep_s", "time_step_s", "top_k", "max_candidates")}
    settings.update({name: str(getattr(args, name).resolve()) if getattr(args, name) else None
                     for name in ("tracks", "discovery", "candidate", "point_file")})
    sources = {"baseline": args.baseline.resolve(), "optimized": args.source.resolve()} if args.baseline else {
        "current": args.source.resolve()}
    runs, comparisons, first, runtimes = [], [], {}, []

    def compare_runs(left, right):
        checks = compare_outputs(left, right)
        comparisons.append({"left": left.name, "right": right.name, **checks})
        if not all(checks.values()):
            write_json(output / "comparison.json", {"inputs": settings, "runs": runs,
                       "runtime_versions": runtimes[0] if runtimes else None,
                       "comparisons": comparisons, "exact_outputs_equal": False})
            raise SystemExit("Outputs differ; stopped repetitions. Inspect comparison.json")

    def run(label, index, profile=False):
        directory = output / (f"{label}-profile" if profile else f"{label}-{index + 1}")
        spec = dict(settings, source=str(sources[label]), profile=profile)
        spec_path = output / (directory.name + "-input.json")
        write_json(spec_path, spec)
        env = dict(os.environ)
        paths = [str(sources[label] / "src"), *[str(path.resolve()) for path in args.dependencies]]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env.update(PYTHONPATH=os.pathsep.join(paths), MPLBACKEND="Agg", OPENBLAS_NUM_THREADS="1",
                   OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
        began = time.perf_counter()
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker-spec", str(spec_path),
                        "--worker-output", str(directory)], check=True, env=env, timeout=args.timeout_s)
        report = json.loads((directory / "timing.json").read_text())
        runtimes.append(report.pop("runtime_versions"))
        report.update(label=label, run=directory.name, process_wall_s=time.perf_counter() - began)
        runs.append(report)
        if label in first:
            compare_runs(first[label], directory)
        else:
            first[label] = directory
        return directory

    for repeat in range(args.repeats):
        order, latest = list(sources), {}
        for label in order if repeat % 2 == 0 else reversed(order):
            latest[label] = run(label, repeat)
        if args.baseline:
            compare_runs(latest["baseline"], latest["optimized"])
    if args.profile:
        for label in sources:
            run(label, 0, profile=True)
    medians = {}
    for label in sources:
        selected = [run for run in runs if run["label"] == label and not run["profiled"]]
        medians[label] = {name: statistics.median(run["score"][name] for run in selected)
                          for name in ("wall_s", "cpu_s")}
        medians[label]["process_wall_s"] = statistics.median(run["process_wall_s"] for run in selected)
    same = all(value for check in comparisons for key, value in check.items() if key.endswith("_exact"))
    summary = {"scope": "fixed real-input computation replay; no location-accuracy or national-runtime claim",
               "inputs": settings, "runs": runs, "score_medians": medians,
               "runtime_versions": runtimes[0],
               "comparisons": comparisons, "exact_outputs_equal": same if comparisons else None}
    if args.baseline:
        summary["score_speedup"] = {name: medians["baseline"][name] / medians["optimized"][name]
                                    for name in ("wall_s", "cpu_s")}
    write_json(output / "comparison.json", summary)
    print(json.dumps({"output": str(output), "score_medians": medians,
                      "exact_outputs_equal": summary["exact_outputs_equal"]}), flush=True)
    if not same:
        raise SystemExit("Outputs differ; inspect comparison.json before claiming an equivalent speedup")


if __name__ == "__main__":
    main()
