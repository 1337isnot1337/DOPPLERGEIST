"""Run one fresh regional HTTP arm, or compare two completed arms.

Use the same audio, request, operator, interpreter and verifier for both arms.
The reference control expects 17 ridges in 15 groups. Original detail plots
remain the default control; --expected-detail-plots none explicitly selects the
current source default. Both arms must use the same plotting policy.
This measures regional runtime, not accuracy or nationwide completion.
--check-inputs performs no upload or numerical fit.
--compare requires matched controls before the strict scientific comparison.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
from importlib.machinery import EXTENSION_SUFFIXES
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


def frozen_source_identity(source):
    """Require tracked src bytes to match one commit, allowing built extensions."""
    source = source.resolve()
    root = Path(os.fsdecode(subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"])).rstrip("\n"))

    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])

    relative = source.relative_to(root).as_posix()
    revision = git("rev-parse", "HEAD").decode().strip()
    if git("status", "--porcelain", "--untracked-files=no", "--", relative):
        raise ValueError("Benchmark src has uncommitted tracked changes")
    algorithm = git("rev-parse", "--show-object-format").decode().strip()
    tracked, digest = set(), hashlib.sha256()
    for entry in git("ls-tree", "-rz", revision, "--", relative).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, expected = metadata.split()
        path = root / os.fsdecode(name)
        if kind != b"blob" or mode not in (b"100644", b"100755") or path.is_symlink():
            raise ValueError(f"Unsupported tracked source entry: {path}")
        data = path.read_bytes()
        actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected.decode():
            raise ValueError(f"Tracked source differs from its frozen commit: {path}")
        tracked.add(path)
        digest.update(name + b"\0" + hashlib.sha256(data).digest())
    python_files = set((source / "dopplergeist").rglob("*.py"))
    if not tracked or not python_files or python_files - tracked:
        raise ValueError("Benchmark package contains untracked Python source")
    return {"source_revision": revision, "tracked_src_sha256": digest.hexdigest(),
            "tracked_src_file_count": len(tracked)}


def detail_plot_default(source):
    tree = ast.parse((source / "dopplergeist/discovery.py").read_text())
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "discover_events"]
    if len(definitions) != 1:
        raise ValueError("Cannot identify the source discover_events definition")
    discover = definitions[0]
    positional = discover.args.posonlyargs + discover.args.args
    defaults = (dict(zip((arg.arg for arg in positional[-len(discover.args.defaults):]),
                         discover.args.defaults)) if discover.args.defaults else {})
    defaults.update(zip((arg.arg for arg in discover.args.kwonlyargs), discover.args.kw_defaults))
    if "plot_event_details" not in {arg.arg for arg in positional + discover.args.kwonlyargs}:
        return "all"  # Legacy sources wrote every event plot without an option.
    default = defaults.get("plot_event_details")
    if not isinstance(default, ast.Constant) or type(default.value) is not bool:
        raise ValueError("The source detail-plot default must be a literal boolean")
    return "all" if default.value else "none"


def backend_identity(source):
    from dopplergeist import matching

    package = source / "dopplergeist"
    if Path(matching.__file__).resolve().parent != package:
        raise ValueError("Imported matching code from another source tree")
    binaries = {path.name: sha256(path) for suffix in EXTENSION_SUFFIXES
                if (path := package / ("_native_ridge" + suffix)).is_file()}
    native = getattr(matching, "_native_ridge_module", None)
    declared = getattr(matching, "RIDGE_FIT_BACKEND", "python-irls-v1")
    binary_hash = None
    if native is not None:
        loaded = Path(native.__file__).resolve()
        if loaded not in {(package / name).resolve() for name in binaries}:
            raise ValueError("Loaded a native backend outside the selected binary inventory")
        binary_hash = sha256(loaded)
        if not declared.endswith(":" + binary_hash):
            raise ValueError("Loaded native backend identity does not match its binary")
    return {"backend_kind": "native" if native is not None else "python",
            "ridge_fit_backend": declared, "native_binary_sha256": binary_hash,
            "native_binaries": binaries}


def implementation_identity(source, verifier):
    return {**frozen_source_identity(source), **backend_identity(source), "verifier_sha256": sha256(verifier)}


def assess_output(output, receipt, expected_ridges, expected_groups, expected_detail_plots="all"):
    if expected_detail_plots not in ("all", "none"):
        raise ValueError("Unknown detail-plot policy")
    final_path = output / "result.json"
    final = json.loads(final_path.read_text()) if final_path.exists() else {}
    events = final.get("events", [])
    groups = len({event.get("harmonic_group_id", event["event_id"]) for event in events})
    job = output / "jobs" / receipt.get("job_id", "missing")
    search_path = job / "search/search-report.json"
    search = json.loads(search_path.read_text()) if search_path.exists() else {}
    detail_names = {f"{event['event_id']}.png" for event in events}
    written_names = {path.name for path in (job / "discovery").glob("event-*.png") if path.is_file()}
    written_names.update(name for name in detail_names if (job / "discovery" / name).is_file())
    expected_names = detail_names if expected_detail_plots == "all" else set()
    counts_match = len(events) == expected_ridges and groups == expected_groups
    all_groups = (search.get("all_event_groups_considered") is True
                  and search.get("event_groups_proposed") == groups)
    passed = bool(receipt.get("verification_passed") and receipt.get("full_pipeline_requirements_met")
                  and counts_match and all_groups and written_names == expected_names)
    return {"control_passed": passed, "event_count": len(events), "independent_groups": groups,
            "expected_recording_counts_met": counts_match, "all_groups_considered": all_groups,
            "event_detail_png_count": len(written_names), "expected_detail_plots": expected_detail_plots,
            "verification_passed": receipt.get("verification_passed", False)}


def compare_arms(paths, output, expected_ridges, expected_groups, expected_detail_plots="all", expected_backend="any"):
    if output.exists():
        raise FileExistsError("Use a new comparison output path")
    controls = [json.loads((path / "timing.json").read_text()) for path in paths]
    if not all(control.get("control_passed") is True and control.get("returncode") == 0
               and control.get("fresh_run") is True and control.get("resumed") is False
               and control.get("implementation_unchanged") is True for control in controls):
        raise ValueError("Both arms must pass their completed fresh-run control gates")
    for key in ("python", "sqlite", "numerical_threads", "cpu_affinity", "numerical_package_versions",
                "expected_detail_plots", "source_detail_plot_default"):
        if any(key not in control for control in controls) or controls[0][key] != controls[1][key]:
            raise ValueError(f"Paired runtime control differs or is missing: {key}")
    if any(control["expected_detail_plots"] != expected_detail_plots
           or control["source_detail_plot_default"] != expected_detail_plots for control in controls):
        raise ValueError("Paired plotting policy differs from --expected-detail-plots")
    for control in controls:
        after = control.get("implementation_after", {})
        keys = ("source_revision", "tracked_src_sha256", "tracked_src_file_count", "backend_kind",
                "ridge_fit_backend", "native_binary_sha256", "native_binaries", "verifier_sha256")
        if not all(key in control and key in after and control[key] == after[key] for key in keys):
            raise ValueError("An arm lacks matching before/after implementation identities")
        if control["backend_kind"] not in ("python", "native") or (
                expected_backend != "any" and control["backend_kind"] != expected_backend):
            raise ValueError("An arm differs from --expected-backend")
    comparator = load_script("regional_upload_comparator", Path(__file__).with_name("compare_real_upload_performance.py"))
    runs = [comparator.Run(path) for path in paths]
    for key in ("source_sha256", "source_bytes", "request", "verifier_sha256", "python_executable", "python_version"):
        if any(key not in run.receipt for run in runs) or runs[0].receipt[key] != runs[1].receipt[key]:
            raise ValueError(f"Paired input/verifier identity differs or is missing: {key}")
    if any(run.receipt["verifier_sha256"] != control["verifier_sha256"] for run, control in zip(runs, controls)):
        raise ValueError("The executed verifier differs from the frozen control")
    operators = [json.loads((path / "operator.json").read_text()) for path in paths]
    if operators[0] != operators[1]:
        raise ValueError("Paired operator configurations differ")
    checks = [assess_output(path, run.receipt, expected_ridges, expected_groups, expected_detail_plots)
              for path, run in zip(paths, runs)]
    if not all(check["control_passed"] for check in checks):
        raise ValueError("A completed arm does not preserve all expected groups and detail plots")
    report = comparator.compare_runs(*paths)
    report["regional_control"] = {"passed": True, "arms": checks,
                                  "source_revisions": [control["source_revision"] for control in controls]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"report": str(output), "paired_control_passed": report["passed"],
                      "semantic_differences": report["differences"]["count"],
                      "verified_full_workflow_speedup": report["verified_full_workflow_speedup"]}))
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Frozen checkout's src/ directory")
    parser.add_argument("--audio", type=Path, help="One common complete MP3 for both arms")
    parser.add_argument("--request", type=Path, help="Shared region and recording-start window")
    parser.add_argument("--operator", type=Path, help="Shared offline index, terrain and search settings")
    parser.add_argument("--verifier", type=Path, help="One common verify_upload_http.py for both arms")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BASELINE", "CURRENT"),
                        help="Check paired controls and compare two completed run directories")
    parser.add_argument("--output", type=Path, required=True,
                        help="New run directory, or a new JSON report with --compare")
    parser.add_argument("--expected-audio-sha256", help="Optional measured-input identity; encoder builds can change bytes")
    parser.add_argument("--expected-ridges", type=int, default=17)
    parser.add_argument("--expected-groups", type=int, default=15)
    parser.add_argument("--expected-detail-plots", choices=("all", "none"), default="all")
    parser.add_argument("--expected-backend", choices=("any", "python", "native"), default="any")
    parser.add_argument("--timeout-s", type=float, default=7200)
    parser.add_argument("--poll-interval-s", type=float, default=0.25)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--check-inputs", action="store_true", help="Validate setup without running HTTP")
    args = parser.parse_args()
    if min(args.threads, args.expected_ridges, args.expected_groups) < 1 or any(
            not math.isfinite(value) or value <= 0 for value in (args.timeout_s, args.poll_interval_s)):
        parser.error("Counts, thread limits, timeout and polling interval must be positive")
    if args.compare:
        if any((args.source, args.audio, args.request, args.operator, args.verifier, args.check_inputs,
                args.expected_audio_sha256)):
            parser.error("--compare cannot be combined with run input flags")
        return compare_arms([path.resolve() for path in args.compare], args.output.resolve(),
                            args.expected_ridges, args.expected_groups, args.expected_detail_plots, args.expected_backend)
    if not all((args.source, args.audio, args.request, args.operator)):
        parser.error("A run requires --source, --audio, --request and --operator")
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
    frozen = frozen_source_identity(source)
    plot_default = detail_plot_default(source)
    if plot_default != args.expected_detail_plots:
        parser.error("Source detail-plot default differs from --expected-detail-plots")
    os.environ.update({key: str(args.threads) for key in
                       ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")})
    sys.path.insert(0, str(source))
    import dopplergeist
    from dopplergeist.contracts import validate_request
    if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
        raise RuntimeError("Imported a different dopplergeist source tree")
    validate_request(dict(request, audio_path=str(audio)))
    backend = backend_identity(source)
    if args.expected_backend != "any" and backend["backend_kind"] != args.expected_backend:
        parser.error("Loaded ridge fitter differs from --expected-backend")
    verifier_path = (args.verifier or Path(__file__).with_name("verify_upload_http.py")).resolve()
    if not verifier_path.is_file():
        parser.error("The selected verifier file does not exist")
    before = {**frozen, **backend, "verifier_sha256": sha256(verifier_path)}
    identity = {**before, "audio_sha256": digest, "audio_bytes": audio.stat().st_size,
                "request_sha256": sha256(args.request), "operator_sha256": sha256(args.operator),
                "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                "numerical_package_versions": {name: importlib.metadata.version(name) for name in
                    ("numpy", "scipy", "pandas", "pyarrow", "pyproj", "rasterio", "soundfile")},
                "numerical_threads": args.threads, "expected_detail_plots": args.expected_detail_plots,
                "source_detail_plot_default": plot_default, "expected_backend": args.expected_backend}
    if args.check_inputs:
        print(json.dumps({"inputs_valid": True, "http_started": False, **identity}, indent=2))
        return 0
    verifier = load_script("regional_upload_verifier", verifier_path)
    started, cpu_started = time.perf_counter(), cpu_seconds()
    receipt = verifier.verify_http(audio, output, request=request, operator=operator,
        expect_status="inconclusive", expect_reason="search_incomplete", timeout_s=args.timeout_s,
        poll_interval_s=args.poll_interval_s, require_full_pipeline=True)
    assessment = assess_output(output, receipt, args.expected_ridges, args.expected_groups, args.expected_detail_plots)
    try:
        after = implementation_identity(source, verifier_path)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        after = {"error": str(error)}
    unchanged = before == after and receipt.get("verifier_sha256") == before["verifier_sha256"]
    assessment["control_passed"] = assessment["control_passed"] and unchanged
    timing = {"scope": "Fresh complete-HTTP regional control; source-informed bounds/clock, no location-accuracy claim",
              "timing_scope": "HTTP verification and output/control checks; initial input checks and imports excluded",
              **identity, **assessment, "wall_s": time.perf_counter() - started,
              "cpu_s": cpu_seconds() - cpu_started, "implementation_after": after,
              "implementation_unchanged": unchanged,
              "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
              "fresh_run": True, "resumed": False, "returncode": 0 if assessment["control_passed"] else 1}
    (output / "timing.json").write_text(json.dumps(timing, indent=2) + "\n")
    print(json.dumps(timing, indent=2), flush=True)
    return timing["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
