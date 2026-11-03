"""Measure JSON encoding of an existing completed real-search checkpoint.

Supply an actual tile file with its original payload hash and retention checksum.
The source is never modified. Both encodings must preserve the complete decoded
record exactly. Timing covers json.dumps and its trailing newline only; loading,
decoding, comparison, file writes, and search/scoring are excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time


def canonical(value):
    """Preserve scalar representation and list order; ignore object-key order."""
    return json.dumps(value, sort_keys=True, allow_nan=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True,
                        help="Original completed tile-*.json from a real search")
    parser.add_argument("--output", type=Path, required=True, help="New summary JSON file")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.output.exists():
        raise FileExistsError(f"Choose a new output file: {args.output}")
    source = args.checkpoint.resolve()
    if not source.name.startswith("tile-") or source.suffix != ".json":
        parser.error("Supply the original completed tile-*.json filename")
    original = source.read_text()
    value = json.loads(original)
    payload = value["payload"]
    candidates = payload["counts"]["candidates"]
    if type(candidates) is not int or candidates < 1:
        raise ValueError("The recorded tile must contain actual candidate associations")
    if not value["run_hash"] or not payload["retention_checksum"]:
        raise ValueError("The tile is missing its run or retention identity")
    payload_hash = hashlib.sha256(canonical(payload).encode()).hexdigest()
    if payload_hash != value["payload_hash"]:
        raise ValueError("The original tile payload hash does not match")
    expected = canonical(value)
    runs = []
    for repetition in range(args.repeats):
        order = ("pretty", "compact") if repetition % 2 == 0 else ("compact", "pretty")
        for name in order:
            compact = name == "compact"
            started_wall, started_cpu = time.perf_counter(), time.process_time()
            encoded = json.dumps(value, indent=None if compact else 2,
                                 separators=(",", ":") if compact else None,
                                 allow_nan=False) + "\n"
            wall, cpu = time.perf_counter() - started_wall, time.process_time() - started_cpu
            decoded = json.loads(encoded)
            if canonical(decoded) != expected:
                raise AssertionError(f"Complete decoded record changed: {name}")
            if (hashlib.sha256(canonical(decoded["payload"]).encode()).hexdigest() != payload_hash
                    or decoded["payload"]["retention_checksum"] != payload["retention_checksum"]):
                raise AssertionError(f"Checkpoint identity changed: {name}")
            runs.append({"repetition": repetition + 1, "encoding": name,
                         "cpu_seconds": cpu, "wall_seconds": wall,
                         "bytes": len(encoded.encode())})
            del decoded, encoded
    summary = {
        "schema_version": 1,
        "scope": "JSON encoding only for a completed real tile; no scoring or pipeline speed claim",
        "input": str(source), "input_bytes": source.stat().st_size,
        "candidate_associations": candidates, "python": platform.python_version(),
        "repeats_per_encoding": args.repeats,
        "all_decoded_outputs_exact": True, "payload_hash_unchanged": True,
        "retention_checksum_unchanged": True, "runs": runs,
    }
    for name in ("pretty", "compact"):
        selected = [row for row in runs if row["encoding"] == name]
        summary[name] = {key: statistics.median(row[key] for row in selected)
                         for key in ("cpu_seconds", "wall_seconds", "bytes")}
    summary["cpu_speedup"] = summary["pretty"]["cpu_seconds"] / summary["compact"]["cpu_seconds"]
    summary["size_reduction_fraction"] = 1 - summary["compact"]["bytes"] / summary["pretty"]["bytes"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(summary, output, indent=2, allow_nan=False)
        output.write("\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "runs"}, allow_nan=False))


if __name__ == "__main__":
    main()
