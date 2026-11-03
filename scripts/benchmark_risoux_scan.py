#!/usr/bin/env python3
"""Screen selected real Risoux soundscapes without flight matching or location search.

Requires the project runtime and optional ``remotezip``. Run with a new output
path: ``PYTHONPATH=src python scripts/benchmark_risoux_scan.py NEW_OUTPUT_DIR``.
Publisher labels are used for sampling and comparison, not scanner inputs.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import urllib.request

from remotezip import RemoteZip

from dopplergeist.discovery import discover_events
from dopplergeist.intake import intake_recording


BASE = "https://zenodo.org/records/10701274/files/"
SEED = 20261103
ANNOTATIONS_MD5 = "bdc6b2c62b8fcfd5d6dae36460809683"


def select(annotations, infos):
    by_name = {Path(info.filename).name: info for info in infos if not info.is_dir()}
    prefixes = sorted({row["prefix"] for row in annotations})
    if len(prefixes) != 5 or len(by_name) != 1314:
        raise ValueError("Publisher metadata changed: expected five prefixes and 1,314 WAV members")
    rng = random.Random(SEED)
    chosen = {}
    for prefix in prefixes:
        plane = [row for row in annotations if row["prefix"] == prefix and row["plane"] == "1"
                 and row["wind"] == row["rain"] == row["biophony"] == "0"]
        silence = [row for row in annotations if row["prefix"] == prefix
                   and row["plane"] == "0" and row["silence"] == "1"]
        chosen[prefix] = (rng.sample(sorted(plane, key=lambda row: row["filename"]), 5)
                          + rng.sample(sorted(silence, key=lambda row: row["filename"]), 1))
    cases = []
    for round_index in range(6):
        for prefix in prefixes:
            row = chosen[prefix][round_index]
            item = by_name[row["filename"]]
            cases.append({"name": item.filename, "size": item.file_size, "compressed_size": item.compress_size,
                          "crc": f"{item.CRC:08x}",
                          "opaque_id": hashlib.sha256(item.filename.encode()).hexdigest()[:20],
                          "publisher_label": "plane_only" if round_index < 5 else "silence_no_plane",
                          "prefix": prefix, "round": round_index + 1})
    return cases


def main(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("audio", "scans"):
        (output / folder).mkdir()
    with urllib.request.urlopen(BASE + "annotations.csv?download=1", timeout=60) as response:
        raw_annotations = response.read()
    if hashlib.md5(raw_annotations).hexdigest() != ANNOTATIONS_MD5:
        raise ValueError("Publisher annotation checksum changed")
    (output / "annotations.csv").write_bytes(raw_annotations)
    annotations = list(csv.DictReader(io.StringIO(raw_annotations.decode("utf-8-sig"))))
    with RemoteZip(BASE + "audio_recordings.zip?download=1", timeout=120) as archive:
        cases = select(annotations, archive.infolist())
        (output / "selection.json").write_text(json.dumps({"seed": SEED, "cases": cases}, indent=2) + "\n")
        with (output / "outcomes.jsonl").open("w") as log:
            for number, case in enumerate(cases, 1):
                identifier = case["opaque_id"]
                row = {"opaque_id": identifier, "case_number": number}
                try:
                    raw = archive.read(case["name"])  # zipfile verifies this member's CRC.
                    if len(raw) != case["size"]:
                        raise ValueError("Uncompressed size differs from the archive index")
                    audio = output / "audio" / (identifier + ".wav")
                    audio.write_bytes(raw)
                    row["sha256"] = hashlib.sha256(raw).hexdigest()
                    with tempfile.TemporaryDirectory(prefix="decode-", dir=output) as temporary:
                        recording = intake_recording(audio, temporary)
                        events = discover_events(recording)
                        groups = {event.get("harmonic_group_id", event["event_id"]) for event in events}
                        scan = {"status": "scanned", "duration_s": recording.metadata["duration_s"],
                                "events": events, "ridge_count": len(events), "proposal_count": len(groups),
                                "scanner_result": "proposals" if groups else "no_proposals"}
                        (output / "scans" / (identifier + ".json")).write_text(json.dumps(scan) + "\n")
                    row.update(status="scanned", duration_s=scan["duration_s"],
                               scanner_result=scan["scanner_result"], proposal_count=scan["proposal_count"])
                except Exception as error:
                    row.update(status="error", error=str(error))
                log.write(json.dumps(row) + "\n")
                log.flush()
                print(number, len(cases), identifier, row["status"], row.get("scanner_result", ""), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: benchmark_risoux_scan.py NEW_OUTPUT_DIR")
    main(sys.argv[1])
