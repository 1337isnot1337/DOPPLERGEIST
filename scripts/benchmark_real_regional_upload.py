"""Run one fresh regional HTTP arm, or compare two completed arms.

Use the same audio, request, operator, interpreter and verifier for both arms.
The reference control expects 17 ridges in 15 groups. Both arms must use the
same detail-plot policy. It measures regional runtime, not location accuracy.
--check-inputs performs no upload or numerical fit.
--compare requires matched controls before the strict scientific comparison.
--allow-new-encoding explicitly declares a different MP3 encoding of the checked
reference WAV. Its event counts come from the paired complete runs, and cannot
inherit the historical MP3's counts or timings.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import sqlite3
import subprocess
import sys
import time

HISTORICAL_MP3_SHA256 = "707083f0344823eeea7f130faec6c22b6628b8b9fea04d026915d93df9a07b15"
REFERENCE_WAV_SHA256 = "262d9c4eba1c80657813c604140ba2afbbaabed2b3aebc833cba7cafdc005e9f"
REFERENCE_DURATION_S = 3600.1845


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def cpu_seconds():
    return sum(usage.ru_utime + usage.ru_stime for usage in
               (resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)))


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def detail_plot_policy(source):
    """Read the source's default without changing production discovery behavior."""
    tree = ast.parse((source / "dopplergeist/discovery.py").read_text())
    discover = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "discover_events")
    defaults = dict(zip((arg.arg for arg in discover.args.kwonlyargs), discover.args.kw_defaults))
    value = defaults.get("plot_event_details")
    if value is None:
        # Historical discovery always produced every event detail plot.
        return True
    if not isinstance(value, ast.Constant) or type(value.value) is not bool:
        raise ValueError("Discovery's detail-plot default must be an explicit boolean")
    return value.value


def assess_output(output, receipt, expected_ridges, expected_groups, detail_plots_enabled=True,
                  *, new_encoding=False):
    final_path = output / "result.json"
    final = json.loads(final_path.read_text()) if final_path.exists() else {}
    events = final.get("events", [])
    groups = len({event.get("harmonic_group_id", event["event_id"]) for event in events})
    job = output / "jobs" / receipt.get("job_id", "missing")
    search_path = job / "search/search-report.json"
    search = json.loads(search_path.read_text()) if search_path.exists() else {}
    plots = sum((job / "discovery" / f"{event['event_id']}.png").is_file() for event in events)
    counts_match = (bool(events) and groups > 0 if new_encoding else
                    len(events) == expected_ridges and groups == expected_groups)
    duration = final.get("recording", {}).get("duration_s")
    duration_matches = (isinstance(duration, (int, float)) and math.isfinite(duration)
                        and math.isclose(duration, REFERENCE_DURATION_S, rel_tol=0, abs_tol=0.00025))
    all_groups = (search.get("all_event_groups_considered") is True
                  and search.get("event_groups_proposed") == groups)
    passed = bool(receipt.get("verification_passed") and receipt.get("full_pipeline_requirements_met")
                  and counts_match and all_groups and (duration_matches or not new_encoding)
                  and plots == (len(events) if detail_plots_enabled else 0))
    return {"control_passed": passed, "event_count": len(events), "independent_groups": groups,
            "expected_recording_counts_met": None if new_encoding else counts_match,
            "nonempty_recording_counts": bool(events) and groups > 0,
            "reference_duration_met": duration_matches, "all_groups_considered": all_groups,
            "event_detail_png_count": plots, "detail_plots_enabled": detail_plots_enabled,
            "verification_passed": receipt.get("verification_passed", False)}


