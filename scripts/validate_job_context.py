#!/usr/bin/env python3
"""Diagnose a completed automatic job using the fixed frozen-context protocol.

No event/flight/location hints or truth file are accepted. This command does not
change the preserved job or its decision. All retained rows and prepared groups
are supplied; partial explanations remain explicit unavailable comparisons.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from aircraft_geoloc.context_validation import ContextSettings, validate_context
from aircraft_geoloc.contracts import validate_recording
from aircraft_geoloc.data_access import FlightIndex
from aircraft_geoloc.matching import prepare_events


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-query-segments", type=int, default=20000)
    args = parser.parse_args()
    if args.max_query_segments <= 0:
        parser.error("--max-query-segments must be positive")
    job = args.job.resolve()
    files = {name: job / name for name in ("intake/recording.json", "discovery/discovery.json",
                                          "operator.json", "refined-candidates.json")}
    metadata = validate_recording(json.loads(files["intake/recording.json"].read_text()))
    detected = json.loads(files["discovery/discovery.json"].read_text())["events"]
    config = json.loads(files["operator.json"].read_text())
    candidates = json.loads(files["refined-candidates.json"].read_text())["ranked"]
    settings = ContextSettings(sound_speed_mps=float(config.get("sound_speed_mps", 343.0)))
    events, measurements = prepare_events(detected, c=settings.sound_speed_mps,
                                         max_distance_m=float(config.get("max_distance_m", 20000)))
    tracks, queried = {}, 0
    index_paths = [Path(p) for p in config["flight_indexes"]]
    indexes = [FlightIndex(p if p.is_absolute() else job / p) for p in index_paths]
    if len(candidates) <= settings.max_modes:
        radius = float(config.get("max_distance_m", 20000)) * 1.6 + 15000
        for row in candidates:
            needed = set(row.get("flight_ids", [])) - tracks.keys()
            if not needed:
                continue
            try:
                lon, lat, clock = float(row["lon"]), float(row["lat"]), float(row["recording_start_time_s"])
                if not np.isfinite([lon, lat, clock]).all():
                    continue
            except (KeyError, ValueError, TypeError):
                continue  # The module preserves this malformed mode as unsupported.
            delta_lat = radius / 110000
            delta_lon = delta_lat / max(0.1, math.cos(math.radians(lat)))
            bounds = (lon-delta_lon, lat-delta_lat, lon+delta_lon, lat+delta_lat)
            interval = (clock + min(e["start_s"] for e in events) - settings.expansion_s - radius / 300,
                        clock + max(e["end_s"] for e in events) + settings.expansion_s + 30)
            for index in indexes:
                for track in index.query(bounds, interval):
                    queried += 1
                    if queried > args.max_query_segments:
                        raise ValueError("Context trajectory-query budget exhausted; no comparison completed")
                    if track.id in needed:
                        previous = tracks.get(track.id)
                        if previous is not None and not all(np.array_equal(a, b) for a, b in (
                                (previous.time, track.time), (previous.xyz, track.xyz),
                                (previous.spline.c, track.spline.c))):
                            raise ValueError(f"Conflicting whole trajectories share ID {track.id}")
                        tracks[track.id] = track
    recording = SimpleNamespace(samples_path=job / "intake/recording.f32", metadata=metadata)
    report = validate_context(recording, candidates, tracks, events, measurements,
                              detected_events=detected, settings=settings, output_dir=args.output)
    receipt = {"context_status": report["status"], "mode_count": len(candidates),
               "prepared_group_count": len(events), "trajectory_segments_queried": queried,
               "max_query_segments": args.max_query_segments, "settings": asdict(settings),
               "inputs_sha256": {name: digest(path) for name, path in files.items()},
               "indexes_sha256": {str(index.path): digest(index.path) for index in indexes},
               "script_sha256": digest(Path(__file__)),
               "limits": ["No job decision was changed.",
                          "All prepared groups were supplied; no first-two or association-only filter.",
                          "This is development diagnostics, not independent location-accuracy acceptance."]}
    (args.output / "run-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "status": report["status"],
                      "modes": len(candidates), "events": len(events), "ranking": report["ranking"][:5]}))


if __name__ == "__main__":
    main()
