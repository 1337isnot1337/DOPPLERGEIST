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


def test_real_candidate_scores_match_full_fits_with_screening(monkeypatch):
    import math
    import random
    from types import SimpleNamespace

    import dopplergeist.acoustic_screen as screen
    import dopplergeist.matching as matching
    from dopplergeist.search import score_candidate

    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real reference diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    candidates, _ = matching.association_candidates(pd.DataFrame(fixture["cpa_rows"]), events,
                                                     max_candidates=20000)
    chosen = sorted(random.Random(20261103).sample(range(len(candidates)), 20))
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = SimpleNamespace(**fixture["point"], x=0., y=0.)

    @matching._cache_ridge_fits
    def run():
        return [score_candidate(candidates[i], point, tracks, events, measurements, mode="robust_ridge", score_floor=0.0)
                for i in chosen]

    original = screen.ridge_trial_rejections
    with monkeypatch.context() as patch:
        patch.setattr(screen, "ridge_trial_rejections",
                      lambda measurement, event, factors, emissions: np.zeros(len(factors), dtype=bool))
        baseline = run()
    witnessed = 0

    def checked(measurement, event, factors, emissions):
        nonlocal witnessed
        rejected = original(measurement, event, factors, emissions)
        sigma = _frequency_scale(event)
        fraction = event.get("quality", {}).get("source_drift_fraction", .02)
        for i in np.flatnonzero(rejected):
            fit = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"], 343.,
                                      sigma, fraction, acoustic_result=(factors[i], emissions[i]))
            assert fit["support_fraction"] == 1. and math.isfinite(fit["score"])
            assert -fit["score"] > 3*sigma
            witnessed += 1
        return rejected

    with monkeypatch.context() as patch:
        patch.setattr(screen, "ridge_trial_rejections", checked)
        screened = run()
    assert witnessed > 0
    for before, after in zip(baseline, screened):
        before, after = dict(before), dict(after)
        before.pop("scoring_assessment", None)
        after.pop("scoring_assessment", None)
        assert json.dumps(before, sort_keys=True, allow_nan=True) == json.dumps(after, sort_keys=True, allow_nan=True)
