"""Whole-segment indexing must preserve the continuous aircraft geometry."""

import numpy as np
from numpy.testing import assert_allclose
import pandas as pd
from pyproj import Transformer
import pytest


data_access = pytest.importorskip("dopplergeist.data_access")
FlightIndex = data_access.FlightIndex

EPOCH = 1_790_000_000.0
TO_ECEF = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
FROM_ECEF = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)


def _basis(lat, lon):
    """Analytic ENU basis vectors, independent of the importer and index."""
    phi, lam = np.deg2rad(lat), np.deg2rad(lon)
    east = np.stack((-np.sin(lam), np.cos(lam), np.zeros_like(lam)), axis=-1)
    north = np.stack(
        (-np.sin(phi) * np.cos(lam), -np.sin(phi) * np.sin(lam), np.cos(phi)),
        axis=-1,
    )
    up = np.stack(
        (np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)),
        axis=-1,
    )
    return east, north, up


def _frame(xyz, velocity, times, flight_id):
    lon, lat, altitude = FROM_ECEF.transform(*xyz.T)
    east, north, up = _basis(lat, lon)
    return pd.DataFrame({
        "flight_id": flight_id,
        "time_s": times,
        "lat": lat,
        "lon": lon,
        "alt_m": altitude,
        "east_mps": np.sum(velocity * east, axis=1),
        "north_mps": np.sum(velocity * north, axis=1),
        "up_mps": np.sum(velocity * up, axis=1),
        "altitude_basis": "ellipsoidal",
    })


def _build(path, frame):
    return FlightIndex.build(
        path, [frame], sources=[],
        coverage={
            "bounds": [-180.0, -90.0, 180.0, 90.0],
            "time_range_s": [EPOCH, EPOCH + 100.0],
            "all_aircraft": True,
            "source_note": "Independent analytic geometry fixture",
        },
    )


def test_partial_null_preserves_other_measured_velocity_components(tmp_path):
    anchor = np.array(TO_ECEF.transform(-100.0, 40.0, 1000.0))
    east, _, _ = _basis(40.0, -100.0)
    relative_time = np.array([0.0, 5.0, 10.0])
    # Exact constant Cartesian acceleration: x(t) = 10*t**2, v(t) = 20*t.
    # In particular, the measured zero at the first endpoint must survive.
    xyz = anchor + (10.0 * relative_time**2)[:, None] * east
    velocity = (20.0 * relative_time)[:, None] * east
    frame = _frame(xyz, velocity, EPOCH + relative_time, "accelerating")
    frame.loc[1, "up_mps"] = np.nan
    index = _build(tmp_path / "partial-null.sqlite", frame)

    tracks = list(index.query([-101.0, 39.0, -99.0, 41.0], [EPOCH, EPOCH + 10.0]))

    assert len(tracks) == 1
    assert_allclose(tracks[0].time, EPOCH + relative_time, rtol=0, atol=0)
    assert_allclose(
        tracks[0].speed_vector(EPOCH + relative_time), velocity, rtol=0, atol=1e-6,
    )


def test_query_contains_continuous_curve_outside_sampled_coordinate_box(tmp_path):
    anchor = np.array(TO_ECEF.transform(-100.0, 40.0, 1000.0))
    east, north, _ = _basis(40.0, -100.0)
    angles = np.deg2rad([-45.0, 45.0, 135.0])
    times = EPOCH + np.array([0.0, 20.0, 40.0])
    radius_m, omega = 1000.0, np.pi / 40.0
    xyz = anchor + radius_m * (
        np.cos(angles)[:, None] * east + np.sin(angles)[:, None] * north
    )
    velocity = radius_m * omega * (
        -np.sin(angles)[:, None] * east + np.cos(angles)[:, None] * north
    )
    frame = _frame(xyz, velocity, times, "curving")
    index = _build(tmp_path / "curved.sqlite", frame)

    # Cubic Hermite basis at u=1/2: H00=H01=1/2, H10=1/8, H11=-1/8.
    expected_position = (xyz[0] + xyz[1]) / 2 + (20.0 / 8) * (velocity[0] - velocity[1])
    lon, lat, _ = FROM_ECEF.transform(*expected_position)
    query_bounds = [lon - 0.00002, lat - 0.00002, lon + 0.00002, lat + 0.00002]
    assert query_bounds[0] > frame.lon.max()  # disjoint from the sampled box
    broad = list(index.query([-101.0, 39.0, -99.0, 41.0], [EPOCH, EPOCH + 40.0]))
    assert len(broad) == 1
    assert_allclose(broad[0].position(EPOCH + 10.0), expected_position, rtol=0, atol=1e-6)

    tracks = list(index.query(query_bounds, [EPOCH + 9.0, EPOCH + 11.0]))

    assert len(tracks) == 1
    assert tracks[0].id == broad[0].id
    assert_allclose(tracks[0].time, times, rtol=0, atol=0)  # never clip to query
    assert_allclose(tracks[0].position(EPOCH + 10.0), expected_position, rtol=0, atol=1e-6)
