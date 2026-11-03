#!/usr/bin/env python3
"""Measured WSU drone session: discovery, conditional fitting, then evaluation.

This is a supplied-trajectory experiment outside the CONUS/absolute-UTC product
path. The published camera-based audio/GPS alignment has unmeasured uncertainty.
Receiver coordinates are read only by the separate evaluate command. Discovery
keeps production defaults and reads the complete, preselected first microphone.
No waveform, trajectory, recording date, or successful decision is fabricated.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
import pandas as pd
from pyproj import Geod, Transformer
from scipy.io import wavfile

from dopplergeist.discovery import DiscoverySettings, discover_events
from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.intake import intake_recording
from dopplergeist.matching import fit_ridge, prepare_events


BASE = "https://rds.westernsydney.edu.au/Centres/ICNS/2026/Jahir_Rodriguez/"
SESSION = "dataset/test_1/Oct_11_2024/flight_5/"
SCOPE = "real_WSU_supplied_trajectory_published_relative_alignment"
DATASET = {
    "title": "UAV Acoustic Localization Dataset",
    "creators": "Belman Jahir Rodríguez, Sergio F. Chevtchenko, Marcelo Herrera Martínez, Yeshwanth Bethi, Saeed Afshar",
    "doi": "https://doi.org/10.26183/07nm-4p35",
    "license": "CC BY-SA 4.0; external recordings and metadata retain that license",
}
# Identities of the actual official files retrieved for this experiment. These
# pins identify the downloaded versions; they are not publisher-issued hashes.
SOURCES = {
    "audio": (284313644, "b209a042aac5b9abcd575ecc71ceb1c162021ca86771a5295c9d7dd6ce18c825"),
    "flight": (579075, "77974bf089826d8da23f3de50874cda26bf678de81d80051f44ec5b083be8424"),
    "alignment": (946, "cd2145d0adb74faa7650671d08ebff971f1861aa5105f48ce47ce7eea49c2a91"),
    "reference": (402253, "b1f105b477bea3c5682aaa884ca11f63bfcf391af701e040ce098dfb0bb033fc"),
}
LIMITS = [
    "One supplied measured trajectory; aircraft identity is not established by fitting.",
    "Published camera-based relative alignment has no measured timing uncertainty.",
    "Common MSL heights are used as a local ECEF approximation; datum accuracy is unverified.",
    "Flat receiver height uses the initial aircraft altitude plus published microphone height.",
    "Search covers the supplied flight footprint plus a fixed margin, not national coverage.",
    "No complete background flight inventory, calibrated uncertainty, or accepted location.",
    "Public development measurement; no sealed holdout or product acceptance assessment.",
]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_source(path, role):
    expected_size, expected_digest = SOURCES[role]
    if Path(path).stat().st_size != expected_size or digest(path) != expected_digest:
        raise ValueError(f"Not the pinned official WSU {role} input")


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def write(path, value):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(plain(value), indent=2, allow_nan=False) + "\n")


def read(path):
    return json.loads(Path(path).read_text())


def new_directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def discover(args):
    output = new_directory(args.output)
    began = time.monotonic()
    source = Path(args.audio).resolve()
    verify_source(source, "audio")
    rate, samples = wavfile.read(source, mmap=True)
    if rate != 48000 or samples.dtype != np.int32 or samples.ndim != 2 or samples.shape[1] != 6:
        raise ValueError("Expected the original six-channel 48 kHz PCM32 WSU recording")
    # Device 1/channel 1 is declared before acoustic inspection; retain all frames.
    mono = output / "device1-channel1.wav"
    wavfile.write(mono, rate, samples[:, 0])
    recording = intake_recording(mono, output / "intake")
    settings = DiscoverySettings()
    events = discover_events(recording, output_dir=output / "discovery", settings=settings)
    summary = {
        "scope": SCOPE, "dataset": DATASET,
        "source_url": BASE + SESSION + "device_1_nosync.wav",
        "source_path": str(source), "source_size_bytes": source.stat().st_size,
        "source_sha256": SOURCES["audio"][1], "mono_channel_one_based": 1,
        "source_frames": len(samples), "source_sample_rate_hz": rate,
        "source_duration_s": len(samples) / rate,
        "complete_recording_used": True, "discovery_settings": asdict(settings),
        "event_count": len(events),
        "independent_proposal_count": len({event["harmonic_group_id"] for event in events}),
        "events": [{k: event[k] for k in ("event_id", "start_s", "end_s", "band_hz")} for event in events],
        "trajectory_or_truth_loaded": False, "runtime_s": time.monotonic() - began,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True).strip(),
        "accepted_location": False, "limitations": LIMITS,
    }
    write(output / "summary.json", summary)
    print(json.dumps(plain(summary), indent=2))


def load_trajectory(csv_path, alignment_path):
    verify_source(csv_path, "flight")
    verify_source(alignment_path, "alignment")
    alignment = read(alignment_path)
    if (alignment.get("session") != "Oct_11_2024" or str(alignment.get("flight_id")) != "5"
            or alignment.get("sample_rate_hz") != 48000
            or alignment.get("corrections_samples", [None])[0] != 0):
        raise ValueError("Expected the published device-1 alignment for WSU test session 1")
    frame = pd.read_csv(csv_path)
    columns = ["time(millisecond)", "latitude", "longitude", "altitude_above_seaLevel(feet)"]
    values = frame[columns].to_numpy(dtype=float)
    if len(values) < 3 or not np.all(np.isfinite(values)) or not np.all(np.diff(values[:, 0]) > 0):
        raise ValueError("Measured trajectory rows must be finite and strictly timed; no repair is performed")
    index = alignment["start_index_csv"]
    if type(index) is not int or not 0 <= index < len(values):
        raise ValueError("Published alignment row is outside the measured trajectory")
    # The publisher aligns its 100 ms audio blocks to successive telemetry rows.
    if not np.allclose(np.diff(values[:, 0]), 100, rtol=0, atol=1e-8):
        raise ValueError("Telemetry does not support the publisher's one-row-per-100-ms mapping")
    clock = float(alignment["skip_seconds"]) + (values[:, 0] - values[index, 0]) / 1000
    height = values[:, 3] * 0.3048
    track = Track("WSU-published-flight-5", clock, values[:, 1], values[:, 2], height,
                  "DJI Air 3 measured telemetry")
    track.altitude_basis = ["publisher_MSL_unverified"] * len(clock)
    return track, alignment


def search(args):
    output = new_directory(args.output)
    began = time.monotonic()
    summary = read(Path(args.discovery) / "summary.json")
    if summary.get("source_sha256") != SOURCES["audio"][1] or summary.get("complete_recording_used") is not True:
        raise ValueError("Expected complete-recording discovery from the pinned WSU audio")
    discovery = read(Path(args.discovery) / "discovery" / "discovery.json")
    events, measurements = prepare_events(discovery["events"])
    track, alignment = load_trajectory(args.flight_csv, args.alignment)
    forward = Transformer.from_crs("EPSG:4326", "EPSG:32756", always_xy=True)
    inverse = Transformer.from_crs("EPSG:32756", "EPSG:4326", always_xy=True)
    x, y = forward.transform(track.lon, track.lat)
    step, margin = args.grid_step_m, args.padding_m
    if not np.isfinite(step) or not np.isfinite(margin) or step <= 0 or margin <= 0:
        raise ValueError("Grid step and flight-footprint margin must be finite and positive")
    bounds = [np.floor((min(x) - margin) / 100) * 100, np.floor((min(y) - margin) / 100) * 100,
              np.ceil((max(x) + margin) / 100) * 100, np.ceil((max(y) + margin) / 100) * 100]
    east = np.arange(bounds[0] + step / 2, bounds[2], step)
    north = np.arange(bounds[1] + step / 2, bounds[3], step)
    if not len(east) or not len(north) or len(east) * len(north) > args.max_grid_points:
        raise ValueError("Empty grid or explicit work budget exceeded; search was not truncated")
    receiver_height = float(track.altitude[0] + alignment["mic_array"]["h_"][0])
    motion = {"globally_subsonic": True}
    try:
        track.validate_motion_support()
    except AcousticSupportError as error:
        motion = {"globally_subsonic": False, "reason": error.reason}
    result = {"scope": SCOPE, "dataset": DATASET, "source_revision": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True).strip(),
        "source_urls": {"audio": BASE + SESSION + "device_1_nosync.wav",
                        "flight": BASE + SESSION + "Oct-11th-2024-03-49PM-Flight-Airdata.csv",
                        "alignment": BASE + SESSION + "alignment_params.json"},
        "audio_clock_mapping": "t_audio = skip_seconds + (time_millisecond - aligned_row_time_millisecond)/1000",
        "skip_seconds": alignment["skip_seconds"], "start_index_csv": alignment["start_index_csv"],
        "absolute_UTC_uncertainty_established": False, "all_measured_trajectory_rows_retained": True,
        "trajectory_rows": len(track.time), "trajectory_audio_time_bounds_s": track.time[[0, -1]],
        "motion_support": motion, "receiver_height_msl_approximation_m": receiver_height,
        "search_domain": {"source": "measured flight footprint plus fixed margin, rounded outward to100m",
                          "crs": "EPSG:32756", "bounds": bounds, "step_m": step, "padding_m": margin,
                          "grid_nodes": "cell centers; no target coordinate inserted"},
        "events_retained": len(events), "results": [], "reference_coordinates_loaded": False,
        "accepted_location": False, "limitations": LIMITS}
    for i, (event, measurement) in enumerate(zip(events, measurements)):
        for drift in (0.0, 0.02):
            loss = np.full((len(north), len(east)), np.nan)
            reasons = Counter()
            best = None
            for iy, yy in enumerate(north):
                for ix, xx in enumerate(east):
                    lon, lat = inverse.transform(xx, yy)
                    try:
                        fit = fit_ridge(track, ecef(lat, lon, receiver_height), measurement, 0.0,
                            event["f0_range_hz"], 343.0, event["quality"]["frequency_loss_scale_hz"], drift)
                    except AcousticSupportError as error:
                        reasons[error.reason] += 1
                        continue
                    if not np.isfinite(fit.get("score", np.nan)) or fit.get("support_fraction") != 1.0:
                        reasons["incomplete_trajectory_or_ridge_support"] += 1
                        continue
                    loss[iy, ix] = -fit["score"]
                    if best is None or loss[iy, ix] < best["loss_hz"]:
                        best = {"lat": lat, "lon": lon, "east_m": xx, "north_m": yy,
                                "loss_hz": loss[iy, ix], "fit": fit,
                                "domain_edge": ix in (0, len(east) - 1) or iy in (0, len(north) - 1)}
            identity = f"event-{i:03d}-drift-{drift:g}"
            np.savez_compressed(output / (identity + ".npz"), east_m=east, north_m=north, loss_hz=loss)
            item = {"id": identity, "event_id": event["event_id"], "source_drift_fraction": drift,
                    "grid_points": loss.size, "supported_points": np.isfinite(loss).sum(),
                    "unknown_points": (~np.isfinite(loss)).sum(), "unknown_reasons": dict(reasons),
                    "best": best, "unique_location_established": False}
            if best is not None:
                yy, xx = np.where(np.isfinite(loss) & (loss <= best["loss_hz"] + 1.0))
                item["within_one_hz_radius_m"] = np.max(np.hypot(east[xx] - best["east_m"], north[yy] - best["north_m"]))
            result["results"].append(item)
    result["status"] = ("no_proposal" if not events else "no_supported_fit"
                        if all(row["best"] is None for row in result["results"]) else "conditional_fits_only")
    result["runtime_s"] = time.monotonic() - began
    result["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(output / "result.json", result)
    print(json.dumps(plain(result), indent=2))


def evaluate(args):
    result = read(Path(args.search) / "result.json")
    if result.get("scope") != SCOPE or result.get("reference_coordinates_loaded") is not False:
        raise ValueError("Expected frozen WSU search results without reference coordinates")
    verify_source(args.reference_csv, "reference")
    reference = pd.read_csv(args.reference_csv)
    lat = reference["latitude"].astype(float).mean()
    lon = reference["longitude"].astype(float).mean()
    if not np.isfinite(lat) or not np.isfinite(lon):
        raise ValueError("Invalid published reference coordinate")
    geod = Geod(ellps="WGS84")
    rows = []
    for case in result["results"]:
        row = {"id": case["id"], "accepted_location": False, "source_association": "unconfirmed"}
        if case["best"] is not None:
            best = case["best"]
            error = geod.inv(lon, lat, best["lon"], best["lat"])[2]
            row.update(horizontal_error_to_published_array_origin_m=error,
                       within_100_m=error <= 100, within_500_m=error <= 500, within_1000_m=error <= 1000)
        rows.append(row)
    report = {"scope": SCOPE, "dataset": DATASET, "frozen_search": str(Path(args.search).resolve()),
              "reference_source": BASE + "dataset/test_1/Oct_11_2024/ref/DJIFlightRecord_2024-10-11_%5B14-32-34%5D.csv",
              "reference_kind": "Publisher reference-flight mean GPS, not an independently surveyed microphone",
              "reference_rows": len(reference), "mic_horizontal_offset_m": 0.1,
              "measured_reference_uncertainty_available": False, "results": rows,
              "accepted_location": False, "limitations": LIMITS}
    write(args.output, report)
    print(json.dumps(plain(report), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("discover")
    command.add_argument("--audio", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(function=discover)
    command = commands.add_parser("search")
    command.add_argument("--discovery", required=True)
    command.add_argument("--flight-csv", required=True)
    command.add_argument("--alignment", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--grid-step-m", type=float, default=50.0)
    command.add_argument("--padding-m", type=float, default=500.0)
    command.add_argument("--max-grid-points", type=int, default=10000)
    command.set_defaults(function=search)
    command = commands.add_parser("evaluate")
    command.add_argument("--search", required=True)
    command.add_argument("--reference-csv", required=True)
    command.add_argument("--output", required=True)
    command.set_defaults(function=evaluate)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
