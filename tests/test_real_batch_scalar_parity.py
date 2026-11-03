"""Every fitted clock must match the scalar model on actual recorded inputs."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist.batch_ridge import first_event_fits
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import (_fit_ridge_uncached, _frequency_scale,
                                  batch_acoustic_trials, prepare_events)
from dopplergeist.search import filter_association_event


@pytest.fixture(scope="module")
def recorded():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to an actual recorded-data diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    identifiers = sorted({row["flight_id"] for row in fixture["cpa_rows"]})
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(identifiers)}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    return fixture, events, measurements, tracks, observer


def assert_all_clocks_equal(measurement, event, factors, emissions):
    fitted = first_event_fits(measurement, event, factors, emissions)
    if fitted is None:
        return 0
    sigma = _frequency_scale(event)
    fraction = event.get("quality", {}).get("source_drift_fraction", 0.02)
    assert len(fitted) == len(factors)
    for clock, (actual, factor, emitted) in enumerate(zip(fitted, factors, emissions)):
        expected = _fit_ridge_uncached(None, None, measurement, 0.0,
            event["f0_range_hz"], 343.0, sigma, fraction,
            acoustic_result=(factor, emitted))
        assert actual == expected, f"Batch/scalar mismatch at clock {clock}: {actual!r} != {expected!r}"
    return len(fitted)


def test_every_fitted_clock_matches_scalar_for_recorded_pairs(recorded):
    fixture, events, measurements, tracks, observer = recorded
    table = pd.DataFrame(fixture["cpa_rows"])
    checked = batches = 0
    for event, measurement in zip(events, measurements):
        # Cover every recorded CPA eligible for this event, not representative
        # rows or a selection based on favorable fit scores.
        for row in filter_association_event(table, event, 5.0, None, 5.0).itertuples():
            track = tracks.get(row.flight_id)
            if track is None:
                continue
            starts = row.receive_time - event["cpa_receive_s"] + np.linspace(-5.0, 5.0, 21)
            batch = batch_acoustic_trials([track], [measurement], observer, starts)[0]
            if batch is None:
                continue
            factors, emissions = batch
            complete = np.all(np.isfinite(factors) & np.isfinite(emissions) & (factors > 0), axis=1)
            if not np.all(complete):
                assert first_event_fits(measurement, event, factors, emissions) is None
            if not np.any(complete):
                continue
            count = assert_all_clocks_equal(measurement, event, factors[complete], emissions[complete])
            checked += count
            batches += count > 0
    assert checked > 100 and batches > 1


def test_recorded_python_power_roundoff_case(recorded):
    _, events, measurements, tracks, observer = recorded
    event_index = next((i for i, event in enumerate(events)
                        if event.get("event_id") == "event-0006"), None)
    track = tracks.get("ab50b9:11")
    if event_index is None or track is None:
        pytest.skip("The supplied recording is not the archived reference roundoff case")
    event, measurement = events[event_index], measurements[event_index]
    # This clock came from an actual reference-input search. Array squaring
    # changed its scalar prior by one ULP and then changed two association rows.
    # Put it outside the old first/middle/last representative checks.
    starts = 1788898677.1507423 + np.array([-1.0, 0.0, 1.0, 2.0, 3.0])
    batch = batch_acoustic_trials([track], [measurement], observer, starts)[0]
    assert batch is not None
    assert assert_all_clocks_equal(measurement, event, *batch) == len(starts)


def test_noncanonical_numeric_parameters_keep_scalar_fallback(recorded):
    fixture, events, measurements, tracks, observer = recorded
    for event, measurement in zip(events, measurements):
        for row in fixture["cpa_rows"]:
            track = tracks.get(row["flight_id"])
            if track is None:
                continue
            starts = row["receive_time"] - event["cpa_receive_s"] + np.linspace(-5.0, 5.0, 5)
            batch = batch_acoustic_trials([track], [measurement], observer, starts)[0]
            if batch is None or first_event_fits(measurement, event, *batch) is None:
                continue
            quality = event.get("quality", {})
            for key, value in (("frequency_loss_scale_hz", np.float32(_frequency_scale(event))),
                               ("source_drift_fraction", np.float32(quality.get("source_drift_fraction", 0.02)))):
                changed = dict(event, quality=dict(quality, **{key: value}))
                assert first_event_fits(measurement, changed, *batch) is None
            changed = dict(event, f0_range_hz=[np.float64(value) for value in event["f0_range_hz"]])
            assert first_event_fits(measurement, changed, *batch) is None
            # Fault-inject a finite but overflowing uncertainty on the same
            # observed arrays; Python powers must retain the scalar fallback.
            changed = dict(event, quality=dict(quality, frequency_loss_scale_hz=1e200))
            assert first_event_fits(measurement, changed, *batch) is None
            return
    pytest.fail("No supported real batch available for numeric-type fallback checks")