def compare_arms(paths, output, expected_ridges, expected_groups):
    if output.exists():
        raise FileExistsError("Use a new comparison output path")
    controls = [json.loads((path / "timing.json").read_text()) for path in paths]
    if not all(control.get("control_passed") is True and control.get("returncode") == 0
               and control.get("fresh_run") is True and control.get("resumed") is False for control in controls):
        raise ValueError("Both arms must pass their completed fresh-run control gates")
    for key in ("python", "sqlite", "numerical_threads", "cpu_affinity", "numerical_package_versions"):
        if any(key not in control for control in controls) or controls[0][key] != controls[1][key]:
            raise ValueError(f"Paired runtime control differs or is missing: {key}")
    recording_controls = [control.get("recording_control", "fixed_counts") for control in controls]
    if recording_controls[0] != recording_controls[1] or recording_controls[0] not in {"fixed_counts", "fresh_encoding"}:
        raise ValueError("Paired recording-control declarations differ or are invalid")
    new_encoding = recording_controls[0] == "fresh_encoding"
    if controls[0].get("ffmpeg_version") != controls[1].get("ffmpeg_version"):
        raise ValueError("Paired FFmpeg versions differ")
    # Older benchmark records required detail plots unconditionally.
    plot_policies = [control.get("detail_plots_enabled", True) for control in controls]
    if not all(type(policy) is bool for policy in plot_policies) or plot_policies[0] != plot_policies[1]:
        raise ValueError("Paired detail-plot policies differ or are invalid")
    comparator = load_script("regional_upload_comparator", Path(__file__).with_name("compare_real_upload_performance.py"))
    runs = [comparator.Run(path) for path in paths]  # Refuses active or unfinished workflows.
    for key in ("source_sha256", "source_bytes", "request", "verifier_sha256", "python_executable", "python_version"):
        if any(key not in run.receipt for run in runs) or runs[0].receipt[key] != runs[1].receipt[key]:
            raise ValueError(f"Paired input/verifier identity differs or is missing: {key}")
    for control, run in zip(controls, runs):
        if (control.get("audio_sha256") != run.receipt["source_sha256"]
                or control.get("audio_bytes") != run.receipt["source_bytes"]):
            raise ValueError("Timing metadata does not identify the verified audio input")
    historical_input = runs[0].receipt["source_sha256"] == HISTORICAL_MP3_SHA256
    if historical_input:
        if new_encoding or (expected_ridges, expected_groups) != (17, 15):
            raise ValueError("The historical MP3 retains its fixed 17-ridge/15-group control")
    if new_encoding and any(control.get("reference_wav_sha256") != REFERENCE_WAV_SHA256
                            or not control.get("ffmpeg_version") for control in controls):
        raise ValueError("New encodings require the canonical WAV identity and explicit FFmpeg runtime")
    operators = [json.loads((path / "operator.json").read_text()) for path in paths]
    if operators[0] != operators[1]:
        raise ValueError("Paired operator configurations differ")
    checks = [assess_output(path, run.receipt, expected_ridges, expected_groups, policy,
                            new_encoding=new_encoding)
              for path, run, policy in zip(paths, runs, plot_policies)]
    if not all(check["control_passed"] for check in checks):
        raise ValueError("A completed arm does not preserve all expected groups and its detail-plot policy")
    if any(checks[0][key] != checks[1][key] for key in ("event_count", "independent_groups")):
        raise ValueError("Paired recording counts differ")
    report = comparator.compare_runs(*paths)
    array_comparator = load_script("regional_array_comparator", Path(__file__).with_name("check_real_upload_arrays.py"))
    report["array_comparison"] = array_comparator.compare_runs(*paths)
    report["passed"] = report["passed"] and report["array_comparison"]["passed"]
    if not report["passed"]:
        report["verified_full_workflow_speedup"] = None
    report["regional_control"] = {"passed": True, "arms": checks,
                                  "recording_control": recording_controls[0],
                                  "historical_mp3_input": historical_input,
                                  "scope": ("New encoding: no historical event-count or timing claim"
                                            if new_encoding else "Fixed recorded-input count control"),
                                  "source_revisions": [control["source_revision"] for control in controls]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"report": str(output), "paired_control_passed": report["passed"],
                      "semantic_differences": report["differences"]["count"],
                      "array_differences": report["array_comparison"]["difference_count"],
                      "verified_full_workflow_speedup": report["verified_full_workflow_speedup"]}))
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Frozen checkout's src/ directory")
    parser.add_argument("--audio", type=Path, help="One common complete MP3 for both arms")
    parser.add_argument("--request", type=Path, help="Shared region and recording-start window")
    parser.add_argument("--operator", type=Path, help="Shared offline index, terrain and search settings")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BASELINE", "CURRENT"),
                        help="Check paired controls and compare two completed run directories")
    parser.add_argument("--output", type=Path, required=True,
                        help="New run directory, or a new JSON report with --compare")
    parser.add_argument("--expected-audio-sha256", help="Optional measured-input identity; encoder builds can change bytes")
    parser.add_argument("--allow-new-encoding", action="store_true",
                        help="Declare a fresh MP3 encoding; complete paired output parity remains mandatory")
    parser.add_argument("--reference-wav", type=Path,
                        help="Canonical real WAV used to produce a fresh MP3 encoding")
    parser.add_argument("--expected-ridges", type=int, default=17)
    parser.add_argument("--expected-groups", type=int, default=15)
    parser.add_argument("--timeout-s", type=float, default=7200)
    parser.add_argument("--poll-interval-s", type=float, default=0.25)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--cpu", type=int, help="Pin this arm and its child processes to one available CPU")
    parser.add_argument("--check-inputs", action="store_true", help="Validate setup without running HTTP")
    args = parser.parse_args()
    if min(args.threads, args.expected_ridges, args.expected_groups) < 1 or any(
            not math.isfinite(value) or value <= 0 for value in (args.timeout_s, args.poll_interval_s)):
        parser.error("Counts, thread limits, timeout and polling interval must be positive")
    if args.compare:
        if any((args.source, args.audio, args.request, args.operator, args.check_inputs, args.expected_audio_sha256,
                args.allow_new_encoding, args.reference_wav, args.cpu is not None)):
            parser.error("--compare cannot be combined with run input flags")
        return compare_arms([path.resolve() for path in args.compare], args.output.resolve(),
                            args.expected_ridges, args.expected_groups)
    if not all((args.source, args.audio, args.request, args.operator)):
        parser.error("A run requires --source, --audio, --request and --operator")
    if args.cpu is not None:
        if not hasattr(os, "sched_getaffinity") or args.cpu not in os.sched_getaffinity(0):
            parser.error("--cpu must identify an available CPU on a platform with affinity controls")
        os.sched_setaffinity(0, {args.cpu})
    source, audio, output = args.source.resolve(), args.audio.resolve(), args.output.resolve()
    if output.exists():
        parser.error("Use a new output directory")
    if not (source / "dopplergeist/__init__.py").is_file() or not audio.is_file() or audio.suffix.lower() != ".mp3":
        parser.error("Supply a dopplergeist src/ directory and an existing real MP3")
    request, operator = [json.loads(path.read_text()) for path in (args.request, args.operator)]
    if not isinstance(request, dict) or not isinstance(operator, dict):
        parser.error("Request and operator files must contain JSON objects")
    if "bounds_wsen" not in request.get("search", {}) or not request.get("time_window"):
        parser.error("Declare an explicit regional bound and recording-start window")
    if operator.get("filters", {}).get("max_events") is not None:
        parser.error("This whole-recording control does not permit an event cap")
    if operator.get("search_budget", {}).get("max_tiles") is not None:
        parser.error("This regional control does not permit a tile cap")
    terrain = operator.get("terrain", {})
    paths = [*operator.get("flight_indexes", []), *terrain.get("rasters", [])]
    if terrain.get("geoid_raster"):
        paths.append(terrain["geoid_raster"])
    if (operator.get("offline") is not True or not operator.get("flight_indexes")
            or not terrain.get("rasters") or any(not Path(path).is_file() for path in paths)):
        parser.error("Supply the shared restored offline index and terrain files")
    digest = sha256(audio)
    if args.expected_audio_sha256 and digest != args.expected_audio_sha256:
        parser.error("MP3 bytes differ from --expected-audio-sha256")
    if digest == HISTORICAL_MP3_SHA256 and (args.expected_ridges, args.expected_groups) != (17, 15):
        parser.error("The historical MP3 requires exactly 17 ridges and 15 groups")
    new_encoding = args.allow_new_encoding and digest != HISTORICAL_MP3_SHA256
    if new_encoding and args.reference_wav is None:
        parser.error("A new encoding requires its canonical --reference-wav")
    reference_digest = sha256(args.reference_wav) if args.reference_wav is not None else None
    if reference_digest is not None and reference_digest != REFERENCE_WAV_SHA256:
        parser.error("The encoding source differs from the canonical real reference WAV")
    plots_enabled = detail_plot_policy(source)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    os.environ.update({key: str(args.threads) for key in
                       ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    sys.path.insert(0, str(source))
    import dopplergeist
    from dopplergeist import geometry, matching
    from dopplergeist.contracts import validate_request
    if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
        raise RuntimeError("Imported a different dopplergeist source tree")
    validate_request(dict(request, audio_path=str(audio)))
    identity = {"source_revision": revision, "audio_sha256": digest, "audio_bytes": audio.stat().st_size,
                "request_sha256": sha256(args.request), "operator_sha256": sha256(args.operator),
                "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                "numerical_package_versions": {name: importlib.metadata.version(name) for name in
                    ("numpy", "scipy", "pandas", "pyarrow", "pyproj", "rasterio", "soundfile")},
                "numerical_threads": args.threads, "detail_plots_enabled": plots_enabled,
                "recording_control": "fresh_encoding" if new_encoding else "fixed_counts",
                "reference_wav_sha256": reference_digest,
                "ffmpeg_version": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
                "ridge_fit_backend": getattr(matching, "RIDGE_FIT_BACKEND", "python-irls-v1"),
                "acoustic_backend": getattr(geometry, "ACOUSTIC_BACKEND", "python-acoustic-v1")}
    if args.check_inputs:
        print(json.dumps({"inputs_valid": True, "http_started": False, **identity}, indent=2))
        return 0
    verifier_path = Path(__file__).with_name("verify_upload_http.py")
    verifier = load_script("regional_upload_verifier", verifier_path)
    started, cpu_started = time.perf_counter(), cpu_seconds()
    receipt = verifier.verify_http(audio, output, request=request, operator=operator,
        expect_status="inconclusive", expect_reason="search_incomplete", timeout_s=args.timeout_s,
        poll_interval_s=args.poll_interval_s, require_full_pipeline=True)
    assessment = assess_output(output, receipt, args.expected_ridges, args.expected_groups, plots_enabled,
                               new_encoding=new_encoding)
    timing = {"scope": "Fresh complete-HTTP regional control; source-informed bounds/clock, no location-accuracy claim",
              "timing_scope": "HTTP verification and output checks; input checks and imports excluded",
              **identity, **assessment, "wall_s": time.perf_counter() - started,
              "cpu_s": cpu_seconds() - cpu_started, "verifier_sha256": sha256(verifier_path),
              "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
              "fresh_run": True, "resumed": False, "returncode": 0 if assessment["control_passed"] else 1}
    (output / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    print(json.dumps(timing, indent=2), flush=True)
    return timing["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
