"""Exact propagation reuse with actual recorded ridges and historical tracks."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import (_cache_ridge_fits, _ridge_fit_cache,
                                   batch_acoustic_trials, prepare_events)


def test_real_acoustic_batches_reuse_exact_inputs_and_preserve_fallback(monkeypatch):
    fixture_path = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not fixture_path:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real CPA diagnostic")
    fixture = json.loads(Path(fixture_path).read_text())
    events, measurements = prepare_events(fixture["events"])
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = fixture["point"]
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    for event, measurement in zip(events, measurements):
        for row in pd.DataFrame(fixture["cpa_rows"]).itertuples():
            if row.flight_id not in tracks:
                continue
            track = tracks[row.flight_id]
            starts = row.receive_time - event["cpa_receive_s"] + np.linspace(-5, 5, 21)
            baseline = batch_acoustic_trials([track], [measurement], observer, starts)[0]
            if baseline is not None and all(np.all(np.isfinite(part)) for part in baseline):
                break
        else:
            continue
        break
    else:
        pytest.fail("No supported real flight/event pair in the fixture")
    calls = 0
    original = track.acoustic
    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(track, "acoustic", counted)

    @_cache_ridge_fits
    def cached():
        first = batch_acoustic_trials([track], [measurement], observer, starts)[0]
        first[0][0, 0] = -1  # Cache entries must not share mutable results.
        again = batch_acoustic_trials([track], [measurement], observer, starts)[0]
        assert all(np.array_equal(a, b) for a, b in zip(again, baseline))
        assert calls == 1
        shifted = starts.copy()
        shifted[0] = np.nextafter(shifted[0], np.inf)
        batch_acoustic_trials([track], [measurement], observer, shifted)
        assert calls == 2
        assert batch_acoustic_trials([track], [measurement], observer, starts, max_samples=1) == [None]
    cached()

    @_cache_ridge_fits
    def without_capacity():
        _ridge_fit_cache.get().acoustic_limit = 0
        return [batch_acoustic_trials([track], [measurement], observer, starts)[0] for _ in range(2)]
    before = calls
    uncached = without_capacity()
    assert calls == before + 2
    assert all(all(np.array_equal(a, b) for a, b in zip(value, baseline)) for value in uncached)

    @_cache_ridge_fits
    def evicted():
        cache = _ridge_fit_cache.get()
        batch_acoustic_trials([track], [measurement], observer, starts)
        cache.acoustic_limit = cache.acoustic_bytes
        shifted = starts.copy()
        shifted[0] = np.nextafter(shifted[0], np.inf)
        batch_acoustic_trials([track], [measurement], observer, shifted)
        batch_acoustic_trials([track], [measurement], observer, starts)
        assert len(cache.acoustic_entries) == 1 and cache.acoustic_bytes <= cache.acoustic_limit
    before = calls
    evicted()
    assert calls == before + 3
