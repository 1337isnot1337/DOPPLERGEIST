"""Missing ADS-B motion fields must not create stationary aircraft samples.

The oracle is a constant Cartesian velocity, converted to readsb's geodetic
positions and ENU measurements with pyproj and an independent basis rotation.
Neither the package's ECEF conversion nor its velocity inference builds truth.
"""
import gzip
import json

import numpy as np
import pandas as pd
import pytest
from numpy.testing import assert_allclose
from pyproj import Transformer

from dopplergeist.tracks import adsblol_frame, load_tracks


EPOCH = 1_790_000_000.0
VELOCITY = np.array([82.0, -21.0, 6.0])
OFFSETS = np.array([0.0, 2.0, 6.0, 12.0, 20.0, 27.0])
TO_ECEF = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
TO_GEODETIC = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
ORIGIN = np.array(TO_ECEF.transform(-100.0, 40.0, 2000.0))
NULL_FIELDS = ("speed", "heading", "vertical_rate", "all")


def _enu_basis(lat_deg, lon_deg):
    lat, lon = np.deg2rad([lat_deg, lon_deg])
    return np.array([
        [-np.sin(lon), np.cos(lon), 0.0],
        [-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)],
        [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)],
    ])


def _trace(offsets=OFFSETS, velocity=VELOCITY, origin=ORIGIN):
    xyz = origin + (offsets - offsets[0])[:, None] * velocity
    lon, lat, height = TO_GEODETIC.transform(*xyz.T)
    rows = []
    for dt, latitude, longitude, altitude in zip(offsets, lat, lon, height):
        east, north, up = _enu_basis(latitude, longitude) @ velocity
        speed_knots = np.hypot(east, north) / (1852.0 / 3600.0)
        heading_deg = np.rad2deg(np.arctan2(east, north)) % 360.0
        altitude_ft = altitude / 0.3048
        vertical_rate_fpm = up / 0.00508
        rows.append([
            float(dt), float(latitude), float(longitude), float(altitude_ft),
            float(speed_knots), float(heading_deg), 0, float(vertical_rate_fpm),
            {"t": "C172"}, None, float(altitude_ft), float(vertical_rate_fpm),
        ])
    return {"icao": "a0b1c2", "timestamp": EPOCH, "trace": rows}


def _remove_fields(trace, fields, indices=None):
    if indices is None:
        indices = range(len(trace["trace"]))
    for index in indices:
        row = trace["trace"][index]
        if fields in ("speed", "all"):
            row[4] = None
        if fields in ("heading", "all"):
            row[5] = None
        if fields in ("vertical_rate", "all"):
            row[7] = row[11] = None


def _write_trace(tmp_path, trace, compressed=False):
    # readsb daily archives can contain gzip bytes under a .json filename.
    path = tmp_path / "trace_full_a0b1c2.json"
    payload = json.dumps(trace, allow_nan=False).encode()
    path.write_bytes(gzip.compress(payload) if compressed else payload)
    return path


def _assert_linear_track(track, origin, velocity):
    sample_times = np.unique(np.r_[track.time, (track.time[:-1] + track.time[1:]) / 2])
    expected_positions = origin + (sample_times - track.time[0])[:, None] * velocity
    # The importer currently rounds knots->m/s to six decimals. Permit that
    # harmless sub-mm/s difference without permitting zero or invented motion.
    assert_allclose(track.speed_vector(sample_times),
                    np.broadcast_to(velocity, (len(sample_times), 3)), atol=2e-4, rtol=0)
    assert_allclose(track.position(sample_times), expected_positions, atol=0.003, rtol=0)


@pytest.mark.parametrize("fields", NULL_FIELDS)
def test_adsblol_importer_preserves_unknown_velocity_components(fields):
    trace = _trace()
    _remove_fields(trace, fields, indices=[2])
    frame = adsblol_frame(trace)
    if fields in ("speed", "all"):
        assert pd.isna(frame.loc[2, "speed_mps"]), "unknown ground speed is not 0 m/s"
    if fields in ("speed", "heading", "all"):
        assert frame.loc[2, ["east_mps", "north_mps"]].isna().all(), (
            "unknown horizontal motion must remain nullable until track-local inference"
        )
    if fields in ("vertical_rate", "all"):
        assert pd.isna(frame.loc[2, "up_mps"]), "missing both climb-rate fields is not 0 m/s"
    assert np.isfinite(frame.loc[0, ["east_mps", "north_mps", "up_mps"]].to_numpy(dtype=float)).all()


