"""Propagation reuse checks using recorded ridges and observed aircraft motion.

The bundled motion observations exercise support failures. The ridge checks use
DOPPLERGEIST_REAL_CPA_FIXTURE, following the existing real-data test contract.
No audio, aircraft observations or ridge measurements are generated here.
"""
from dataclasses import replace
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.matching import prepare_events
from dopplergeist.tracks import _segment_velocity


@pytest.fixture
def observed_motion():
    path = Path(__file__).resolve().parents[1] / (
        "research/trajectory-motion/frozen/canonical-observations.json")
    table = pd.DataFrame(json.loads(path.read_text()))
    tracks = []
    for identifier, group in table.groupby("flight_id", sort=False):
        group = group.sort_values("time_s")
        velocity, _ = _segment_velocity(group)
        tracks.append(Track(identifier, group.time_s.to_numpy(), group.lat.to_numpy(),
                            group.lon.to_numpy(), group.alt_m.to_numpy(),
                            str(group.typecode.iloc[0]), velocity))
    assert len(tracks) == 4
    return tracks


@pytest.fixture(scope="module")
def recorded_pair():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a real CPA diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    for event, measurement in zip(events, measurements):
        spec, ridge, weight, _ = measurement
        measured = np.isfinite(spec.time) & np.isfinite(ridge) & (weight > 0)
        for row in fixture["cpa_rows"]:
            track = tracks.get(row["flight_id"])
            if track is None:
                continue
            receive = row["receive_time"] - event["cpa_receive_s"] + spec.time[measured]
            try:
                track.validate_motion_support()
                values = track.acoustic(receive, observer)
            except AcousticSupportError:
                continue
            if len(receive) >= 10 and all(np.all(np.isfinite(part)) for part in values):
                return track, observer, receive
    pytest.fail("The real fixture contains no fully supported observed flight/ridge pair")


def assert_same_arrays(left, right):
    for before, after in zip(left, right):
        np.testing.assert_array_equal(before, after)


def support_error(track, receive, observer, c):
    with pytest.raises(AcousticSupportError) as caught:
        track.acoustic(receive, observer, c)
    error = caught.value
    return error.reason, error.emission_intervals_s, error.receive_intervals_s


def test_real_ridge_propagation_reuse_preserves_physical_solution(recorded_pair):
    original, observer, receive = recorded_pair
    track = replace(original)
    first = track.acoustic(receive, observer)
    assert_same_arrays(first, track.acoustic(receive, observer))
    factor, emitted, distance = first
    displacement = track.position(emitted) - observer
    expected_distance = np.linalg.norm(displacement, axis=-1)
    radial = np.sum(displacement * track.speed_vector(emitted), axis=-1) / expected_distance
    np.testing.assert_array_equal(distance, expected_distance)
    np.testing.assert_array_equal(factor, 343. / (343. + radial))

    # A bracketed scalar solve checks emission time independently of Newton's
    # updates and the final-iteration reuse. Use relative time for root finding.
    for index in (0, len(receive) // 2, len(receive) - 1):
        def arrival_residual(relative):
            when = track.origin + relative
            return when - receive[index] + np.linalg.norm(track.position(when) - observer) / 343.
        root = brentq(arrival_residual, 0., float(track.time[-1] - track.origin),
                      xtol=1e-10, rtol=1e-14)
        assert abs(track.origin + root - emitted[index]) <= 4 * abs(np.spacing(receive[index]))


def test_real_ridge_arrays_and_query_mutations_do_not_poison_reuse(recorded_pair):
    original, observer, receive = recorded_pair
    track = replace(original)
    expected = track.acoustic(receive, observer)
    returned = track.acoustic(receive, observer)
    for part in returned:
        part[:] = np.nan
    assert_same_arrays(expected, track.acoustic(receive, observer))

    # Fault-inject changes into the existing real query arrays, then restore
    # them. An array object's identity must not substitute for its current data.
    changed_time, changed_observer = receive.copy(), observer.copy()
    changed_time[0] = np.nextafter(changed_time[0], np.inf)
    changed_observer[0] = np.nextafter(changed_observer[0], np.inf)
    assert_same_arrays(track.acoustic(changed_time, changed_observer),
                       replace(original).acoustic(changed_time, changed_observer))
    changed_time[:] = receive
    changed_observer[:] = observer
    assert_same_arrays(expected, track.acoustic(changed_time, changed_observer))
    for c in (330., 355., 343.):
        assert_same_arrays(track.acoustic(receive, observer, c),
                           replace(original).acoustic(receive, observer, c))


def test_observed_motion_interval_results_are_mutation_isolated(observed_motion):
    for track in observed_motion:
        first = track._unsupported_motion_intervals(343.)
        expected = first.copy()
        assert len(expected) > 1
        first[:] = 0
        second = track._unsupported_motion_intervals(343.)
        np.testing.assert_array_equal(second, expected)
        second[:] = 0
        np.testing.assert_array_equal(track._unsupported_motion_intervals(343.), expected)
        with pytest.raises(AcousticSupportError) as caught:
            track.validate_motion_support()
        expected_intervals = [[float(track.time[i]), float(track.time[i + 1])] for i in expected]
        assert caught.value.emission_intervals_s == expected_intervals
        caught.value.emission_intervals_s[0][0] = -1.
        with pytest.raises(AcousticSupportError) as again:
            track.validate_motion_support()
        assert again.value.emission_intervals_s == expected_intervals


def test_observed_motion_cache_respects_sound_speed_and_failure_payloads(observed_motion):
    changed = False
    for track in observed_motion:
        midpoint = len(track.time) // 2
        # A ground receiver below an observed position is a model query, not
        # a claim that a recording was made at that position.
        observer = ecef(track.lat[midpoint], track.lon[midpoint], 0.)
        previous = None
        for c in (330., 343., 355., 343.):
            indices = track._unsupported_motion_intervals(c)
            np.testing.assert_array_equal(indices, replace(track)._unsupported_motion_intervals(c))
            if previous is not None and not np.array_equal(indices, previous):
                changed = True
            previous = indices
            assert support_error(track, track.time, observer, c) == support_error(
                replace(track), track.time, observer, c)
    assert changed, "Observed tracks must exercise a changed sound-speed support boundary"


def test_observed_motion_cache_preserves_sound_speed_scalar_precision(observed_motion):
    track = observed_motion[0]
    track._unsupported_motion_intervals(330.)
    peak = float(track._speed_peak[0])
    assert np.isfinite(peak)
    coarse = np.float32(peak / (1-1e-10))
    # Query opposite sides of this actual observed spline's speed maximum.
    # NumPy can compare the differently typed thresholds equal after rounding,
    # although the float64 speed array distinguishes their original values.
    direction = np.inf if float(coarse * (1-1e-10)) < peak else -np.inf
    precise = float(np.nextafter(peak, direction)) / (1-1e-10)
    expected_precise = replace(track)._unsupported_motion_intervals(precise)
    expected_coarse = replace(track)._unsupported_motion_intervals(coarse)
    assert not np.array_equal(expected_precise, expected_coarse)
    for first, second in ((precise, coarse), (coarse, precise),
                          (np.float64(precise), coarse), (coarse, np.float64(precise))):
        cached = replace(track)
        cached._unsupported_motion_intervals(first)
        np.testing.assert_array_equal(cached._unsupported_motion_intervals(second),
                                      replace(track)._unsupported_motion_intervals(second))
