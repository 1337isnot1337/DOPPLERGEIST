"""Complete-clock fit parity using recorded audio and observed aircraft tracks."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist import batch_ridge
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import (
    RidgeTimes, _cache_ridge_fits, _fit_ridge_uncached, _frequency_scale, _ridge_fit_cache,
    association_candidates, batch_acoustic_trials, prepare_events,
)
from dopplergeist.search import score_candidate
from dopplergeist.tiled_search import _association_clock_window


def _recorded_rounding_case():
    fixture = json.loads((Path(__file__).parent / "data/real-ridge-batch-arithmetic.json").read_text())
    event = fixture["event"]
    measurement = (RidgeTimes(np.asarray(fixture["times"])), np.asarray(fixture["ridge"]),
                   np.asarray(fixture["weight"]), {})
    factors, emissions = np.asarray(fixture["factors"]), np.asarray(fixture["emissions"])
    return fixture, event, measurement, factors, emissions


def test_recorded_power_rounding_keeps_legacy_and_scalar_paths_distinct():
    fixture, event, measurement, factors, emissions = _recorded_rounding_case()
    legacy = batch_ridge.first_event_fits(measurement, event, factors, emissions)
    assert legacy == fixture["legacy_diagnostics"]
    fitted = batch_ridge.supported_clock_fits(measurement, event, (factors, emissions))
    assert fitted is not None
    for index, result in enumerate(fitted):
        scalar = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
            343., _frequency_scale(event), event.get("quality", {}).get("source_drift_fraction", .02),
            acoustic_result=(factors[index], emissions[index]))
        assert result == scalar


def test_real_source_fit_cache_reuses_exact_rows_without_aliasing():
    _, event, measurement, factors, emissions = _recorded_rounding_case()
    calls = 0
    original = batch_ridge._fit_ridge_uncached

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    @_cache_ridge_fits
    def run():
        first = batch_ridge.supported_clock_fits(measurement, event, (factors, emissions))
        assert first is not None
        expected = [dict(row) for row in first]
        count = calls
        first[0]["caller_note"] = "caller-local mutation"
        second = batch_ridge.supported_clock_fits(measurement, event, (factors.copy(), emissions.copy()))
        assert second == expected and calls == count
        subset = batch_ridge.supported_clock_fits(measurement, event, (factors[[1, 2]], emissions[[1, 2]]))
        assert subset == expected[1:3] and calls == count
        # A smaller set of actual recorded samples has different normalization
        # and must not borrow the full-ridge result.
        shorter = (RidgeTimes(measurement[0].time[:-1]), measurement[1][:-1], measurement[2][:-1], {})
        changed = batch_ridge.supported_clock_fits(shorter, event, (factors[:, :-1], emissions[:, :-1]))
        assert changed is not None and calls > count
        count = calls
        quality = dict(event.get("quality", {}), frequency_loss_scale_hz=_frequency_scale(event)*1.01)
        changed_model = batch_ridge.supported_clock_fits(measurement, dict(event, quality=quality),
                                                        (factors, emissions))
        assert changed_model is not None and calls > count

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(batch_ridge, "_fit_ridge_uncached", counted)
        run()


def test_real_source_fit_cache_has_fixed_size_keys_and_a_row_limit():
    _, event, measurement, factors, emissions = _recorded_rounding_case()

    def run():
        expected = batch_ridge.supported_clock_fits(measurement, event, (factors, emissions))
        assert expected is not None
        entries = _ridge_fit_cache.get().source_entries
        assert len(entries) == 2
        assert all(len(prefix) == len(row) == 32 for prefix, row in entries)
        repeated = batch_ridge.supported_clock_fits(measurement, event, (factors, emissions))
        assert repeated == expected
        assert len(entries) == 2

    _cache_ridge_fits(run, max_entries=2)()


@pytest.fixture
def recorded():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    index_path = os.environ.get("DOPPLERGEIST_REAL_INDEX")
    if not source and index_path:
        source = Path(__file__).parent / "data/real-search-workloads.json"
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_INDEX or DOPPLERGEIST_REAL_CPA_FIXTURE to restored real inputs")
    fixture = json.loads(Path(source).read_text())
    if "cases" in fixture:
        case = os.environ.get("DOPPLERGEIST_REAL_CPA_CASE", "previous-fit")
        fixture = dict(fixture, **fixture["cases"][case])
    events, measurements = prepare_events(fixture["events"])
    limits = {}
    if fixture.get("recording_start_window_s"):
        limits["time_origin"], limits["time_tolerance_s"] = _association_clock_window(
            fixture["recording_start_window_s"], 5.)
    candidates, _ = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events,
                                           max_candidates=20000, **limits)
    tracks = {track.id: track for track in FlightIndex(index_path or fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = SimpleNamespace(**dict({"x": 0., "y": 0.}, **fixture["point"]))
    return events, measurements, candidates, tracks, point


def _selection(candidates):
    assert candidates
    # Include the largest real associations as well as a spread across the
    # original enumeration. No new passages or measurements are generated.
    spread = np.linspace(0, len(candidates)-1, min(32, len(candidates)), dtype=int)
    largest = sorted(range(len(candidates)), key=lambda i: -len(candidates[i]["event_indices"]))[:8]
    return [candidates[i] for i in sorted(set(spread) | set(largest))]


@pytest.mark.parametrize("score_floor", [None, 0.])
def test_real_complete_assessments_preserve_every_diagnostic(recorded, monkeypatch, score_floor):
    events, measurements, candidates, tracks, point = recorded
    selected = _selection(candidates)

    @_cache_ridge_fits
    def run():
        return [score_candidate(candidate, point, tracks, events, measurements,
                                mode="robust_ridge", score_floor=score_floor) for candidate in selected]

    with monkeypatch.context() as patch:
        patch.setattr(batch_ridge, "supported_clock_fits", lambda *args: None)
        scalar = run()
    original = batch_ridge.supported_clock_fits
    fitted_batches = 0

    def counted(*args):
        nonlocal fitted_batches
        result = original(*args)
        fitted_batches += result is not None
        return result

    with monkeypatch.context() as patch:
        patch.setattr(batch_ridge, "supported_clock_fits", counted)
        batched = run()
    assert fitted_batches > 0
    assert json.dumps(batched, sort_keys=True, allow_nan=True) == json.dumps(
        scalar, sort_keys=True, allow_nan=True)


@pytest.mark.parametrize("sound_speed", [331., 343.])
def test_real_supported_rows_equal_the_scalar_fitter(recorded, sound_speed):
    events, measurements, candidates, tracks, point = recorded
    observer = ecef(point.lat, point.lon, point.elev_m)
    checked = 0
    for candidate in _selection(candidates)[:12]:
        indices = candidate["event_indices"]
        selected_events = [events[i] for i in indices]
        selected_measurements = [measurements[i] for i in indices]
        selected_tracks = [tracks[p["flight_id"]] for p in candidate["passes"]]
        lower, upper = candidate["recording_start_bounds_s"]
        starts = np.linspace(lower-5., upper+5., max(1, int(np.ceil((upper-lower+10.)/.5)))+1)
        batches = batch_acoustic_trials(selected_tracks, selected_measurements, observer, starts, sound_speed)
        for event, measurement, batch in zip(selected_events, selected_measurements, batches):
            results = batch_ridge.supported_clock_fits(measurement, event, batch)
            if results is None:
                continue
            factors, emissions = batch
            for i, result in enumerate(results):
                if result is None:
                    assert not np.all(np.isfinite(factors[i]) & (factors[i] > 0)
                                      & np.isfinite(emissions[i]))
                    continue
                scalar = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
                    sound_speed, _frequency_scale(event), event.get("quality", {}).get("source_drift_fraction", .02),
                    acoustic_result=(factors[i], emissions[i]))
                assert json.dumps(result, sort_keys=True) == json.dumps(scalar, sort_keys=True)
                checked += 1
    assert checked > 0


def test_real_track_endpoint_preserves_partial_support_and_zero_drift_fallback(recorded):
    events, measurements, candidates, tracks, point = recorded
    observer = ecef(point.lat, point.lon, point.elev_m)
    for candidate in _selection(candidates):
        for index, passage in zip(candidate["event_indices"], candidate["passes"]):
            track, event, measurement = tracks[passage["flight_id"]], events[index], measurements[index]
            times = measurement[0].time
            first_arrival = track.time[0] + np.linalg.norm(track.xyz[0]-observer)/343.
            # Straddle a real trajectory's support boundary; do not alter any
            # recorded sample or manufacture an aircraft trajectory.
            starts = first_arrival - times.min() + np.linspace(-2., 2., 9)
            batch = batch_acoustic_trials([track], [measurement], observer, starts)[0]
            fitted = batch_ridge.supported_clock_fits(measurement, event, batch)
            if fitted is None or not any(result is None for result in fitted):
                continue
            factors, emissions = batch
            for i, result in enumerate(fitted):
                scalar = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
                    343., _frequency_scale(event), event.get("quality", {}).get("source_drift_fraction", .02),
                    acoustic_result=(factors[i], emissions[i]))
                if result is None:
                    assert scalar["support_fraction"] == 0.
                else:
                    assert json.dumps(result, sort_keys=True) == json.dumps(scalar, sort_keys=True)
            no_drift = dict(event, quality=dict(event.get("quality", {}), source_drift_fraction=0.))
            assert batch_ridge.supported_clock_fits(measurement, no_drift, batch) is None
            break
        else:
            continue
        break
    else:
        pytest.fail("No partially supported real trajectory batch exercised")
