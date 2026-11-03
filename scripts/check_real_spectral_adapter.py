#!/usr/bin/env python3
"""Compare spectral adapter with a prior real-audio development run.

This is a source-informed software check, not a blind localization benchmark.
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from dopplergeist.audio import Spectrum
from dopplergeist.geometry import ecef
from dopplergeist.intake import IntakeRecording
from dopplergeist.search import event_score, score_candidate
from dopplergeist.spectral_matching import measure_spectral_event, score_spectral_association
from dopplergeist.tracks import load_tracks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="prior real-audio result directory")
    parser.add_argument("tracks", type=Path, help="historical trajectory Parquet")
    parser.add_argument("type_database", type=Path, help="type database used by the prior run")
    parser.add_argument("job", type=Path, help="completed real automatic job with decoded audio")
    args = parser.parse_args()
    row = json.loads((args.reference / "ranked.json").read_text())[0]
    events = json.loads((args.reference / "measured-events.json").read_text())
    measurements = []
    for i in range(len(events)):
        with np.load(args.reference / f"event-{i + 1}.npz") as data:
            spectrum = Spectrum(data["time"], data["frequency"], data["db"], data["contrast"])
            measurements.append((spectrum, data["ridge"], data["weight"], {}))
    tracks, _ = load_tracks(args.tracks, type_database=args.type_database)
    lookup = {track.id: track for track in tracks}
    point = SimpleNamespace(**{key: row[key] for key in ("point_id", "lat", "lon", "elev_m", "x", "y")})
    start = row["recording_start_time_s"]
    candidate = {"point_id": point.point_id,
                 "passes": [{"flight_id": flight, "receive_time": start + event["cpa_receive_s"]}
                            for flight, event in zip(row["flight_ids"], events)]}
    old = score_candidate(candidate, point, lookup, events, measurements, mode="brightness",
                          time_origin=start, time_sweep_s=1, time_step_s=0.5)
    selected = list(range(len(events)))
    spectra = [measurement[0] for measurement in measurements]
    observer = ecef(point.lat, point.lon, point.elev_m)
    args_to_score = (selected, row["flight_ids"], events, spectra, lookup, observer, (start - 1, start + 1))
    result = score_spectral_association(*args_to_score)
    for key in ("score", "event_scores", "f0_hz", "recording_start_time_s"):
        if old[key] != result[key]:
            raise AssertionError(f"Legacy and shared-clock spectral results differ: {key}")
    if result["evaluated_trials"] != 5 or not result["clock_grid_complete"]:
        raise AssertionError("Expected five supported shared-clock trials")
    subset = score_spectral_association([1], [row["flight_ids"][1]], events, spectra, lookup,
                                        observer, (start, start))
    single_score, single_f0 = event_score(lookup[row["flight_ids"][1]], observer, spectra[1], None, None,
                                          start, events[1]["f0_range_hz"], "brightness")
    if (subset["event_indices"] != [1] or subset["score"] != single_score
            or subset["f0_hz"] != [single_f0]):
        raise AssertionError("Subset scoring did not retain the chosen real event")
    if score_spectral_association(*args_to_score, max_clock_trials=4)["status"] != "work_limit":
        raise AssertionError("Clock work limit did not stop scoring")
    if score_spectral_association(*args_to_score, max_spectral_samples=1)["status"] != "work_limit":
        raise AssertionError("Spectral work limit did not stop scoring")
    missing = score_spectral_association(selected, row["flight_ids"], events, spectra, {}, observer, (start - 1, start + 1))
    if missing["status"] != "unavailable" or missing["unknown_trials"] != 5 or missing["clock_grid_complete"]:
        raise AssertionError("Missing tracks were not reported as unknown")
    metadata = json.loads((args.job / "intake/recording.json").read_text())
    recording = IntakeRecording(args.job / "intake/recording.f32", metadata, {})
    event = json.loads((args.job / "result.json").read_text())["events"][0]
    spectrum = measure_spectral_event(recording, event)
    if (not np.isfinite(spectrum.contrast).all() or spectrum.time[0] >= event["start_s"]
            or spectrum.time[-1] <= event["end_s"]):
        raise AssertionError("Measured spectrum lacks expected real-audio support")
    print(f"Matched legacy scores on {len(events)} groups and five shared clocks; "
          f"bounded actual discovery spectrum {spectrum.contrast.shape}. No location claim.")


if __name__ == "__main__":
    main()
