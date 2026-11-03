#!/usr/bin/env python3
"""Screen a fixed sample of public VIREO audio; never match flights or locate it.

Requires the project runtime and optional ``remotezip``. Use a new output path:
``PYTHONPATH=src python scripts/benchmark_vireo_scan.py NEW_OUTPUT_DIR``.
The scanner sees only opaque audio filenames, not site, date or selection labels.
"""
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import tempfile

from remotezip import RemoteZip

from dopplergeist.discovery import discover_events
from dopplergeist.intake import intake_recording


SOURCE = "https://zenodo.org/records/21246876/files/Vireo%20Initiative.zip?download=1"
SEED = 20261103


def select(infos):
    groups = {}
    for info in infos:
        path = Path(info.filename)
        if not info.is_dir() and re.fullmatch(r"\d{8}_\d{6}\.WAV", path.name, re.I):
            groups.setdefault(str(path.parent), []).append(info)
    if len(groups) != 18 or any(len(items) < 6 for items in groups.values()):
        raise ValueError("Publisher archive has changed: expected 18 sites with at least six WAV files")
    rng = random.Random(SEED)
    chosen = {name: rng.sample(sorted(items, key=lambda i: i.filename), 6)
              for name, items in sorted(groups.items())}
    cases = []
    for round_index in range(6):
        for group in sorted(chosen):
            item = chosen[group][round_index]
            cases.append({"name": item.filename, "size": item.file_size,
                          "compressed_size": item.compress_size, "crc": f"{item.CRC:08x}",
                          "opaque_id": hashlib.sha256(item.filename.encode()).hexdigest()[:20],
                          "round": round_index + 1})
    return cases


def main(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("audio", "scans"):
        (output / folder).mkdir()
    with RemoteZip(SOURCE, timeout=90) as archive:
        cases = select(archive.infolist())
        (output / "selection.json").write_text(json.dumps({"seed": SEED, "cases": cases}, indent=2) + "\n")
        with (output / "outcomes.jsonl").open("w") as log:
            for number, case in enumerate(cases, 1):
                identifier = case["opaque_id"]
                row = {"opaque_id": identifier, "case_number": number}
                unavailable = None
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
                    status = getattr(getattr(error, "response", None), "status_code", None)
                    if status in (429, 500, 502, 503, 504):
                        unavailable = status
                log.write(json.dumps(row) + "\n")
                log.flush()
                print(number, len(cases), identifier, row["status"], row.get("scanner_result", ""), flush=True)
                if unavailable is not None:
                    for remaining_number, remaining in enumerate(cases[number:], number + 1):
                        log.write(json.dumps({"opaque_id": remaining["opaque_id"], "case_number": remaining_number,
                                              "status": "not_attempted", "reason": f"source_http_{unavailable}"}) + "\n")
                    log.flush()
                    print(f"Stopped after source HTTP {unavailable}; remaining cases were not attempted", flush=True)
                    break


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: benchmark_vireo_scan.py NEW_OUTPUT_DIR")
    main(sys.argv[1])
