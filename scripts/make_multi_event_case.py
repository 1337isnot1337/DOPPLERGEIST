"""Render an independent multi-flyover MP3 fixture with separately stored truth.

No dopplergeist code is imported. A source oscillator is transported from
emission time to arrival time using geometric distance. The first two passes
have similar remote distractors; later passes have different timing/geometry.
This is a finite synthetic population, not a real-world accuracy benchmark.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
import soundfile as sf


RATE = 8000
EPOCH = 1790000000.0
GROUND = 120.0
SOUND_SPEED = 343.0
REGIONS = [(40.0, -100.0), (35.0, -90.0), (43.0, -112.0)]
EARTH = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)


def transport(emission_s, distance_m, emitted, receive_s, c=SOUND_SPEED):
    arrival_s = emission_s + distance_m / c
    if np.any(np.diff(arrival_s) <= 0):
        raise ValueError("The synthetic source must have increasing arrival time")
    return np.interp(receive_s, arrival_s, emitted, left=0.0, right=0.0)


def path(t, event, variant, inverse, offset):
    angle = np.deg2rad([20, 105, 185, 270, 65, 325][event])
    if event >= 2:
        angle += 0.21 * variant
    speed = 72.0 + 6.0 * event
    along = speed * t + 0.018 * t**2
    cross = 700.0 + 110.0 * event + 0.055 * t**2
    cross += variant * (0.0002 * t**3 if event >= 2 else 0)
    x = offset[0] + along * np.cos(angle) - cross * np.sin(angle)
    y = offset[1] + along * np.sin(angle) + cross * np.cos(angle)
    lon, lat = inverse.transform(x, y)
    alt = GROUND + 1050.0 + 130.0 * event + (0.4 - 0.1 * event) * t
    return np.asarray(lon), np.asarray(lat), np.asarray(alt)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def generate(output, event_count=4, seed=20261103):
    if event_count not in (3, 4, 6):
        raise ValueError("Choose 3, 4 or 6 independent flyovers")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs, truth_dir, renderer = (output / name for name in ("inputs", "truth", "renderer"))
    for directory in (inputs, truth_dir, renderer):
        directory.mkdir()
    rng = np.random.default_rng(seed)
    duration = 220 * event_count + 80
    receive = np.arange(duration * RATE, dtype=np.float64) / RATE
    audio = rng.normal(0, 0.12, len(receive))
    audio += 0.025 * np.sin(2 * np.pi * 60 * receive)
    audio += 0.015 * np.sin(2 * np.pi * 1200 * receive)
    location = [40.03173, -100.01829]
    observer = np.asarray(EARTH.transform(location[1], location[0], GROUND))
    labels, rows, mapping = [], [], []
    kinds = ["C172", "PC12", "A320", "", "C208", "B350"]
    for variant, (latitude, longitude) in enumerate(REGIONS):
        projection = f"+proj=aeqd +lat_0={latitude} +lon_0={longitude} +datum=WGS84 +units=m"
        inverse = Transformer.from_crs(projection, "EPSG:4326", always_xy=True)
        forward = Transformer.from_crs("EPSG:4326", projection, always_xy=True)
        offset = forward.transform(location[1], location[0]) if variant == 0 else (0.0, 0.0)
        for event in range(event_count):
            identity = hashlib.sha256(f"{seed}:traffic:{variant}:{event}".encode()).hexdigest()[:12]
            center = 150.0 + 220 * event
            if variant and event >= 2:
                center += variant * (27 if event % 2 else -31)
            t = np.arange(-135.0, 136.0)
            lon, lat, alt = path(t, event, variant, inverse, offset)
            # Model velocities from a small independent central difference in
            # ECEF, then rotate to each sample's local ENU frame.
            before = np.column_stack(EARTH.transform(*path(t - 0.001, event, variant, inverse, offset)))
            after = np.column_stack(EARTH.transform(*path(t + 0.001, event, variant, inverse, offset)))
            vx, vy, vz = ((after - before) / 0.002).T
            phi, lam = np.deg2rad(lat), np.deg2rad(lon)
            east = -np.sin(lam) * vx + np.cos(lam) * vy
            north = -np.sin(phi) * np.cos(lam) * vx - np.sin(phi) * np.sin(lam) * vy + np.cos(phi) * vz
            up = np.cos(phi) * np.cos(lam) * vx + np.cos(phi) * np.sin(lam) * vy + np.sin(phi) * vz
            for j in range(len(t)):
                rows.append({"flight_id": identity, "time_s": EPOCH + center + t[j],
                    "lat": lat[j], "lon": lon[j], "alt_m": alt[j], "typecode": kinds[event],
                    "east_mps": east[j], "north_mps": north[j], "up_mps": up[j],
                    "altitude_basis": "ellipsoidal"})
            mapping.append({"flight_id": identity, "variant": variant, "event": event})
            if variant:
                continue
            emitted_time = np.arange(-100 * RATE, 100 * RATE, dtype=np.float64) / RATE
            source = np.column_stack(EARTH.transform(*path(emitted_time, event, 0, inverse, offset)))
            distance = np.linalg.norm(source - observer, axis=1)
            frequency = 135.0 + 23.0 * event
            taper = np.minimum(1.0, np.maximum(0.0, (100 - np.abs(emitted_time)) / 8))
            amplitude = 0.08 * np.minimum(1, 1800 / distance) * taper
            oscillator = amplitude * (np.sin(2 * np.pi * frequency * emitted_time)
                + 0.3 * np.sin(2 * np.pi * 2 * frequency * emitted_time + 0.4))
            audio += transport(center + emitted_time, distance, oscillator, receive)
            labels.append({"flight_id": identity, "start_s": float(center + emitted_time[0] + distance[0] / SOUND_SPEED),
                "end_s": float(center + emitted_time[-1] + distance[-1] / SOUND_SPEED),
                "center_emission_s": center, "source_frequency_hz": frequency})
    # One common gain preserves relative source/noise strengths without clipping.
    audio /= max(1.0, float(np.max(np.abs(audio))) / 0.95)
    wav = renderer / "recording.wav"
    sf.write(wav, audio, RATE, subtype="FLOAT")
    command = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(wav), "-c:a", "libmp3lame",
               "-b:a", "32k", str(inputs / "recording.mp3")]
    subprocess.run(command, check=True)
    pd.DataFrame(rows).to_parquet(inputs / "tracks.parquet", index=False)
    for name, height in (("terrain.tif", GROUND), ("geoid.tif", 0.0)):
        with rasterio.open(inputs / name, "w", driver="GTiff", width=360, height=180, count=1,
            dtype="float32", crs="EPSG:4326", transform=from_origin(-180, 90, 1, 1), compress="deflate") as raster:
            raster.write(np.full((180, 360), height, dtype="float32"), 1)
            raster.update_tags(synthetic="true", vertical_datum="synthetic_common_datum")
    write_json(inputs / "coverage.json", {"bounds": [-180.0, -85.0, 180.0, 85.0],
        "time_range_s": [EPOCH - 300, EPOCH + duration + 300], "all_aircraft": True,
        "source_kind": "complete_finite_synthetic_population", "real_receiver_coverage": False})
    clock = datetime.fromtimestamp(EPOCH, timezone.utc).isoformat().replace("+00:00", "Z")
    write_json(inputs / "request.json", {"schema_version": 1, "audio_path": "recording.mp3",
        "time_window": {"start_utc": clock, "end_utc": clock, "source": "user"},
        "search": {"coverage": "conus"}})
    write_json(truth_dir / "labels.json", {"location": location, "elevation_m": GROUND,
        "recording_start_utc": clock, "events": labels, "traffic_identity_map": mapping,
        "scope": "independent synthetic renderer", "acceptable_error_m": 1000,
        "preferred_error_m": 500, "reported_thresholds_m": [100, 500, 1000]})
    manifest = {"schema_version": 1, "scope": "synthetic multi-event development fixture",
        "seed": seed, "event_count": event_count, "duration_s": duration, "sample_rate_hz": RATE,
        "generator_sha256": digest(Path(__file__)), "encoder_command": command,
        "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        "input_files": {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(inputs.iterdir())},
        "renderer_wav_sha256": digest(wav), "truth_sha256": digest(truth_dir / "labels.json"),
        "limits": ["Finite synthetic traffic is not a real national archive.",
                   "The first two events have similar remote distractors; later passes differ.",
                   "Do not mount this manifest, generator, renderer or truth directory in a blinded search."]}
    write_json(output / "generation.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events", type=int, choices=(3, 4, 6), default=4)
    parser.add_argument("--seed", type=int, default=20261103)
    args = parser.parse_args()
    result = generate(args.output, args.events, args.seed)
    print(json.dumps({"output": str(args.output.resolve()), "event_count": result["event_count"],
                      "duration_s": result["duration_s"], "input_files": result["input_files"]}))


if __name__ == "__main__":
    main()
