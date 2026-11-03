"""Native propagation parity through real ridge fits and candidate scoring."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist import native_acoustic
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import (_cache_ridge_fits, _fit_ridge_uncached, _frequency_scale,
                                   association_candidates, prepare_events)
from dopplergeist.search import filter_association_event, score_candidate


@pytest.fixture(scope="module")
def recorded():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a real recorded-input diagnostic")
    if native_acoustic._native is None:
        pytest.skip("optional native acoustic extension is not built")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    table = pd.DataFrame(fixture["cpa_rows"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = SimpleNamespace(**{"x": 0., "y": 0., **fixture["point"]})
    return fixture, events, measurements, table, tracks, point


def _fit_outcome(*args):
    try:
        return _fit_ridge_uncached(*args)
    except AcousticSupportError as error:
        return {"acoustic_error": vars(error)}


def test_recorded_scalar_fits_and_batch_geometry_are_bit_exact(recorded, monkeypatch):
    _, events, measurements, table, tracks, point = recorded
    observer = ecef(point.lat, point.lon, point.elev_m)
    cases = []
    for event, measurement in zip(events, measurements):
        rows = filter_association_event(table, event, 5., None, 5.)
        for row in list(rows.itertuples())[:3]:
            if row.flight_id not in tracks:
                continue
            for offset in (-5., 0., 5.):
                cases.append((tracks[row.flight_id], observer, measurement,
                    row.receive_time-event["cpa_receive_s"]+offset, event["f0_range_hz"],
                    343., _frequency_scale(event), event.get("quality", {}).get("source_drift_fraction", .02)))
    assert cases
    extension = native_acoustic._native
    before = extension.successful_calls()
    with monkeypatch.context() as context:
        context.setattr(native_acoustic, "_native", None)
        expected = [_fit_outcome(*args) for args in cases]
    actual = [_fit_outcome(*args) for args in cases]
    assert extension.successful_calls() > before
    assert json.dumps(actual, sort_keys=True, allow_nan=True) == json.dumps(expected, sort_keys=True, allow_nan=True)
    assert sum(result.get("support_fraction") == 1. for result in actual) > 0


def test_recorded_complete_candidate_scoring_is_exact(recorded, monkeypatch):
    fixture, events, measurements, table, tracks, point = recorded
    options = {}
    if "recording_start_window_s" in fixture:
        from dopplergeist.tiled_search import _association_clock_window
        center, tolerance = _association_clock_window(
            fixture["recording_start_window_s"], fixture.get("scoring", {}).get("time_sweep_s", 5.))
        options = {"time_origin": center, "time_tolerance_s": tolerance}
    candidates, _ = association_candidates(table, events, max_candidates=20000, **options)
    assert candidates
    selected = sorted({0, len(candidates)//5, 2*len(candidates)//5,
                       3*len(candidates)//5, 4*len(candidates)//5, len(candidates)-1})

    @_cache_ridge_fits
    def run():
        return [score_candidate(candidates[i], point, tracks, events, measurements,
                                mode="robust_ridge") for i in selected]

    extension = native_acoustic._native
    before = extension.successful_calls()
    with monkeypatch.context() as context:
        context.setattr(native_acoustic, "_native", None)
        expected = run()
    actual = run()
    assert extension.successful_calls() > before
    assert json.dumps(actual, sort_keys=True, allow_nan=True) == json.dumps(expected, sort_keys=True, allow_nan=True)
