"""Run public requests without loading truth. Linux wait4 records per-case resources.

Example: run_benchmark.py inputs/manifest.json --output results/new -- \
    python run_one.py {request} {output}
The command must write a shared JobResult to {output}/result.json. No shell is used.
This is separation of inputs, not a sandbox for an adversarial search executable.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from dopplergeist.evaluation import sha256


def run(manifest_path, output, command):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    predictions = {}
    for case in manifest["cases"]:
        key = case["case_id"]
        if not key or Path(key).name != key or key in {".", ".."} or key in predictions:
            raise ValueError("Case IDs must be unique safe directory names")
        request_path = (manifest_path.parent / case["request"]).resolve()
        request = json.loads(request_path.read_text())
        # Reject label/hint fields before invoking any algorithm.
        from dopplergeist.contracts import validate_request
        request = validate_request(request)
        audio = (request_path.parent / request["audio_path"]).resolve()
        if sha256(audio) != case["audio_sha256"]:
            raise ValueError(f"Audio checksum mismatch: {key}")
        request["audio_path"] = str(audio)
        folder = output / key
        folder.mkdir()
        staged_request = folder / "request.json"
        staged_request.write_text(json.dumps(request, indent=2) + "\n")
        argv = [arg.replace("{request}", str(staged_request)).replace("{output}", str(folder)) for arg in command]
        began = time.monotonic()
        peak_memory = None
        exit_code = None
        with (folder / "process.log").open("wb") as log:
            try:
                process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
                _, status, usage = os.wait4(process.pid, 0)
                process.returncode = exit_code = os.waitstatus_to_exitcode(status)
                peak_memory = usage.ru_maxrss * 1024
            except OSError as exc:
                log.write(str(exc).encode())
        elapsed = time.monotonic() - began
        result_path = folder / "result.json"
        if exit_code != 0 or not result_path.exists():
            result = {"status": "failed", "reason_code": "benchmark_execution_failed"}
        else:
            try:
                from dopplergeist.contracts import validate_result
                result = validate_result(json.loads(result_path.read_text()))
                if result["status"] not in {"succeeded", "inconclusive", "failed", "needs_input", "cancelled"}:
                    raise ValueError("Benchmark worker did not finish with a terminal result")
            except (ValueError, KeyError, TypeError) as exc:
                result = {"status": "failed", "reason_code": "invalid_result", "message": str(exc)}
        result.update(runtime_s=elapsed, peak_memory_bytes=peak_memory,
                      exit_code=exit_code, request_sha256=sha256(staged_request),
                      audio_sha256=case["audio_sha256"])
        predictions[key] = result
        (output / "predictions.json").write_text(json.dumps(predictions, indent=2, allow_nan=False) + "\n")
        print(key, result["status"], flush=True)
    return predictions


def main():
    # Keep command arguments opaque to this parser.
    if "--" not in sys.argv:
        raise SystemExit("Specify an executable after --")
    boundary = sys.argv.index("--")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(sys.argv[1:boundary])
    command = sys.argv[boundary + 1:]
    if not command:
        parser.error("An executable is required after --")
    run(args.manifest, args.output, command)


if __name__ == "__main__":
    main()
