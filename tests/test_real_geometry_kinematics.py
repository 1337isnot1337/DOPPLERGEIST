"""Compare optimized geometry with the former solver on recorded inputs only."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import dopplergeist.geometry as geometry
from dopplergeist.data_access import FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.search import filter_association_event


@pytest.fixture(scope="module")
def recorded_geometry():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a recorded-input diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    table = pd.DataFrame(fixture["cpa_rows"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = fixture["point"]
    observer = geometry.ecef(point["lat"], point["lon"], point["elev_m"])
    calls = []
    for event, measurement in zip(events, measurements):
        times, ridge, weights = measurement[0].time, measurement[1], measurement[2]
        measured = np.isfinite(times) & np.isfinite(ridge) & (weights > 0)
        rows = filter_association_event(table, event, 5., None, 5.)
        for row in list(rows.itertuples())[:3]:
            if row.flight_id in tracks:
                starts = row.receive_time - event["cpa_receive_s"] + np.linspace(-5., 5., 5)
                calls.append((tracks[row.flight_id], starts[:, None] + times[measured]))
    return observer, calls, list(tracks.values())


def _original_acoustic(track, receive_time, observer, c=343.):
    """The pre-optimization Newton loop, including its unconditional final fit.

    This deliberately retains separate position/velocity evaluations as the
    regression oracle. It uses the same recorded splines and support rules.
    """
    t = np.asarray(receive_time, dtype=float)
    start, end = track.time[[0, -1]]
    arrival_start = start + np.linalg.norm(track.xyz[0] - observer) / c
    arrival_end = end + np.linalg.norm(track.xyz[-1] - observer) / c
    supported = (t >= arrival_start) & (t <= arrival_end)
    initial = track.position(np.clip(t, start, end))
    tau = np.clip(t - np.linalg.norm(initial - observer, axis=-1) / c, start, end)
    for _ in range(10):
        delta = track.position(tau) - observer
        distance = np.linalg.norm(delta, axis=-1)
        radial = np.sum(delta * track.speed_vector(tau), axis=-1) / distance
        derivative = 1 + radial / c
        if np.any(derivative <= 0):
            raise geometry.AcousticSupportError(track.id, "non_monotone_arrival")
        correction = (tau - t + distance / c) / derivative
        updated = np.clip(tau - correction, start, end)
        unchanged = np.array_equal(tau, updated)
        tau = updated
        if np.max(np.abs(correction)) < geometry._EMISSION_ITERATION_TOLERANCE_S or unchanged:
            break
    delta = track.position(tau) - observer
    distance = np.linalg.norm(delta, axis=-1)
    radial = np.sum(delta * track.speed_vector(tau), axis=-1) / distance
    factor = c / (c + radial)
    track._check_motion_support(t, observer, c)
    arrival_derivative = 1 + radial / c
    if np.any(arrival_derivative <= 0):
        raise geometry.AcousticSupportError(track.id, "non_monotone_arrival")
    remaining = (tau - t + distance / c) / arrival_derivative
    tolerance = np.maximum(1e-7, 4 * np.abs(np.spacing(t)))
    if np.any(supported & (~np.isfinite(remaining) | (np.abs(remaining) > tolerance))):
        raise geometry.AcousticSupportError(track.id, "emission_solver_not_converged")
    return tuple(np.where(supported, value, np.nan) for value in (factor, tau, distance))


def _outcome(function, track, query, observer):
    try:
        return function(track, query, observer)
    except geometry.AcousticSupportError as error:
        return {"track_id": error.track_id, "reason": error.reason,
                "emission_intervals_s": error.emission_intervals_s,
                "receive_intervals_s": error.receive_intervals_s}


def _assert_same(track, query, observer):
    expected = _outcome(_original_acoustic, track, query, observer)
    actual = _outcome(geometry.Track.acoustic, track, query, observer)
    if isinstance(expected, dict):
        assert actual == expected
        return 0
    assert not isinstance(actual, dict)
    for old, new in zip(expected, actual):
        assert old.shape == new.shape
        assert old.tobytes() == new.tobytes()
    return int(np.isfinite(actual[0]).sum())


def test_recorded_packed_spline_matches_native_and_cpa_grid_queries(recorded_geometry):
    _, _, tracks = recorded_geometry
    geometry._packed_kinematics.cache_clear()
    checked = 0
    for track in tracks[:12]:
        # The same interpolation grid as cpa_table, plus archived sample times.
        query = np.unique(np.r_[track.time,
            np.arange(track.time[0], track.time[-1], 2.), track.time[-1]])
        position, velocity = track._position_velocity(query)
        assert position.tobytes() == track.position(query).tobytes()
        assert velocity.tobytes() == track.speed_vector(query).tobytes()
        checked += len(query)
    assert checked > 100
    assert 0 < geometry._packed_kinematics.cache_info().currsize <= 8


def test_recorded_solver_matches_original_with_bounded_spline_cache(recorded_geometry):
    observer, calls, _ = recorded_geometry
    geometry._packed_kinematics.cache_clear()
    checked = sum(_assert_same(track, query, observer) for track, query in calls)
    assert checked > 100
    assert 0 < geometry._packed_kinematics.cache_info().currsize <= 8


def test_recorded_solver_fallback_and_native_support_errors(recorded_geometry, monkeypatch):
    observer, calls, tracks = recorded_geometry
    monkeypatch.setattr(geometry, "_PACKED_KINEMATICS_MAX_INTERVALS", 0)
    before = geometry._packed_kinematics.cache_info()
    checked = sum(_assert_same(track, query, observer) for track, query in calls[:5])
    assert checked > 0
    assert geometry._packed_kinematics.cache_info() == before

    # Query arrival envelopes of unsupported intervals in actual archived
    # tracks. These are solver queries, not invented aircraft observations.
    failures = 0
    for track in tracks:
        for index in track._unsupported_motion_intervals(343.)[:2]:
            emitted = (track.time[index] + track.time[index + 1]) / 2
            receive = emitted + np.linalg.norm(track.position(emitted) - observer) / 343.
            expected = _outcome(_original_acoustic, track, receive, observer)
            actual = _outcome(geometry.Track.acoustic, track, receive, observer)
            assert isinstance(expected, dict)
            assert actual == expected
            failures += 1
        if failures >= 4:
            break
    assert failures > 0
