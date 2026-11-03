#!/usr/bin/env python3
"""Screen a fixed real-audio sample; do not run flight matching or localization.

Requires the project runtime and ``remotezip``. Run from the repository with
``PYTHONPATH=src python scripts/benchmark_aerosonic_scan.py NEW_OUTPUT_DIR``.
The publisher's locations are deliberately displaced; they are not precision
recorder coordinates. Identifiers and labels stay in selection.json, while the
scanner receives only opaque audio filenames and no event or flight hints.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import urllib.request

from remotezip import RemoteZip

from dopplergeist.discovery import discover_events
from dopplergeist.intake import intake_recording


SOURCE = "https://zenodo.org/api/records/10215080/files/"
SEED = 20261103
# The publisher's positive recordings are concentrated at location 0. Select
# all positives at locations 1 and 2 and a reproducible sample at location 0;
# sample ten publisher-labelled background recordings at each location.
COUNTS = {("0", "1"): 100, ("1", "1"): 9, ("2", "1"): 16,
          ("0", "0"): 10, ("1", "0"): 10, ("2", "0"): 10}


def main(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with urllib.request.urlopen(SOURCE + "sample_meta.csv/content", timeout=60) as response:
        catalog_bytes = response.read()
    catalog = list(csv.DictReader(io.StringIO(catalog_bytes.decode("utf-8-sig"))))
    rng = random.Random(SEED)
    selected = []
    for (location, label), count in COUNTS.items():
        population = sorted((r for r in catalog if r["location"] == location and r["class"] == label),
                            key=lambda r: r["filename"])
        selected.extend(rng.sample(population, count))
    rng.shuffle(selected)
    selection = [{"case_id": f"case-{i:04d}", "source_filename": row["filename"],
                  "publisher_location_id": row["location"], "publisher_aircraft_class": row["class"],
                  "publisher_session": row["session"]} for i, row in enumerate(selected, 1)]
    (output / "selection.json").write_text(json.dumps({"seed": SEED, "source_record":
        "https://zenodo.org/records/10215080", "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "location_scope": "Publisher location markers are nearby public places, not exact microphones.",
        "sampling": "Fixed stratified random sample; source labels are not scanner inputs.",
        "cases": selection}, indent=2) + "\n")
    (output / "audio").mkdir()
    (output / "scans").mkdir()
    with RemoteZip(SOURCE + "audio.zip/content", timeout=90) as archive, \
            (output / "outcomes.jsonl").open("x", buffering=1) as outcomes:
        members = {Path(name).name: name for name in archive.namelist() if name.lower().endswith(".wav")}
        for i, case in enumerate(selection, 1):
            case_id = case["case_id"]
            report = {"case_id": case_id, "status": "error"}
            try:
                # CRC is checked by zipfile when the member is read completely.
                data = archive.read(members[case["source_filename"]])
                audio = output / "audio" / (case_id + ".wav")
                audio.write_bytes(data)
                report["audio_sha256"] = hashlib.sha256(data).hexdigest()
                recording = intake_recording(audio, output / "scans" / case_id / "intake")
                events = discover_events(recording)
                (output / "scans" / case_id / "events.json").write_text(json.dumps(events, indent=2) + "\n")
                report.update(status="scanned", duration_s=recording.metadata["duration_s"],
                              ridge_records=len(events), independent_group_ids=len({
                                  e["harmonic_group_id"] for e in events}))
            except Exception as error:
                report["error"] = f"{type(error).__name__}: {error}"
            outcomes.write(json.dumps(report, allow_nan=False) + "\n")
            print(f"{i}/{len(selection)} {case_id}: {report['status']} "
                  f"groups={report.get('independent_group_ids', '-')}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: benchmark_aerosonic_scan.py NEW_OUTPUT_DIR")
    main(sys.argv[1])
