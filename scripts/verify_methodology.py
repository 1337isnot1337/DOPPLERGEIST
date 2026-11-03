#!/usr/bin/env python3
"""Measured codec and automatic-product acceptance checks; never fabricate a fix.

Each invocation creates a new output directory. Codec checks establish only
sample timing through the installed encoder/decoder, not location accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.metadata
import json
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import numpy as np
from scipy import signal
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def provenance():
    sources = list((ROOT / "src").rglob("*.py")) + [Path(__file__)]
    browser_helper = Path(__file__).with_name("verify_upload_browser.py")
    if browser_helper.is_file():
        sources.append(browser_helper)
    return {
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "working_tree": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).splitlines(),
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted(sources)},
        "python": sys.version,
        "platform": platform.platform(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "soundfile")
        },
        "ffmpeg": subprocess.check_output(
            ["ffmpeg", "-version"], text=True
        ).splitlines()[0],
    }


def run_command(command, directory, name):
    started = time.monotonic()
    with (directory / f"{name}.stdout").open("wb") as stdout, (
        directory / f"{name}.stderr"
    ).open("wb") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, check=False)
    record = {
        "command": list(map(str, command)),
        "returncode": result.returncode,
        "elapsed_s": time.monotonic() - started,
    }
    write_json(directory / f"{name}.command.json", record)
    if result.returncode:
        raise RuntimeError(f"{name} failed ({result.returncode}); see {name}.stderr")
    return record


def timing_offsets(reference, decoded, sample_rate_hz, centers_s, radius_s=0.25):
    """Find independent pilot offsets; positive means decoded content is later.

    A correlation floor prevents silence or unrelated decoded content from
    being reported as a valid clock measurement.
    """
    radius = round(radius_s * sample_rate_hz)
    offsets = []
    for center in centers_s:
        start = round((center - 0.75) * sample_rate_hz)
        stop = round((center + 0.75) * sample_rate_hz)
        if start < radius or stop + radius > len(decoded) or stop > len(reference):
            raise ValueError("Decoded audio does not contain every complete timing pilot")
        pilot = np.asarray(reference[start:stop], dtype=float)
        observed = np.asarray(decoded[start - radius:stop + radius], dtype=float)
        pilot -= pilot.mean()
        observed -= observed.mean()
        energy = np.dot(pilot, pilot)
        if energy < 1e-12:
            raise ValueError("Timing pilot has no usable signal")
        correlation = signal.correlate(observed, pilot, mode="valid", method="fft")
        energies = np.convolve(observed**2, np.ones(len(pilot)), mode="valid")
        normalized = correlation / np.sqrt(np.maximum(energies * energy, 1e-30))
        peak = int(np.argmax(normalized))
        coefficient = float(normalized[peak])
        if coefficient < 0.8 or peak in (0, 2 * radius):
            raise ValueError("Timing pilot is absent, distorted, or outside the measured range")
        offset = float(peak - radius)
        a, b, c = correlation[peak - 1:peak + 2]
        denominator = a - 2 * b + c
        if denominator:
            offset += float(0.5 * (a - c) / denominator)
        offsets.append({"center_s": center, "offset_s": offset / sample_rate_hz,
                        "correlation": coefficient})
    return offsets


def decode(source, target, directory, name, sample_rate_hz=4000):
    run_command(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(source),
         "-ac", "1", "-ar", str(sample_rate_hz), "-f", "f32le", str(target)],
        directory, name,
    )
    return np.fromfile(target, dtype="<f4")


def codec_audit(output):
    output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    rate = 24000
    duration_s = 45.375
    centers = [2.3, 18.7, 39.2]
    t = np.arange(round(rate * duration_s)) / rate
    rng = np.random.default_rng(902613)
    # The nonperiodic pilots make a half-cycle or MP3-frame shift observable.
    noise = signal.sosfilt(signal.butter(6, [150, 1300], fs=rate,
                                       btype="bandpass", output="sos"),
                           rng.normal(size=len(t)))
    envelope = sum(np.exp(-((t - center) / 0.45)**8) for center in centers)
    channel = 0.08 * np.sin(2 * np.pi * (170 * t - 0.5 * t**2)) + noise * envelope
    channel /= max(1.0, float(np.max(np.abs(channel))))
    source = output / "timing-source.wav"
    sf.write(source, np.column_stack((channel, 0.7 * channel)), rate, subtype="FLOAT")
    reference = decode(source, output / "reference.f32", output, "reference-decode")
    report = {
        "schema_version": 1, "scope": "codec_timing_only",
        "location_validation": False, "provenance": provenance(),
        "source_sha256": sha256(source), "reference_sample_rate_hz": 4000,
        "reference_samples": len(reference), "cases": [],
    }
    variants = [
        ("mono-8k-cbr16", 8000, 1, ["-b:a", "16k"], True),
        ("mono-16k-cbr32", 16000, 1, ["-b:a", "32k"], True),
        ("stereo-44k-cbr96", 44100, 2, ["-b:a", "96k"], True),
        ("stereo-48k-vbr", 48000, 2, ["-q:a", "4"], True),
        ("mono-16k-no-xing", 16000, 1, ["-b:a", "32k", "-write_xing", "0"], False),
    ]
    for name, encoded_rate, channels, options, gapless_expected in variants:
        row = {"name": name, "gapless_expected": gapless_expected,
               "encoded_sample_rate_hz": encoded_rate, "encoded_channels": channels}
        report["cases"].append(row)
        try:
            mp3 = output / f"{name}.mp3"
            run_command(["ffmpeg", "-v", "error", "-nostdin", "-i", str(source),
                         "-ar", str(encoded_rate), "-ac", str(channels),
                         "-c:a", "libmp3lame", *options, str(mp3)], output, name + "-encode")
            decoded = decode(mp3, output / f"{name}.f32", output, name + "-decode")
            offsets = timing_offsets(reference, decoded, 4000, centers)
            row.update({"mp3_sha256": sha256(mp3), "decoded_samples": len(decoded),
                        "duration_difference_s": (len(decoded) - len(reference)) / 4000,
                        "pilots": offsets,
                        "max_absolute_offset_s": max(abs(p["offset_s"]) for p in offsets),
                        "end_to_start_drift_s": offsets[-1]["offset_s"] - offsets[0]["offset_s"]})
            if gapless_expected:
                row["status"] = ("passed" if row["max_absolute_offset_s"] <= 0.002
                                 and abs(row["duration_difference_s"]) <= 0.002 else "failed")
            else:
                row["status"] = "diagnostic"
                row["limitation"] = "No gapless header: source sample zero is not recoverable from this MP3 alone."
        except (RuntimeError, ValueError) as exc:
            row.update(status="failed", error=str(exc))
        write_json(output / "report.json", report)
    report["elapsed_s"] = time.monotonic() - began
    report["passed"] = all(row["status"] != "failed" for row in report["cases"])
    write_json(output / "report.json", report)
    print(json.dumps({"report": str(output / "report.json"), "passed": report["passed"],
                      "cases": [{k: r[k] for k in ("name", "status")} for r in report["cases"]]}))
    return 0 if report["passed"] else 1


def get_json(url):
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def inspect_result(result, audio_hash, expected_status, expected_reason=None):
    from aircraft_geoloc.contracts import validate_result

    result = validate_result(result)
    if result["status"] != expected_status:
        raise ValueError(f"Expected {expected_status}, received {result['status']}: {result.get('reason_code')}")
    if expected_reason and result.get("reason_code") != expected_reason:
        raise ValueError(f"Expected reason {expected_reason}, received {result.get('reason_code')}")
    if result.get("recording", {}).get("source_sha256", audio_hash) != audio_hash:
        raise ValueError("Intake recording hash differs from submitted audio")
    if result["status"] == "succeeded":
        if not result.get("recording") or not result.get("events"):
            raise ValueError("Supported-location result lacks recording/event evidence")
        coverage = result.get("coverage", {})
        if not coverage.get("search_complete") or coverage.get("data_status") != "available":
            raise ValueError("Supported-location result lacks complete declared coverage")
    return result


def wait_job(base, job_id, deadline, history_path):
    previous = None
    with history_path.open("w") as history:
        while time.monotonic() < deadline:
            value = get_json(f"{base}/api/jobs/{job_id}")
            signature = (value["status"], value.get("stage"), value.get("progress"))
            if signature != previous:
                history.write(json.dumps({"monotonic_s": time.monotonic(), "result": value}) + "\n")
                history.flush()
                previous = signature
            if value["status"] in {"needs_input", "inconclusive", "succeeded", "failed", "cancelled"}:
                return value
            time.sleep(0.25)
    raise TimeoutError(f"Job {job_id} did not terminate within the acceptance budget")


def product_audit(args):
    """Exercise real entry points. Expected abstention is not location success."""
    from aircraft_geoloc.contracts import validate_request

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    audio = args.audio.resolve(strict=True)
    audio_hash = sha256(audio)
    request = {"schema_version": 1, "audio_path": str(audio), "search": {"coverage": "conus"}}
    if args.start_utc:
        request["time_window"] = {"start_utc": args.start_utc,
                                  "end_utc": args.end_utc or args.start_utc, "source": "user",
                                  "source_detail": args.time_source}
    elif args.end_utc:
        raise ValueError("--end-utc requires --start-utc")
    request = validate_request(request)
    wire_request = {k: v for k, v in request.items() if k != "audio_path"}
    write_json(output / "upload-request.json", wire_request)
    modes = list(dict.fromkeys(args.via or ["cli", "api", "browser"]))
    report = {"schema_version": 1, "scope": "automatic_product_acceptance",
              "location_accuracy_evaluated": False, "input_sha256": audio_hash,
              "request": wire_request, "provenance": provenance(), "modes": [],
              "operator_config_sha256": sha256(args.operator_config) if args.operator_config else None}
    base_command = [sys.executable, "-m", "aircraft_geoloc.cli"]
    config = ["--config", str(args.operator_config.resolve())] if args.operator_config else []
    began = time.monotonic()
    server = None
    server_log = None
    try:
        if "cli" in modes:
            directory = output / "cli"
            directory.mkdir()
            command = base_command + ["analyze", str(audio), "--jobs", str(directory / "jobs"),
                                      "--max-runtime", str(args.timeout), *config]
            if args.start_utc:
                window = request["time_window"]
                command += ["--start-utc", window["start_utc"], "--end-utc", window["end_utc"],
                            "--time-source", args.time_source]
            run_command(command, directory, "analyze")
            value = json.loads((directory / "analyze.stdout").read_text())
            write_json(directory / "result.json", value)
            result = inspect_result(value, audio_hash, args.expect_status, args.expect_reason)
            job_directory = directory / "jobs" / value["job_id"]
            input_record = json.loads((job_directory / "input.json").read_text())
            original = job_directory / input_record["path"]
            if original.parent != job_directory or sha256(original) != audio_hash or input_record["sha256"] != audio_hash:
                raise ValueError("CLI did not preserve the exact uploaded bytes")
            report["modes"].append({"mode": "cli", "result": result, "original_hash_verified": True})
        if any(mode in modes for mode in ("api", "browser")):
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                port = reserved.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            server_command = base_command + ["serve", "--jobs", str(output / "http-jobs"),
                                            "--port", str(port), "--max-runtime", str(args.timeout), *config]
            write_json(output / "server-command.json", server_command)
            server_log = (output / "server.log").open("wb")
            server = subprocess.Popen(server_command, stdout=server_log, stderr=subprocess.STDOUT)
            ready_deadline = time.monotonic() + 20
            while True:
                if server.poll() is not None:
                    raise RuntimeError("Upload service exited during startup; see server.log")
                try:
                    capabilities = get_json(base + "/api/capabilities")
                    write_json(output / "capabilities.json", capabilities)
                    break
                except OSError:
                    if time.monotonic() >= ready_deadline:
                        raise TimeoutError("Upload service did not become ready")
                    time.sleep(0.1)
            for mode in modes:
                if mode == "cli":
                    continue
                directory = output / mode
                directory.mkdir()
                if mode == "api":
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                    try:
                        with audio.open("rb") as stream:
                            connection.request("POST", "/api/jobs", body=stream, headers={
                                "Content-Type": "application/octet-stream",
                                "Content-Length": str(audio.stat().st_size),
                                "X-Filename": "input" + audio.suffix,
                                "X-Dopplergeist-Request": json.dumps(wire_request),
                            })
                            response = connection.getresponse()
                            queued = json.loads(response.read())
                            if response.status != 202:
                                raise RuntimeError(f"Upload HTTP {response.status}: {queued}")
                    finally:
                        connection.close()
                    write_json(directory / "submission.json", queued)
                    value = wait_job(base, queued["job_id"], time.monotonic() + args.timeout + 30,
                                     directory / "history.jsonl")
                else:
                    if not args.browser_python:
                        raise ValueError("Browser acceptance requires --browser-python with Playwright installed")
                    # Preserve the venv interpreter path: resolving its symlink
                    # would silently execute the base Python without Playwright.
                    run_command([str(args.browser_python.absolute()), str(ROOT / "scripts/verify_upload_browser.py"),
                                 "--base-url", base, "--audio", str(audio),
                                 "--request", str(output / "upload-request.json"),
                                 "--output", str(directory), "--timeout", str(args.timeout + 30)],
                                directory, "browser")
                    value = json.loads((directory / "result.json").read_text())
                write_json(directory / "result.json", value)
                result = inspect_result(value, audio_hash, args.expect_status, args.expect_reason)
                listing = get_json(f"{base}/api/jobs/{value['job_id']}/artifacts")
                write_json(directory / "artifacts.json", listing)
                originals = [row for row in listing["artifacts"]
                             if row["path"] == "input" + audio.suffix.lower()]
                if len(originals) != 1:
                    raise ValueError("Artifact API did not expose one preserved original")
                target = directory / "downloaded-original.bin"
                with urlopen(f"{base}/api/jobs/{value['job_id']}/artifacts/{originals[0]['path']}", timeout=30) as response, target.open("wb") as stream:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                if sha256(target) != audio_hash:
                    raise ValueError("Artifact API returned different original bytes")
                report["modes"].append({"mode": mode, "result": result, "original_hash_verified": True})
                write_json(output / "report.json", report)
        report["passed"] = True
    except Exception as exc:
        report.update(passed=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if server_log is not None:
            server_log.close()
        report["elapsed_s"] = time.monotonic() - began
        write_json(output / "report.json", report)
    print(json.dumps({"report": str(output / "report.json"), "passed": report["passed"],
                      "error": report.get("error"), "modes_completed": len(report["modes"])}))
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    codec = subparsers.add_parser("codec", help="Measure independent MP3 sample timing pilots")
    codec.add_argument("--output", type=Path, required=True)
    product = subparsers.add_parser("product", help="Exercise actual CLI, HTTP upload and browser form")
    product.add_argument("--audio", type=Path, required=True)
    product.add_argument("--output", type=Path, required=True)
    product.add_argument("--operator-config", type=Path)
    product.add_argument("--start-utc")
    product.add_argument("--end-utc")
    product.add_argument("--time-source", default="Explicit acceptance-test recording clock window")
    product.add_argument("--via", action="append", choices=["cli", "api", "browser"])
    product.add_argument("--browser-python", type=Path)
    product.add_argument("--timeout", type=float, default=600)
    product.add_argument("--expect-status", required=True,
                         choices=["succeeded", "needs_input", "inconclusive", "failed"])
    product.add_argument("--expect-reason")
    args = parser.parse_args()
    if args.command == "codec":
        return codec_audit(args.output.resolve())
    if args.command == "product":
        return product_audit(args)


if __name__ == "__main__":
    raise SystemExit(main())
