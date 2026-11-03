"""Export two supported real pipeline track/ridge controls with provenance."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    import numpy as np
    from dopplergeist import geometry, matching, tracks as track_module
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.geometry import AcousticSupportError, ecef

    fixture = json.loads(args.fixture.read_text())
    index = FlightIndex(fixture["real_index"])
    if index.report["input_hash"] != fixture["index_input_hash"]:
        raise ValueError("The restored index differs from the prepared real fixture")
    names = sorted({row["flight_id"] for row in fixture["cpa_rows"]})
    tracks = {track.id: track for track in index.lookup(names, max_tracks=max(1, len(names)),
        max_samples=fixture["budget"]["max_track_samples_per_tile"],
        bounds=fixture["query_bounds"], time_range=fixture["query_time_s"])}
    events, measurements = matching.prepare_events(fixture["events"])
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    cases, chosen = [], set()
    for i in sorted(range(len(events)), key=lambda i: -len(measurements[i][1])):
        event, measurement = events[i], measurements[i]
        sigma = matching._frequency_scale(event)
        drift = event.get("quality", {}).get("source_drift_fraction", 0.02)
        times, ridge, weight = matching._ridge_fit_inputs(measurement, sigma, drift)
        measured = np.isfinite(times) & np.isfinite(ridge) & (weight > 0)
        for row in fixture["cpa_rows"]:
            track = tracks.get(row["flight_id"])
            if track is None or track.id in chosen:
                continue
            start = row["receive_time"] - event["cpa_receive_s"]
            receive = start + times[measured]
            try:
                factors, emissions, distance = track.acoustic(receive, observer, 343.0)
            except AcousticSupportError:
                continue
            if not all(np.isfinite(values).all() for values in (factors, emissions, distance)):
                continue
            fit = matching.fit_ridge(track, observer, measurement, start,
                                     event["f0_range_hz"], 343.0, sigma, drift)
            if not np.isfinite(fit["score"]):
                continue
            score = matching.score_ridges([track], [event], [measurement], observer, start, 343.0)
            cases.append({
                "track": {key: getattr(track, key) for key in
                          ("id", "time", "lat", "lon", "altitude", "typecode", "velocity")},
                "track_metadata": {key: getattr(track, key, None) for key in
                                   ("altitude_basis", "aircraft_class", "velocity_inferred_components")},
                "receiver_point": point, "observer_ecef_m": observer,
                "c_mps": 343.0, "recording_start_s": start, "event_index": i, "event": event,
                "measurement": {"time_s": times, "ridge_hz": ridge, "weight": weight},
                "scoring_parameters": {"f0_bounds_hz": event["f0_range_hz"],
                                       "sigma_hz": sigma, "drift_fraction": drift},
                "measured_mask": measured, "receive_times_s": receive,
                "expected_acoustic": {"factor": factors, "emission_time_s": emissions, "distance_m": distance},
                "expected_fit": fit, "expected_score_ridges": score, "cpa_source_row": row,
            })
            chosen.add(track.id)
            if len(cases) == 2:
                break
        if len(cases) == 2:
            break
    if len(cases) != 2:
        raise ValueError("Two distinct supported recorded track/ridge controls are required")
    output = {
        "schema_version": 1,
        "scope": "Real indexed aircraft observations and recorded ridges; source-informed receiver/clock, no location-accuracy claim",
        "selection": "Longest recorded groups first, original CPA-row order, distinct tracks with complete finite acoustic support; no fit-score ranking",
        "velocity_reference_frame": "ECEF; null preserves Track's ordinary position-gradient inference",
        "provenance": {
            "source_commit": os.environ.get("GITHUB_SHA"),
            "fixture": str(args.fixture), "fixture_sha256": digest(args.fixture),
            "discovery_source": fixture["discovery_source"],
            "discovery_sha256": digest(fixture["discovery_source"]),
            "index_report": index.report, "query_bounds": fixture["query_bounds"],
            "query_time_s": fixture["query_time_s"], "python": platform.python_version(),
            "ridge_fit_backend": getattr(matching, "RIDGE_FIT_BACKEND", "python-irls-v1"),
            "acoustic_backend": getattr(geometry, "ACOUSTIC_BACKEND", "python-acoustic-v1"),
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "pandas")},
            "implementation_sha256": {Path(module.__file__).name: digest(module.__file__)
                                      for module in (geometry, matching, track_module)},
        }, "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(output, stream, indent=2, default=lambda value: value.tolist(), allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.output), "tracks": sorted(chosen),
                      "recorded_ridge_samples": [len(case["measurement"]["time_s"]) for case in cases]}))


if __name__ == "__main__":
    main()
