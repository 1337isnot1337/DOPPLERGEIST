"""Optional feasibility regression against recorded ridges and ADS-B tracks."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist.acoustic_screen import ridge_trial_rejections
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import (_fit_ridge_uncached, _frequency_scale,
                                   batch_acoustic_trials, prepare_events)
from dopplergeist.search import filter_association_event


def test_real_ridge_rejections_have_supported_failing_witnesses():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real reference diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    table = pd.DataFrame(fixture["cpa_rows"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        sorted(set(table.flight_id)), max_tracks=2000, max_samples=2000000)}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    witnessed = tested = unsupported = 0
    for event, measurement in zip(events, measurements):
        sigma = _frequency_scale(event)
        fraction = event.get("quality", {}).get("source_drift_fraction", .02)
        rows = filter_association_event(table, event, 5., None, 5.)
        for row in rows.itertuples():
            track = tracks.get(row.flight_id)
            if track is None:
                unsupported += 3
                continue
            # These are candidate shared clocks for the same recorded event;
            # this diagnostic does not supply a location to the automatic run.
            starts = row.receive_time-event["cpa_receive_s"] + np.array([-2.5, 0., 2.5])
            batch = batch_acoustic_trials([track], [measurement], observer, starts)[0]
            if batch is None:
                unsupported += len(starts)
                continue
            factors, emissions = batch
            rejected = ridge_trial_rejections(measurement, event, factors, emissions)
            assert rejected.shape == starts.shape
            incomplete = ~np.all(np.isfinite(factors) & np.isfinite(emissions), axis=1)
            assert not np.any(rejected & incomplete)
            tested += int((~incomplete).sum())
            unsupported += int(incomplete.sum())
            for i in np.flatnonzero(rejected):
                fit = _fit_ridge_uncached(track, observer, measurement, starts[i],
                                          event["f0_range_hz"], 343., sigma, fraction,
                                          acoustic_result=(factors[i], emissions[i]))
                assert fit["support_fraction"] == 1.
                assert np.isfinite(fit["score"])
                assert -fit["score"] > 3*sigma
                witnessed += 1
    assert tested > 100 and witnessed > 0 and unsupported > 0
