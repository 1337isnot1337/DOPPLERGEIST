#!/usr/bin/env python3
"""Compare index staging on the first24 real non-jet traces in verified archives.

Pass complete provider-verified split archives in published order. The selected
parity sample cannot establish whole-day coverage. All four outcomes are saved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from dopplergeist.aircraft_types import load_classes
from dopplergeist.data_access import (
    FlightIndex, _archive_members, _archive_nonjet_staging, _decode_archive_frame, sha256,
)


LIMIT = 64 * 1024**2


def directory_bytes(folder):
    size = 0
    for path in folder.iterdir():
        try:
            size += path.stat().st_size
        except FileNotFoundError:
            pass  # SQLite can rename its completed temporary index between reads.
    return size


def fingerprint(rows):
    digest = hashlib.sha256()
    for row in rows:
        for value in row:
            raw = value if isinstance(value, bytes) else repr(value).encode()
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, nargs="+", required=True)
    parser.add_argument("--types", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir()
    classes, _ = load_classes(args.types)
    selected, times = [], []
    for raw in _archive_members(args.archive, LIMIT):
        frame = _decode_archive_frame(raw, LIMIT)
        if frame.empty:
            continue
        batch = _archive_nonjet_staging(frame, classes)
        if not batch[0]:
            continue
        path = inputs / f"native-{len(selected)+1:02d}.json"
        path.write_bytes(raw)
        selected.append(path)
        times.extend(row[1] for row in batch[0])
        if len(selected) == 24:
            break
    if len(selected) != 24:
        raise ValueError("The fixed protocol requires24 nonempty confirmed-nonjet traces")
    sources = [{"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size} for path in selected]
    coverage = {"aircraft_policy": "selected_nonjet_subset", "all_aircraft": False,
                "selection": "First24 native nonjet traces; incomplete source coverage",
                "bounds": [-180, -90, 180, 90], "time_range_s": [min(times), max(times)]}
    cases = [(reverse, compressed) for reverse in (False, True) for compressed in (False, True)]
    (root / "plan.json").write_text(json.dumps({"sources": sources, "cases": cases,
        "selection_before_comparison": True}, indent=2) + "\n")
    outcomes, reference = [], None
    for reverse, compressed in cases:
        name = ("reverse" if reverse else "forward") + ("-compressed" if compressed else "-row")
        folder = root / name
        folder.mkdir()
        os.environ["SQLITE_TMPDIR"] = str(folder)
        path = folder / "index.sqlite"
        stop, peak = threading.Event(), [0]

        def watch():
            while not stop.wait(0.02):
                peak[0] = max(peak[0], directory_bytes(folder))

        monitor = threading.Thread(target=watch)
        monitor.start()
        start = time.monotonic()
        value = {"name": name, "exact": False}
        try:
            order = selected[::-1] if reverse else selected
            frames = (_archive_nonjet_staging(_decode_archive_frame(p.read_bytes(), LIMIT), classes) for p in order)
            index = FlightIndex.build(path, frames, sources=sources, coverage=coverage,
                class_map=classes, prepared=True, compressed_staging=compressed)
            with index.connect() as db:
                rows = db.execute("SELECT s.name,s.start,s.end,s.payload,s.payload_hash,"
                    "p.west,p.east,p.south,p.north FROM segments s JOIN spatial p USING(id) ORDER BY s.name").fetchall()
                prepared = db.execute("SELECT * FROM prepared_tracks ORDER BY id").fetchall()
            facts = {"rows": index.report["rows"], "invalid": index.report["invalid_rows"],
                     "segments": index.report["segments"], "altitude": index.report["altitude_basis_counts"],
                     "logical_sha256": fingerprint(rows), "prepared_sha256": fingerprint(prepared)}
            if name == "forward-row":
                reference = facts
            value.update(facts, exact=reference is not None and facts == reference,
                         final_bytes=path.stat().st_size)
        except Exception as error:
            value.update(error_type=type(error).__name__, error=str(error))
        finally:
            stop.set()
            monitor.join()
            peak[0] = max(peak[0], directory_bytes(folder))
        value.update(wall_s=time.monotonic()-start, peak_observed_folder_bytes=peak[0])
        outcomes.append(value)
        (root / "outcomes.json").write_text(json.dumps(outcomes, indent=2) + "\n")
        print(json.dumps(value), flush=True)
    if not all(value["exact"] for value in outcomes):
        raise RuntimeError("Staging parity failed; all attempted outcomes remain saved")


if __name__ == "__main__":
    main()
