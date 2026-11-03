#!/usr/bin/env python3
"""Supplement JSON/SQLite parity with the actual arrays from fresh HTTP runs.

Both runs must have completed full-workflow verification and stopped their
services. Compare complete intake diagnostics, decoded PCM and CSV bytes, NPZ
member arrays, and decoded PNG pixels. Verify the selected files against each
run's finalized job manifest before reading their contents.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np


ARRAY_SUFFIXES = {".f32", ".csv", ".npz", ".png"}


def read_json(path):
    def reject(value):
        raise ValueError(f"Nonfinite JSON constant in {path}: {value}")
    return json.loads(path.read_text(), parse_constant=reject)


def same_file_bytes(left, right):
    """Compare exact bytes with bounded memory, including signed-zero bits."""
    with left.open("rb") as first, right.open("rb") as second:
        while True:
            a, b = first.read(1024 * 1024), second.read(1024 * 1024)
            if a != b:
                return False
            if not a:
                return True


def same_array_bits(left, right):
    """Require equal dtype, shape, and element bits, independent of layout."""
    if left.dtype != right.dtype or left.shape != right.shape:
        return False
    if left.dtype.hasobject:
        raise ValueError("Object arrays are not supported by the scientific array comparator")
    with np.nditer([left, right], flags=["external_loop", "buffered", "zerosize_ok"],
                   op_flags=[["readonly"], ["readonly"]], order="C", buffersize=65536) as iterator:
        return all(a.tobytes() == b.tobytes() for a, b in iterator)


class Run:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        receipt_path = self.directory / "http-verification.json"
        if not receipt_path.is_file():
            raise ValueError(f"Run has no finalized HTTP verification receipt: {self.directory}")
        self.receipt = read_json(receipt_path)
        if (not self.receipt.get("finished_utc")
                or self.receipt.get("service", {}).get("returncode") != 0
                or self.receipt.get("service", {}).get("forced_kill") is True
                or not all(self.receipt.get(key) is True for key in
                           ("verification_passed", "implementation_unchanged",
                            "full_pipeline_observed", "full_pipeline_requirements_met"))):
            raise ValueError(f"Run is unfinished or lacks successful full-workflow verification: {self.directory}")
        digest, source_bytes = (self.receipt.get(key) for key in ("source_sha256", "source_bytes"))
        if (not isinstance(digest, str) or len(digest) != 64
                or any(value not in "0123456789abcdef" for value in digest)
                or type(source_bytes) is not int or source_bytes <= 0):
            raise ValueError("HTTP receipt has no valid source identity and byte count")
        job_id = self.receipt.get("job_id")
        if not isinstance(job_id, str) or not job_id or Path(job_id).name != job_id or job_id in {".", ".."}:
            raise ValueError("HTTP receipt contains an invalid job identifier")
        self.job = (self.directory / "jobs" / job_id).resolve()
        if not self.job.is_relative_to(self.directory / "jobs"):
            raise ValueError("Job directory leaves the verified run")
        final = read_json(self.job / "result.json")
        if (final.get("status") in {"queued", "running"}
                or any(final.get(key) != self.receipt.get(key) for key in ("status", "reason_code"))
                or len(final.get("events", [])) != self.receipt.get("event_count")
                or len(final.get("candidates", [])) != self.receipt.get("candidate_count")):
            raise ValueError("Final job result does not match its completed HTTP receipt")
        provenance = read_json(self.job / "provenance.json")
        if ((self.directory / "continuation-start.json").exists() or "resumed_from" in provenance):
            raise ValueError("This comparator requires fresh HTTP runs, without continuation or resume")
        manifest = read_json(self.directory / "job-manifest.json")
        if manifest.get("job_id") != job_id or not isinstance(manifest.get("files"), dict):
            raise ValueError("Finalized job manifest does not identify this HTTP job")
        self.manifest = manifest["files"]
        self.inventory = {path.relative_to(self.job).as_posix(): path
                          for path in self.job.rglob("*")
                          if path.is_file() and path.suffix.lower() in ARRAY_SUFFIXES}
        expected = {name for name in self.manifest if Path(name).suffix.lower() in ARRAY_SUFFIXES}
        if set(self.inventory) != expected:
            raise ValueError("Actual array inventory differs from the finalized job manifest: "
                             f"missing={sorted(expected - self.inventory.keys())}, "
                             f"extra={sorted(self.inventory.keys() - expected)}")
        if "intake/recording.f32" not in self.inventory:
            raise ValueError("Verified full workflow has no decoded PCM artifact")
        self.verified = 0

    def verify_file(self, relative):
        path = self.job / relative
        if path.is_symlink() or not path.resolve().is_relative_to(self.job):
            raise ValueError(f"Artifact leaves its verified job: {relative}")
        with path.open("rb") as stream:
            actual = {"bytes": path.stat().st_size,
                      "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
        if self.manifest.get(relative) != actual:
            raise ValueError(f"Artifact no longer matches the finalized job manifest: {relative}")
        self.verified += 1
        return actual

    def intake(self):
        self.verify_file("intake/intake.json")
        value = read_json(self.job / "intake/intake.json")
        # This command argument is the sole run-specific field in intake.
        # Preserve every other field, including downmix and sample-zero policy.
        command = value.get("decode", {}).get("command")
        if isinstance(command, list):
            source = str(self.job / "input.mp3")
            value["decode"]["command"] = ["<job>/input.mp3" if item == source else item for item in command]
        return value


def compare_runs(baseline, current):
    left, right = Run(baseline), Run(current)
    differences, checked, pcm = [], Counter(), {}

    def different(artifact, reason, **details):
        differences.append({"artifact": artifact, "reason": reason, **details})

    sources = [{key: run.receipt.get(key) for key in ("source_sha256", "source_bytes")}
               for run in (left, right)]
    if sources[0] != sources[1]:
        different("HTTP source", "source_bytes_or_identity_changed", baseline=sources[0], current=sources[1])
    intake = [run.intake() for run in (left, right)]
    encoded = [json.dumps(value, sort_keys=True, allow_nan=False) for value in intake]
    if encoded[0] != encoded[1]:
        different("intake/intake.json", "diagnostics_changed", baseline=intake[0], current=intake[1])
    checked["intake_diagnostics"] += 1
    inventories = [set(run.inventory) for run in (left, right)]
    if inventories[0] != inventories[1]:
        different("array inventory", "missing_or_extra_artifacts",
                  baseline_only=sorted(inventories[0] - inventories[1]),
                  current_only=sorted(inventories[1] - inventories[0]))
    for name in sorted(inventories[0] & inventories[1]):
        paths = [run.inventory[name] for run in (left, right)]
        records = [run.verify_file(name) for run in (left, right)]
        suffix = paths[0].suffix.lower()
        if suffix in {".f32", ".csv"}:
            if not same_file_bytes(*paths):
                different(name, "file_bytes_changed", baseline=records[0], current=records[1])
            checked["decoded_pcm" if suffix == ".f32" else "csv"] += 1
            if suffix == ".f32":
                pcm[name] = {"baseline": records[0], "current": records[1]}
        elif suffix == ".png":
            from matplotlib.image import imread
            arrays = [imread(path) for path in paths]
            if not same_array_bits(*arrays):
                different(name, "decoded_pixels_changed", baseline_shape=list(arrays[0].shape),
                          current_shape=list(arrays[1].shape))
            checked["png"] += 1
        elif suffix == ".npz":
            with np.load(paths[0], allow_pickle=False) as first, np.load(paths[1], allow_pickle=False) as second:
                members = [archive.files for archive in (first, second)]
                if any(len(names) != len(set(names)) for names in members):
                    raise ValueError(f"NPZ contains duplicate array names: {name}")
                if set(members[0]) != set(members[1]):
                    different(name, "array_members_changed", baseline=sorted(members[0]), current=sorted(members[1]))
                for member in sorted(set(members[0]) & set(members[1])):
                    arrays = [archive[member] for archive in (first, second)]
                    if not same_array_bits(*arrays):
                        different(name, "array_dtype_shape_or_bits_changed", member=member,
                                  baseline={"dtype": str(arrays[0].dtype), "shape": list(arrays[0].shape)},
                                  current={"dtype": str(arrays[1].dtype), "shape": list(arrays[1].shape)})
                    checked["npz_arrays"] += 1
            checked["npz"] += 1
    return {"passed": not differences, "baseline": str(left.directory), "current": str(right.directory),
            "scope": "Supplementary exact intake/array/pixel comparison of two verified fresh HTTP workflows",
            "checked": {key: checked[key] for key in
                        ("intake_diagnostics", "decoded_pcm", "csv", "npz", "npz_arrays", "png")},
            "manifest_verified_artifacts": {"baseline": left.verified, "current": right.verified},
            "source": sources[0], "decoded_pcm": pcm,
            "difference_count": len(differences), "differences": differences,
            "normalization": "Only the exact input.mp3 path in intake.decode.command is replaced.",
            "array_rule": "Equal member names, dtype, shape, and element bits; no numerical tolerance. Memory layout does not affect equality.",
            "limitations": ["PNG encoding metadata and NPZ ZIP packaging are not compared.",
                            "The separate JSON/SQLite comparator remains required.",
                            "Equal outputs establish baseline consistency, not location accuracy."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New JSON report path")
    args = parser.parse_args()
    report = compare_runs(args.baseline, args.current)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"report": str(args.output), "passed": report["passed"],
                      "checked": report["checked"], "difference_count": report["difference_count"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