@pytest.mark.parametrize("fields", NULL_FIELDS)
def test_load_tracks_infers_nullable_trace_velocity_from_positions(tmp_path, fields):
    trace = _trace()
    _remove_fields(trace, fields)
    tracks, report = load_tracks(_write_trace(tmp_path, trace))
    assert report["segments"] == len(tracks) == 1
    _assert_linear_track(tracks[0], ORIGIN, VELOCITY)


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_load_tracks_infers_partial_null_canonical_velocity(tmp_path, suffix):
    frame = adsblol_frame(_trace())
    # Canonical formats must work too; nulls can affect independent components
    # in different rows even when the velocity columns exist for the whole table.
    for row, column in [(1, "east_mps"), (2, "north_mps"), (3, "up_mps")]:
        frame.loc[row, column] = np.nan
    path = tmp_path / f"tracks.{suffix}"
    if suffix == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    tracks, _ = load_tracks(path)
    assert len(tracks) == 1
    _assert_linear_track(tracks[0], ORIGIN, VELOCITY)


def test_velocity_inference_uses_each_gap_split_segment(tmp_path):
    second_offsets = np.array([130.0, 132.0, 137.0, 143.0, 153.0])
    second_origin = ORIGIN + np.array([5000.0, -4000.0, 3000.0])
    second_velocity = np.array([-40.0, 15.0, -3.0])
    trace = _trace()
    trace["trace"].extend(_trace(second_offsets, second_velocity, second_origin)["trace"])
    _remove_fields(trace, "all")
    tracks, report = load_tracks(_write_trace(tmp_path, trace, compressed=True), max_gap_s=30.0)
    assert report["segments"] == len(tracks) == 2
    _assert_linear_track(tracks[0], ORIGIN, VELOCITY)
    _assert_linear_track(tracks[1], second_origin, second_velocity)
    # In particular, the last derivative before the gap and the first after it
    # must not use the distant segment's positions. There is no interpolation
    # through the unobserved interval either.
    middle_of_gap = (tracks[0].time[-1] + tracks[1].time[0]) / 2
    for track in tracks:
        assert np.isnan(track.position(middle_of_gap)).all()
        assert np.isnan(track.speed_vector(middle_of_gap)).all()


def test_measured_zero_velocity_is_preserved(tmp_path):
    trace = _trace()
    # A reported stop is a real derivative constraint even when the positions
    # before/after that knot would give a nonzero finite-difference slope.
    row = trace["trace"][2]
    row[4], row[5], row[7], row[11] = 0.0, None, 0.0, None
    frame = adsblol_frame(trace)
    assert_allclose(frame.loc[2, ["east_mps", "north_mps", "up_mps"]].to_numpy(dtype=float), 0.0)
    tracks, _ = load_tracks(_write_trace(tmp_path, trace))
    assert_allclose(tracks[0].speed_vector(EPOCH + row[0]), 0.0, atol=1e-12)


def test_missing_horizontal_velocity_keeps_measured_zero_climb(tmp_path):
    trace = _trace()
    row = trace["trace"][2]
    row[4] = row[5] = None
    row[7] = row[11] = 0.0
    basis = _enu_basis(row[1], row[2])
    expected_enu = basis @ VELOCITY
    expected_enu[2] = 0.0
    tracks, _ = load_tracks(_write_trace(tmp_path, trace))
    assert_allclose(tracks[0].speed_vector(EPOCH + row[0]), basis.T @ expected_enu, atol=2e-4, rtol=0)


def test_missing_climb_keeps_measured_zero_horizontal_velocity(tmp_path):
    trace = _trace()
    row = trace["trace"][2]
    row[4], row[5], row[7], row[11] = 0.0, None, None, None
    basis = _enu_basis(row[1], row[2])
    expected_enu = basis @ VELOCITY
    expected_enu[:2] = 0.0
    tracks, _ = load_tracks(_write_trace(tmp_path, trace))
    assert_allclose(tracks[0].speed_vector(EPOCH + row[0]), basis.T @ expected_enu, atol=2e-4, rtol=0)
