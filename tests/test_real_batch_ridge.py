"""Optional batched-fit parity checks using observed audio and aircraft tracks."""
import json
import os
from pathlib import Path
import random
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist.batch_ridge import first_event_fits
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import (_cache_ridge_fits, _fit_ridge_uncached, _frequency_scale,
                                   association_candidates, batch_acoustic_trials, prepare_events)
from dopplergeist.search import filter_association_event, score_candidate


@pytest.fixture
def recorded():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real reference diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    table = pd.DataFrame(fixture["cpa_rows"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    return fixture, events, measurements, table, tracks


def test_real_batched_event_fits_equal_scalar_diagnostics(recorded):
    fixture, events, measurements, table, tracks = recorded
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    checked = unsupported = 0
    for event, measurement in zip(events, measurements):
        for row in list(filter_association_event(table, event, 5., None, 5.).itertuples())[:5]:
            if row.flight_id not in tracks:
                continue
            starts = row.receive_time - event["cpa_receive_s"] + np.linspace(-5, 5, 21)
            batch = batch_acoustic_trials([tracks[row.flight_id]], [measurement], observer, starts)[0]
            if batch is None:
                unsupported += len(starts)
                continue
            factors, emissions = batch
            complete = np.all(np.isfinite(factors) & np.isfinite(emissions) & (factors > 0), axis=1)
            if not np.all(complete):
                assert first_event_fits(measurement, event, factors, emissions) is None
                unsupported += int((~complete).sum())
            if not np.any(complete):
                continue
            factors, emissions = factors[complete], emissions[complete]
            results = first_event_fits(measurement, event, factors, emissions)
            if results is None:
                continue
            fraction = event.get("quality", {}).get("source_drift_fraction", .02)
            sigma = _frequency_scale(event)
            for result, factor, emitted in zip(results, factors, emissions):
                scalar = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
                                             343., sigma, fraction, acoustic_result=(factor, emitted))
                assert json.dumps(result, sort_keys=True) == json.dumps(scalar, sort_keys=True)
                checked += 1
            zero_drift = dict(event, quality=dict(event.get("quality", {}), source_drift_fraction=0.))
            assert first_event_fits(measurement, zero_drift, factors, emissions) is None
    assert checked > 100


def test_real_association_results_match_scalar_fits(recorded, monkeypatch):
    import dopplergeist.batch_ridge as batch_ridge

    fixture, events, measurements, table, tracks = recorded
    candidates, _ = association_candidates(table, events, max_candidates=20000)
    selected = sorted(random.Random(20261103).sample(range(len(candidates)), min(100, len(candidates))))
    point = SimpleNamespace(**fixture["point"], x=0., y=0.)

    @_cache_ridge_fits
    def run():
        return [score_candidate(candidates[i], point, tracks, events, measurements,
                                mode="robust_ridge", score_floor=0.) for i in selected]

    with monkeypatch.context() as patch:
        patch.setattr(batch_ridge, "first_event_fits", lambda *args: None)
        scalar = run()
    calls = 0
    original = batch_ridge.first_event_fits

    def counted(*args):
        nonlocal calls
        result = original(*args)
        calls += result is not None
        return result

    with monkeypatch.context() as patch:
        patch.setattr(batch_ridge, "first_event_fits", counted)
        batched = run()
    assert calls > 0
    assert json.dumps(scalar, sort_keys=True, allow_nan=True) == json.dumps(batched, sort_keys=True, allow_nan=True)
