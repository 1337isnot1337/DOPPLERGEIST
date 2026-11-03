"""Render an independent multi-flyover MP3 fixture with separately stored truth.

No aircraft_geoloc code is imported. A source oscillator is transported from
emission time to arrival time using geometric distance. The first two passes
have similar remote distractors; later passes have different timing/geometry.
This is a finite synthetic population, not a real-world accuracy benchmark.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
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
GEODETIC = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
FIXTURE_VARIANTS = ("local-segments", "full-coverage")
MAX_CANDIDATE_RANGE_M = 20000.0
TRAJECTORY_SPEED_BOUND_MPS = 0.4 * SOUND_SPEED
MIN_SUPPORT_SOUND_SPEED_MPS = SOUND_SPEED - 5.0
RIGHT_COVERAGE_PADDING_S = 300


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


def full_support_plan(duration_s):
    """Predeclare support for every receive time and range-gated candidate.

    The receiver's distance from the first point is at most R+V*(D+Q+P).
    The chosen P makes its first arrival precede sample zero even at c=338.
    The last arrival follows D+Q. Subsonic motion makes arrival monotone.
    """
    speed, sound = TRAJECTORY_SPEED_BOUND_MPS, MIN_SUPPORT_SOUND_SPEED_MPS
    padding = math.ceil((MAX_CANDIDATE_RANGE_M + speed * (duration_s + RIGHT_COVERAGE_PADDING_S))
                        / (sound - speed)) + 2
    first_arrival = -padding + (MAX_CANDIDATE_RANGE_M
        + speed * (duration_s + RIGHT_COVERAGE_PADDING_S + padding)) / sound
    return {"fixture_variant": "full-coverage", "minimum_sound_speed_mps": sound,
        "support_scope": "nominal_cpa_receiver_domain",
        "receiver_domain": "Nominal coarse/fine CPA receivers within the declared range; no analytic refinement/profile receiver guarantee.",
        "refinement_and_profile_support": "Separately checked by unchanged runtime fit and acceptance gates.",
        "maximum_candidate_range_m": MAX_CANDIDATE_RANGE_M, "speed_bound_mps": speed,
        "left_padding_s": padding, "right_padding_s": RIGHT_COVERAGE_PADDING_S,
        "emission_interval_s": [EPOCH - padding, EPOCH + duration_s + RIGHT_COVERAGE_PADDING_S],
        "guaranteed_receive_interval_s": [EPOCH, EPOCH + duration_s],
        "start_arrival_upper_bound_s": EPOCH + first_arrival,
        "end_arrival_lower_bound_s": EPOCH + duration_s + RIGHT_COVERAGE_PADDING_S,
        "arrival_monotonicity_lower_bound": 1 - speed / sound,
        "support_assumptions": ["Receiver lies within the declared range of a track point or sampled CPA chord.",
            "The serialized trajectory satisfies the continuous Hermite speed bound.",
            "Receive times lie within the audio interval; sound speed is at least the declared minimum."]}


def serialized_motion(frame):
    """Reconstruct WGS84 positions and supplied ENU velocities independently."""
    lon, lat, height = (frame[name].to_numpy(dtype=float) for name in ("lon", "lat", "alt_m"))
    position = np.column_stack(EARTH.transform(lon, lat, height))
    east, north, up = (frame[name].to_numpy(dtype=float) for name in ("east_mps", "north_mps", "up_mps"))
    phi, lam = np.deg2rad(lat), np.deg2rad(lon)
    velocity = np.column_stack((-np.sin(lam) * east - np.sin(phi) * np.cos(lam) * north + np.cos(phi) * np.cos(lam) * up,
        np.cos(lam) * east - np.sin(phi) * np.sin(lam) * north + np.cos(phi) * np.sin(lam) * up,
        np.cos(phi) * north + np.sin(phi) * up))
    return position, velocity


def hermite_speed_control_bound(times, position, velocity):
    """Bound continuous speed by the three quadratic Bezier velocity controls."""
    dt = np.diff(times)
    if len(dt) == 0 or not np.all(np.isfinite(dt)) or np.any(dt <= 0):
        raise ValueError("Trajectory times must be finite and strictly increasing")
    middle = 3 * np.diff(position, axis=0) / dt[:, None] - velocity[:-1] - velocity[1:]
    return float(max(np.max(np.linalg.norm(velocity, axis=1)), np.max(np.linalg.norm(middle, axis=1))))


def extend_trajectory(core_rows, plan):
    """Add generated ECEF tangent samples while keeping every original row."""
    core = pd.DataFrame(core_rows)
    position, velocity = serialized_motion(core)
    first, last = plan["emission_interval_s"]

    def tail(times, endpoint):
        anchor = core_rows[endpoint]
        xyz = position[endpoint] + (times - anchor["time_s"])[:, None] * velocity[endpoint]
        lon, lat, height = GEODETIC.transform(*xyz.T)
        phi, lam = np.deg2rad(lat), np.deg2rad(lon)
        vx, vy, vz = velocity[endpoint]
        east = -np.sin(lam) * vx + np.cos(lam) * vy
        north = -np.sin(phi) * np.cos(lam) * vx - np.sin(phi) * np.sin(lam) * vy + np.cos(phi) * vz
        up = np.cos(phi) * np.cos(lam) * vx + np.cos(phi) * np.sin(lam) * vy + np.sin(phi) * vz
        return [dict(anchor, time_s=float(t), lon=float(lo), lat=float(la), alt_m=float(h),
            east_mps=float(e), north_mps=float(n), up_mps=float(u))
            for t, lo, la, h, e, n, u in zip(times, lon, lat, height, east, north, up)]

    before = np.arange(first, core_rows[0]["time_s"], dtype=float)
    after = np.arange(core_rows[-1]["time_s"] + 1, last + 1, dtype=float)
    return tail(before, 0) + core_rows + tail(after, -1)


def certify_full_coverage(frame, core_frame, plan):
    """Certify actual Parquet values, untouched core rows, and C1 joins."""
    reports = []
    first, last = plan["emission_interval_s"]
    expected_times = np.arange(first, last + 1, dtype=float)
    for identity, core in core_frame.groupby("flight_id", sort=True):
        track = frame.loc[frame.flight_id == identity].reset_index(drop=True)
        core = core.reset_index(drop=True)
        times = track.time_s.to_numpy(dtype=float)
        if not np.array_equal(times, expected_times):
            raise ValueError("Aircraft does not cover the exact common emission grid")
        original = track.loc[track.time_s.isin(core.time_s)].reset_index(drop=True)
        if not original.equals(core):
            raise ValueError("An original trajectory sample changed during extension or serialization")
        position, velocity = serialized_motion(track)
        if (not np.all(np.isfinite(np.column_stack((position, velocity))))
                or not track.lat.between(-85, 85).all() or not track.lon.between(-180, 180).all()
                or not track.alt_m.between(GROUND + 1, 20000).all()):
            raise ValueError("Extended coordinates or altitude are outside the declared valid domain")
        speed = hermite_speed_control_bound(times, position, velocity)
        if not math.isfinite(speed) or speed >= plan["speed_bound_mps"]:
            raise ValueError("Trajectory does not satisfy the predeclared subsonic speed bound")
        joins = []
        for time_s, neighbor in ((core.time_s.iloc[0], -1), (core.time_s.iloc[-1], 1)):
            index = int(np.flatnonzero(times == time_s)[0])
            other = index + neighbor
            predicted = position[index] + (times[other] - times[index]) * velocity[index]
            position_error = float(np.linalg.norm(position[other] - predicted))
            velocity_error = float(np.linalg.norm(velocity[other] - velocity[index]))
            if position_error > 1e-6 or velocity_error > 1e-8:
                raise ValueError("Tangent tail does not preserve the endpoint position and velocity")
            joins.append({"time_s": float(time_s), "tangent_position_roundtrip_error_m": position_error,
                          "velocity_roundtrip_error_mps": velocity_error})
        reports.append({"flight_id": str(identity), "samples": len(track), "original_samples": len(core),
            "original_rows_preserved": True, "maximum_hermite_speed_control_mps": speed,
            "altitude_range_m": [float(track.alt_m.min()), float(track.alt_m.max())],
            "joins": joins, "interpolant_position_and_velocity_continuous": True})
    if len(reports) != frame.flight_id.nunique() or not reports:
        raise ValueError("Trajectory certificate does not cover every aircraft")
    return dict(plan, samples_per_track=len(expected_times), aircraft_count=len(reports),
        maximum_hermite_speed_control_mps=max(row["maximum_hermite_speed_control_mps"] for row in reports),
        original_rows_preserved=True, position_join_tolerance_m=1e-6, velocity_join_tolerance_mps=1e-8,
        continuity="C1 position/velocity joins; acceleration continuity is not asserted", tracks=reports)


def generate(output, event_count=4, seed=20261103, fixture_variant="local-segments"):
    if event_count not in (3, 4, 6):
        raise ValueError("Choose 3, 4 or 6 independent flyovers")
    if fixture_variant not in FIXTURE_VARIANTS:
        raise ValueError("Unknown fixture variant")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs, truth_dir, renderer = (output / name for name in ("inputs", "truth", "renderer"))
    for directory in (inputs, truth_dir, renderer):
        directory.mkdir()
    rng = np.random.default_rng(seed)
    duration = 220 * event_count + 80
    support_plan = full_support_plan(duration) if fixture_variant == "full-coverage" else None
    receive = np.arange(duration * RATE, dtype=np.float64) / RATE
    audio = rng.normal(0, 0.12, len(receive))
    audio += 0.025 * np.sin(2 * np.pi * 60 * receive)
    audio += 0.015 * np.sin(2 * np.pi * 1200 * receive)
    location = [40.03173, -100.01829]
    observer = np.asarray(EARTH.transform(location[1], location[0], GROUND))
    labels, rows, core_rows, mapping = [], [], [], []
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
            original = []
            for j in range(len(t)):
                original.append({"flight_id": identity, "time_s": EPOCH + center + t[j],
                    "lat": lat[j], "lon": lon[j], "alt_m": alt[j], "typecode": kinds[event],
                    "east_mps": east[j], "north_mps": north[j], "up_mps": up[j],
                    "altitude_basis": "ellipsoidal"})
            core_rows.extend(original)
            rows.extend(extend_trajectory(original, support_plan) if support_plan else original)
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
    support = (certify_full_coverage(pd.read_parquet(inputs / "tracks.parquet"), pd.DataFrame(core_rows), support_plan)
               if support_plan else None)
    for name, height in (("terrain.tif", GROUND), ("geoid.tif", 0.0)):
        with rasterio.open(inputs / name, "w", driver="GTiff", width=360, height=180, count=1,
            dtype="float32", crs="EPSG:4326", transform=from_origin(-180, 90, 1, 1), compress="deflate") as raster:
            raster.write(np.full((180, 360), height, dtype="float32"), 1)
            raster.update_tags(synthetic="true", vertical_datum="synthetic_common_datum")
    coverage = {"bounds": [-180.0, -85.0, 180.0, 85.0],
        "time_range_s": [EPOCH - 300, EPOCH + duration + 300], "all_aircraft": True,
        "source_kind": "complete_finite_synthetic_population", "real_receiver_coverage": False}
    if support:
        coverage.update(time_range_s=support["emission_interval_s"],
            trajectory_support={key: value for key, value in support.items() if key != "tracks"})
    write_json(inputs / "coverage.json", coverage)
    clock = datetime.fromtimestamp(EPOCH, timezone.utc).isoformat().replace("+00:00", "Z")
    write_json(inputs / "request.json", {"schema_version": 1, "audio_path": "recording.mp3",
        "time_window": {"start_utc": clock, "end_utc": clock, "source": "user"},
        "search": {"coverage": "conus"}})
    write_json(truth_dir / "labels.json", {"location": location, "elevation_m": GROUND,
        "recording_start_utc": clock, "events": labels, "traffic_identity_map": mapping,
        "scope": "independent synthetic renderer", "acceptable_error_m": 1000,
        "preferred_error_m": 500, "reported_thresholds_m": [100, 500, 1000]})
    manifest = {"schema_version": 1, "scope": "synthetic multi-event development fixture",
        "fixture_variant": fixture_variant, "trajectory_support": support,
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
    parser.add_argument("--fixture-variant", choices=FIXTURE_VARIANTS, default="local-segments")
    args = parser.parse_args()
    result = generate(args.output, args.events, args.seed, args.fixture_variant)
    print(json.dumps({"output": str(args.output.resolve()), "event_count": result["event_count"],
                      "duration_s": result["duration_s"], "input_files": result["input_files"]}))


if __name__ == "__main__":
    main()
