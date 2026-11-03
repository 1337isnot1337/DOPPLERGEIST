#!/usr/bin/env python3
"""Measured codec and automatic-product acceptance checks; never fabricate a fix.

Each invocation creates a new output directory. Codec checks establish only
sample timing through the installed encoder/decoder, not location accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    codec = subparsers.add_parser("codec", help="Measure independent MP3 sample timing pilots")
    codec.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "codec":
        return codec_audit(args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
