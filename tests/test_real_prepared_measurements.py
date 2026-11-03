"""Prepared-input cache invariants on measured ridges and observed trajectories."""
import copy
import json
import os
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import matching
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef


@pytest.fixture
def recorded_fit_inputs():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to an actual recorded-data diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = matching.prepare_events(fixture["events"])
    identities = sorted({row["flight_id"] for row in fixture["cpa_rows"]})
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(identities)}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    # Prefer a longer recorded ridge; selection never uses fit score or truth.
    for index in sorted(range(len(events)), key=lambda i: -len(measurements[i][1])):
        event, measurement = events[index], measurements[index]
        for row in fixture["cpa_rows"]:
            track = tracks.get(row["flight_id"])
            if track is None:
                continue
            start = row["receive_time"] - event["cpa_receive_s"]
            times, ridge, weight = matching._ridge_fit_inputs(measurement, 1.0, 0.02)
            measured = np.isfinite(times) & np.isfinite(ridge) & (weight > 0)
            try:
                factors, emissions, _ = track.acoustic(start + times[measured], observer)
            except AcousticSupportError:
                continue
            if np.all(np.isfinite(factors)) and np.all(np.isfinite(emissions)):
                return track, observer, measurement, start, event["f0_range_hz"], (factors, emissions)
    pytest.fail("No physically supported real ridge/trajectory candidate in the fixture")


def same(actual, expected):
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_real_prepared_cache_mutations_and_return_independence(recorded_fit_inputs):
    track, observer, measurement, start, bounds, acoustics = recorded_fit_inputs

    @matching._cache_ridge_fits
    def check():
        def compare(measured, sigma=1.0):
            args = (track, observer, measured, start, bounds, 343.0, sigma, 0.02)
            expected = matching._fit_ridge_uncached(*args, acoustic_result=acoustics)
            actual = matching.fit_ridge(*args, acoustic_result=acoustics)
            same(actual, expected)
            actual["f0_hz"] = -123.0
            same(matching.fit_ridge(*args, acoustic_result=acoustics), expected)

        compare(measurement)
        # Fault-inject changes into copies of observed arrays. These are cache
        # controls, not new field recordings or location-accuracy observations.
        for part in (0, 1, 2):
            changed = copy.deepcopy(measurement)
            array = changed[0].time if part == 0 else changed[part]
            array[0] = np.nextafter(array[0], np.inf)
            compare(changed)
        compare(measurement, np.float32(0.3))
        compare(measurement, np.float64(0.3))
        cache = matching._ridge_fit_cache.get()
        assert len(cache.measurement_entries) == 6
        assert cache.measurement_bytes <= cache.measurement_limit
    check()


def test_real_prepared_cache_capacity_and_validation(recorded_fit_inputs):
    track, observer, measurement, start, bounds, acoustics = recorded_fit_inputs

    @matching._cache_ridge_fits
    def check():
        cache = matching._ridge_fit_cache.get()
        cache.max_entries = 1
        for sigma in (1.0, 1.5, 1.0):
            args = (track, observer, measurement, start, bounds, 343.0, sigma, 0.02)
            same(matching.fit_ridge(*args, acoustic_result=acoustics),
                 matching._fit_ridge_uncached(*args, acoustic_result=acoustics))
            assert len(cache.measurement_entries) == 1
            assert cache.measurement_bytes <= cache.measurement_limit
        cache.measurement_entries.clear()
        cache.measurement_bytes = 0
        cache.measurement_limit = 0
        args = (track, observer, measurement, start, bounds, 343.0, 2.0, 0.02)
        same(matching.fit_ridge(*args, acoustic_result=acoustics),
             matching._fit_ridge_uncached(*args, acoustic_result=acoustics))
        assert not cache.measurement_entries and cache.measurement_bytes == 0
        with pytest.raises(ValueError, match="drift fraction"):
            matching.fit_ridge(track, observer, measurement, start, bounds,
                               drift_fraction=0.2, acoustic_result=acoustics)
        invalid = copy.deepcopy(measurement)
        invalid[2][0] = -1.0
        with pytest.raises(ValueError, match="weights"):
            matching.fit_ridge(track, observer, invalid, start, bounds, acoustic_result=acoustics)
    check()
