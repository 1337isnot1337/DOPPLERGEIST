"""Compare fresh bounded real-recording HTTP uploads from two source checkouts.

Supply one shared input directory: recording.mp3, request.json, and operator.json.
The existing bounded-upload runner fixes the archived regional workload and
requires an inconclusive/search_incomplete result. This measures runtime and
exact output parity, not localization accuracy or national coverage.

Every pair uses fresh services and jobs. Pair order alternates baseline/current
then current/baseline. Both existing scientific and array comparators must pass.
Use a new output directory; keep inputs and both source checkouts unchanged.
Dependencies come from the active Python environment and inherited PYTHONPATH.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time


SCRIPTS = Path(__file__).resolve().parent
ARMS = ("baseline", "current")
THREAD_CONTROLS = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
COMPARATORS = (
    ("science", "compare_real_upload_performance.py"),
    ("arrays", "check_real_upload_arrays.py"),
)


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def read_json(path):
    return json.loads(path.read_text())


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


def stop_runner(process):
    """Let the existing verifier stop its service and preserve its receipt."""
    if process.poll() is not None:
        return
    # The verifier records SIGTERM and protects service teardown from repeated
    # signals. A raw SIGINT would bypass its final receipt write.
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_arm(pair, name, source, args, env, runs):
    destination = args.output / f"{pair}-{name}"
    log = args.output / f"{pair}-{name}.log"
    command = [sys.executable, str(SCRIPTS / "benchmark_real_bounded_upload.py"),
               "--source", str(source), "--inputs", str(args.inputs),
               "--output", str(destination), "--timeout-s", str(args.timeout_s)]
    row = {"pair": pair, "source": name, "output": str(destination),
           "log": str(log), "command": command,
           "receipt": str(destination / "http-verification.json")}
    runs.append(row)
    emit({"starting": row})
    with log.open("x") as stream:
        process = subprocess.Popen(command, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        previous = None
        # The verifier deadline starts after imports. Bound startup and final
        # verification too, then request its normal SIGTERM service cleanup.
        deadline = time.monotonic() + args.timeout_s + 60.0
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Pair {pair} {name} exceeded its verifier timeout plus 60 seconds")
                history = destination / "history.jsonl"
                if history.exists():
                    lines = history.read_text().splitlines()
                    if lines:
                        try:
                            result = json.loads(lines[-1])["result"]
                            state = (result.get("status"), result.get("stage"))
                            if state != previous:
                                emit({"pair": pair, "source": name,
                                      "status": state[0], "stage": state[1]})
                                previous = state
                        except (json.JSONDecodeError, KeyError):
                            # The verifier can be between writes to its last line.
                            pass
                time.sleep(1)
        finally:
            try:
                stop_runner(process)
            finally:
                row["returncode"] = process.returncode
    receipt_path = destination / "http-verification.json"
    receipt = read_json(receipt_path) if receipt_path.exists() else {}
    for key in ("elapsed_s", "verification_passed", "status", "reason_code",
                "candidate_count", "event_count", "full_pipeline_observed",
                "full_pipeline_requirements_met"):
        row[key] = receipt.get(key)
    row["receipt"] = str(receipt_path)
    if process.returncode:
        raise RuntimeError(f"Pair {pair} {name} runner failed; see {log}")
    if not all(receipt.get(key) is True for key in
               ("verification_passed", "full_pipeline_observed", "full_pipeline_requirements_met")):
        raise RuntimeError(f"Pair {pair} {name} did not verify the full workflow; see {receipt_path}")
    elapsed = receipt.get("elapsed_s")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed <= 0:
        raise RuntimeError(f"Pair {pair} {name} has no finite positive elapsed time")
    emit({"completed": row})
    return receipt


def compare_pair(pair, args, env, comparisons):
    for kind, filename in COMPARATORS:
        report_path = args.output / f"{pair}-{kind}.json"
        log = args.output / f"{pair}-{kind}.log"
        command = [sys.executable, str(SCRIPTS / filename),
                   "--baseline", str(args.output / f"{pair}-baseline"),
                   "--current", str(args.output / f"{pair}-current"),
                   "--output", str(report_path)]
        row = {"pair": pair, "kind": kind, "passed": False,
               "report": str(report_path), "log": str(log), "command": command}
        comparisons.append(row)
        with log.open("x") as stream:
            result = subprocess.run(command, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=args.timeout_s)
        row["returncode"] = result.returncode
        if report_path.exists():
            row["passed"] = read_json(report_path).get("passed") is True
        if result.returncode or not row["passed"]:
            raise RuntimeError(f"Pair {pair} {kind} exact comparison failed; see {report_path} and {log}")
        emit(row)


def summarize(report):
    samples = {name: [row["elapsed_s"] for row in report["runs"]
                      if row["source"] == name and row.get("verification_passed") is True
                      and isinstance(row.get("elapsed_s"), (int, float))
                      and not isinstance(row["elapsed_s"], bool)
                      and math.isfinite(row["elapsed_s"]) and row["elapsed_s"] > 0]
               for name in ARMS}
    medians = {name: statistics.median(values) if values else None
               for name, values in samples.items()}
    report["wall_seconds_samples"] = samples
    report["wall_seconds_median"] = medians
    report["wall_seconds_range"] = {
        name: [min(values), max(values)] if values else None for name, values in samples.items()}
    passed = (report["completed"] and len(report["comparisons"]) == 2 * report["repeats"]
              and all(row["passed"] for row in report["comparisons"]))
    report["all_exact_comparisons_passed"] = passed
    report["speedup"] = medians["baseline"] / medians["current"] if passed else None
    report["wall_reduction_fraction"] = 1 - medians["current"] / medians["baseline"] if passed else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True, help="Pinned checkout's src directory")
    parser.add_argument("--current-source", type=Path, required=True, help="Candidate checkout's src directory")
    parser.add_argument("--inputs", type=Path, required=True, help="Shared real recording and JSON configuration directory")
    parser.add_argument("--output", type=Path, required=True, help="New comparison directory; existing results are preserved")
    parser.add_argument("--repeats", type=positive_int, default=3, help="Alternating paired repetitions (default: 3)")
    parser.add_argument("--timeout-s", type=positive_seconds, default=900.0,
                        help="Verifier and comparator timeout; upload runners have a 60-second startup/finalization margin")
    args = parser.parse_args(argv)
    args.inputs, args.output = args.inputs.resolve(), args.output.resolve()
    sources = {name: getattr(args, f"{name}_source").resolve() for name in ARMS}
    required = [args.inputs / name for name in ("recording.mp3", "request.json", "operator.json")]
    required += [SCRIPTS / "benchmark_real_bounded_upload.py"]
    required += [SCRIPTS / filename for _, filename in COMPARATORS]
    for source in sources.values():
        required += [source / "dopplergeist/__init__.py", source.parent / "scripts/verify_upload_http.py"]
    for path in required:
        if not path.is_file():
            parser.error(f"Required input or source file is missing: {path}")
    if args.output.exists():
        parser.error(f"Use a new output directory: {args.output}")
    settings = {name: (args.inputs / name).read_bytes() for name in ("request.json", "operator.json")}
    for name, data in settings.items():
        try:
            value = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            parser.error(f"Invalid {name}: {error}")
        if not isinstance(value, dict):
            parser.error(f"{name} must contain a JSON object")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **THREAD_CONTROLS)
    report = {
        "repeats": args.repeats, "timeout_s": args.timeout_s, "completed": False,
        "inputs": str(args.inputs), "sources": {name: str(path) for name, path in sources.items()},
        "runs": [], "comparisons": [],
        "controls": {"python_executable": sys.executable, "python_version": sys.version,
                     "thread_environment": THREAD_CONTROLS,
                     "runner_margin_s": 60, "interrupt_cleanup_limit_s": 35,
                     "cpu_affinity": "Inherited unchanged from the invoking process",
                     "dependencies": "Active Python environment and inherited PYTHONPATH"},
        "scope": "Fresh bounded regional HTTP uploads with source-informed receiver bounds and clock; expected inconclusive/search_incomplete. No localization accuracy claim.",
        "timing_scope": "Existing verifier elapsed_s includes the workflow and its verification. It excludes parent interpreter startup and the two cross-run comparators. Comparator phase observations have one-second polling uncertainty.",
        "cache_scope": "Fresh service and job per arm, shared recording and operator configuration. OS file caches are not flushed. Index preparation is outside this measurement.",
        "order": "Odd pairs: baseline,current. Even pairs: current,baseline.",
    }
    args.output.mkdir(parents=True, exist_ok=False)
    first_receipts = {}
    input_identity = None
    exit_code = 0
    previous_term = signal.getsignal(signal.SIGTERM)

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        for pair in range(1, args.repeats + 1):
            order = ARMS if pair % 2 else ARMS[::-1]
            for name in order:
                if any((args.inputs / filename).read_bytes() != data for filename, data in settings.items()):
                    raise RuntimeError("Input JSON configuration changed during the comparison")
                receipt = run_arm(pair, name, sources[name], args, env, report["runs"])
                identity = {key: receipt.get(key) for key in ("source_sha256", "source_bytes", "request")}
                if input_identity is None:
                    input_identity = identity
                elif identity != input_identity:
                    raise RuntimeError("Recording or request changed between uploads")
                if name in first_receipts:
                    for key in ("implementation_files", "verifier_sha256"):
                        if receipt.get(key) != first_receipts[name].get(key):
                            raise RuntimeError(f"The {name} implementation changed between repetitions")
                else:
                    first_receipts[name] = receipt
            compare_pair(pair, args, env, report["comparisons"])
        report["completed"] = True
    except (Exception, KeyboardInterrupt) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
        emit({"failed": report["error"], "output": str(args.output)})
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        summarize(report)
        with (args.output / "comparison.json").open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    emit({"report": str(args.output / "comparison.json"),
          **{key: report[key] for key in ("all_exact_comparisons_passed", "wall_seconds_median", "speedup")}})
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
