#!/usr/bin/env python3
"""Compare production support exclusions with the preserved raw-motion audit.

This bounded source-only check reads no audio, receiver truth or search output.
It neither alters the historical audit nor performs a localization replay.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd

from dopplergeist.data_access import _frame_track
from dopplergeist.geometry import AcousticSupportError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=Path("research/trajectory-motion/frozen"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report_path = args.audit/"report.json"
    report = json.loads(report_path.read_text())
    canonical_path = args.audit/"canonical-observations.json"
    canonical = pd.read_json(canonical_path)
    inputs = [report_path, canonical_path]
    rows = []
    for aircraft in report["aircraft"]:
        identity = aircraft["identity"]
        fresh_path = args.audit/f"fresh-{identity}.json"
        fresh = pd.read_json(fresh_path)
        inputs.append(fresh_path)
        for tag, frame in (("canonical", canonical[canonical.flight_id == identity]), ("fresh", fresh)):
            for segment in aircraft[tag]["segments"]:
                intervals = segment["intervals"]
                chunk = frame[frame.time_s.between(intervals[0]["start_s"], intervals[-1]["end_s"])]
                chunk = chunk.sort_values("time_s", kind="stable").drop_duplicates("time_s")
                track = _frame_track(segment["id"], chunk)
                expected = [[i["start_s"], i["end_s"]] for i in intervals if i["exceeds_subsonic_speed"]]
                try:
                    track.validate_motion_support(c=report["declaration"]["sound_speed_mps"])
                    excluded = []
                except AcousticSupportError as error:
                    assert error.reason == "non_subsonic_motion"
                    excluded = error.emission_intervals_s
                assert excluded == expected, (tag, track.id, expected, excluded)
                rows.append({"source": tag, "track_id": track.id, "native_intervals": len(intervals),
                             "excluded_intervals_s": excluded, "audit_agrees": True})
    root = Path(__file__).resolve().parents[1]
    code = [Path(__file__), root/"src/dopplergeist/geometry.py", root/"src/dopplergeist/data_access.py"]
    receipt = {"scope": "source_only_production_guard_comparison", "segments": rows,
               "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=root).strip(),
               "code_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code},
               "input_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
               "excluded_native_intervals": sum(len(r["excluded_intervals_s"]) for r in rows),
               "limitations": ["No source repair, acoustic scoring, tile replay or accuracy claim",
                               "Whole native intervals are conservative model exclusions"]}
    (args.output/"receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n")
    print(f"{len(rows)} source segments agree; {receipt['excluded_native_intervals']} excluded native intervals")


if __name__ == "__main__":
    main()
