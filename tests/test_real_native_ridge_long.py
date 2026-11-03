"""Check the native reduction boundary on a long recorded Doppler ridge."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist import matching
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.search import filter_association_event


def test_recorded_ridge_crosses_native_pairwise_reduction_boundary(monkeypatch):
    native = matching._native_fit_irls
    if native is None:
        pytest.skip("optional native ridge extension is not installed")
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real point120 diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = matching.prepare_events(fixture["events"])
    index = max(range(len(measurements)), key=lambda i: len(measurements[i][1]))
    event, measurement = events[index], measurements[index]
    if len(measurement[1]) < 141:
        pytest.skip("this recorded fixture has no ridge crossing the 128-sample boundary")
    rows = filter_association_event(pd.DataFrame(fixture["cpa_rows"]), event, 5., None, 5.)
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        list(dict.fromkeys(rows.flight_id)), max_tracks=2000, max_samples=2000000)}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    checked = passages = 0
    native_successes = 0

    def counted(*arguments):
        nonlocal native_successes
        result = native(*arguments)
        native_successes += result is not None and all(np.isfinite(value) for value in result)
        return result

    monkeypatch.setattr(matching, "_native_fit_irls", counted)
    for row in rows.itertuples():
        # These are shared-clock hypotheses for actual measured observations;
        # no recording or trajectory samples are generated.
        starts = row.receive_time - event["cpa_receive_s"] + np.array([-2.5, 0., 2.5])
        batch = matching.batch_acoustic_trials(
            [tracks[row.flight_id]], [measurement], observer, starts)[0]
        if batch is None or not all(np.all(np.isfinite(array)) for array in batch):
            continue
        for count in (127, 128, 129, 136, 141):
            selected = (matching.RidgeTimes(measurement[0].time[:count]),
                        measurement[1][:count], measurement[2][:count], {})
            for factor, emitted in zip(batch[0][:, :count], batch[1][:, :count]):
                for sigma in (0.5, 1.0, 3.7, 18.001973492902533):
                    for fraction in (0.0, 0.02, 0.1):
                        arguments = (None, None, selected, 0., event["f0_range_hz"],
                                     343., sigma, fraction)
                        with monkeypatch.context() as patch:
                            patch.setattr(matching, "_native_fit_irls", None)
                            expected = matching._fit_ridge_uncached(
                                *arguments, acoustic_result=(factor, emitted))
                        actual = matching._fit_ridge_uncached(
                            *arguments, acoustic_result=(factor, emitted))
                        assert expected["support_fraction"] == 1. and np.isfinite(expected["score"])
                        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
                        checked += 1
        passages += 1
        if passages == 3:
            break
    assert passages == 3 and checked == native_successes == 540
