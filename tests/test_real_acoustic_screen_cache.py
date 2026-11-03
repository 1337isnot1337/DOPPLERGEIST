"""Exact screen-cache regressions using recorded ridges and aircraft tracks."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from dopplergeist import acoustic_screen as screen
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import (_cache_ridge_fits, _frequency_scale, _ridge_fit_cache,
                                  batch_acoustic_trials, prepare_events)
from dopplergeist.search import filter_association_event


@pytest.fixture(scope="module")
def recorded_batches():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a recorded CPA diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    table = pd.DataFrame(fixture["cpa_rows"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        sorted(set(table.flight_id)), max_tracks=2000, max_samples=2000000)}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    batches = []
    for event, measurement in zip(events, measurements):
        rows = filter_association_event(table, event, 5., None, 5.)
        for row in list(rows.itertuples())[:2]:
            if row.flight_id not in tracks:
                continue
            starts = row.receive_time-event["cpa_receive_s"]+np.linspace(-5, 5, 21)
            batch = batch_acoustic_trials([tracks[row.flight_id]], [measurement], observer, starts)[0]
            if batch is not None and np.all(np.isfinite(batch)):
                batches.append((measurement, event, *batch))
    assert len(batches) > 2
    return batches


def same(actual, expected):
    if isinstance(actual, tuple):
        assert all(np.array_equal(a, b, equal_nan=True) for a, b in zip(actual, expected))
    else:
        assert np.array_equal(actual, expected)


def test_real_cached_loss_evidence_uses_current_floor(recorded_batches, monkeypatch):
    original = screen._loss_lower_bounds
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(screen, "_loss_lower_bounds", counted)
    settings = [(group, floor) for group in (1, 3, 6, 16)
                for floor in (0., group-1., group-.3, float(np.nextafter(group, -np.inf)),
                              float(group), float(group+1), float("nan"))]
    expected = [[screen.ridge_trial_rejections(*values, score_floor=floor, group_count=group)
                 for group, floor in settings] for values in recorded_batches]
    calls = 0

    @_cache_ridge_fits
    def compare():
        for values, results in zip(recorded_batches, expected):
            before = calls
            for (group, floor), result in zip(settings, results):
                actual = screen.ridge_trial_rejections(*values, score_floor=floor, group_count=group)
                same(actual, result)
                actual[0][:] = True
                actual[1][:] = -12345.  # Returned arrays cannot modify stored evidence.
            assert calls == before + 1
        cache = _ridge_fit_cache.get()
        assert 0 < cache.screen_bytes + sys.getsizeof(cache.screen_entries) <= cache.screen_limit
        assert len(cache.screen_entries) <= cache.max_entries

    compare()
    assert _ridge_fit_cache.get() is None


def test_real_screen_cache_mutation_and_eviction(recorded_batches, monkeypatch):
    base = recorded_batches[0]
    changed = []
    for index in range(5):
        values = deepcopy(base)
        array = (values[0][0].time, values[0][1], values[0][2], values[2], values[3])[index]
        array.flat[0] = np.nextafter(array.flat[0], np.inf)
        changed.append(values)
    for name in ("sigma", "fraction", "high"):
        values = deepcopy(base)
        event = values[1]
        if name == "sigma":
            event["quality"]["frequency_loss_scale_hz"] = float(np.nextafter(_frequency_scale(event), np.inf))
        elif name == "fraction":
            event["quality"]["source_drift_fraction"] = float(np.nextafter(
                event["quality"].get("source_drift_fraction", .02), np.inf))
        else:
            event["f0_range_hz"][1] = float(np.nextafter(event["f0_range_hz"][1], np.inf))
        changed.append(values)
    changed.append((*base[:2], np.asfortranarray(base[2]), np.asfortranarray(base[3])))
    settings = {"score_floor": 2.7, "group_count": 3}
    expected = [screen.ridge_trial_rejections(*values, **settings) for values in [base, *changed]]
    original = screen._loss_lower_bounds
    calls = 0

    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)

    monkeypatch.setattr(screen, "_loss_lower_bounds", counted)

    @_cache_ridge_fits
    def compare():
        cache = _ridge_fit_cache.get()
        same(screen.ridge_trial_rejections(*base, **settings), expected[0])
        same(screen.ridge_trial_rejections(*deepcopy(base), **settings), expected[0])
        assert calls == 1
        for values, result in zip(changed, expected[1:]):
            before = calls
            same(screen.ridge_trial_rejections(*values, **settings), result)
            assert calls == before+1
        cache.max_entries = 1
        for values, result in zip([base, changed[0], base], [expected[0], expected[1], expected[0]]):
            before = calls
            same(screen.ridge_trial_rejections(*values, **settings), result)
            assert calls == before+1
            assert len(cache.screen_entries) == 1
        for limit in (1, 0):
            cache.screen_limit = limit
            before = calls
            for _ in range(2):
                same(screen.ridge_trial_rejections(*base, **settings), expected[0])
            assert calls == before+2
            assert not cache.screen_entries and cache.screen_bytes == 0

    compare()
