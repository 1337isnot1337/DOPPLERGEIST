"""Scalar/batch parity on recorded ridges and an observed four-flight candidate.

Set DOPPLERGEIST_REAL_REGION_PARQUET to the original reference-region.parquet
checkpoint. These are computation regressions, not independent location tests.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist.batch_ridge import first_event_fits
from dopplergeist.geometry import ecef
from dopplergeist.matching import (_fit_ridge_uncached, _frequency_scale,
                                   batch_acoustic_trials, prepare_events)
from dopplergeist.search import cpa_table, score_candidate
from dopplergeist.tiled_search import _association_clock_window
from dopplergeist.tracks import load_tracks


@pytest.fixture(scope="module")
def recorded_case():
    source = os.environ.get("DOPPLERGEIST_REAL_REGION_PARQUET")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_REGION_PARQUET to the real regional observations")
    root = Path(__file__).resolve().parents[1]
    proposals = json.loads((root / "evidence/audio/w1-sensitivity-20261102/reference/discovery.json").read_text())["events"]
    events, measurements = prepare_events(proposals)
    saved = json.loads((root / "evidence/results/reference-local/report.json").read_text())["best"]
    point = SimpleNamespace(**{key: saved[key] for key in ("point_id", "lat", "lon", "elev_m", "x", "y")})
    clock = saved["recording_start_time_s"]
    window = (clock - 120., clock + 120.)
    track_window = (window[0] - 240., window[1] + max(event["end_s"] for event in proposals) + 240.)
    observed, _ = load_tracks(source, time_range=track_window)
    tracks = {track.id: track for track in observed}

    # This discarded mode exposed a difference at a clock omitted by the
    # batch fitter's three representative scalar checks.
    indices = [5, 7, 9, 10]
    identifiers = ["ab50b9:1", "aa340e:0", "a50341:2", "a1dfeb"]
    emissions = [1788899360.29, 1788899674.95, 1788900044.81, 1788900787.9874015]
    table = cpa_table([tracks[name] for name in identifiers], pd.DataFrame([vars(point)]), 20000.)
    passes = []
    for name, emission in zip(identifiers, emissions):
        rows = table[table.flight_id == name]
        assert len(rows)
        row = rows.iloc[int(np.argmin(np.abs(rows.emission_time.to_numpy() - emission)))].to_dict()
        assert abs(row["emission_time"] - emission) < 1e-6
        passes.append(row)
    center, tolerance = _association_clock_window(window, 5.)
    lower, upper = center - tolerance, center + tolerance
    for index, row in zip(indices, passes):
        event = events[index]
        anchor = row["receive_time"] - event["cpa_receive_s"]
        margin = event.get("quality", {}).get("cpa_tolerance_s", 0) + 2.5
        lower, upper = max(lower, anchor - margin), min(upper, anchor + margin)
    lower, upper = max(lower - 5., window[0]), min(upper + 5., window[1])
    candidate = {"point_id": point.point_id, "passes": passes, "event_indices": indices,
                 "recording_start_bounds_s": [lower, upper]}
    event, measurement = events[indices[0]], measurements[indices[0]]
    anchor = passes[0]["receive_time"] - event["cpa_receive_s"]
    shifts = np.linspace(lower - anchor, upper - anchor,
                         max(1, int(np.ceil((upper - lower) / .5))) + 1)
    batch = batch_acoustic_trials([tracks[identifiers[0]]], [measurement],
                                 ecef(point.lat, point.lon, point.elev_m), anchor + shifts)[0]
    assert batch is not None
    return candidate, point, tracks, events, measurements, event, measurement, batch


def test_real_batch_matches_scalar_at_every_clock(recorded_case):
    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    fitted = first_event_fits(measurement, event, factors, emissions)
    assert fitted is not None
    assert len(fitted) == 39
    for index, result in enumerate(fitted):
        expected = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
                                      343., _frequency_scale(event),
                                      event.get("quality", {}).get("source_drift_fraction", .02),
                                      acoustic_result=(factors[index], emissions[index]))
        assert result == expected


def test_real_screened_candidate_matches_full_scalar_evaluation(recorded_case, monkeypatch):
    import dopplergeist.batch_ridge as batch_ridge

    candidate, point, tracks, events, measurements, *_ = recorded_case
    with monkeypatch.context() as context:
        context.setattr(batch_ridge, "first_event_fits", lambda *args, **kwargs: None)
        full = score_candidate(candidate, point, tracks, events, measurements,
                               mode="robust_ridge", time_sweep_s=0.)
    for floor in (0., 1.6244675383457703):
        screened = score_candidate(candidate, point, tracks, events, measurements,
                                   mode="robust_ridge", time_sweep_s=0., score_floor=floor)
        assert json.dumps(screened, sort_keys=True) == json.dumps(full, sort_keys=True)


def test_real_batch_numeric_overflow_preserves_scalar_fallback(recorded_case):
    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    extreme = dict(event, quality=dict(event.get("quality", {}), frequency_loss_scale_hz=1e155))
    assert first_event_fits(measurement, extreme, factors, emissions) is None


def test_real_batch_reference_checks_keep_running_with_cached_scalar_work(recorded_case, monkeypatch):
    from dopplergeist import batch_ridge, matching

    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    expected = first_event_fits(measurement, event, factors, emissions)
    assert expected is not None
    scalar_calls, reference_checks, numerical_calls = [], [], []
    original_reference = batch_ridge._scalar_reference_fit
    original_numerical = batch_ridge._fit_ridge_batch_uncached

    def counted_scalar(*args, **kwargs):
        scalar_calls.append(1)
        return _fit_ridge_uncached(*args, **kwargs)

    def counted_reference(*args, **kwargs):
        reference_checks.append(1)
        return original_reference(*args, **kwargs)

    def counted_numerical(*args, **kwargs):
        numerical_calls.append(1)
        return original_numerical(*args, **kwargs)

    monkeypatch.setattr(matching, "_fit_ridge_uncached", counted_scalar)
    monkeypatch.setattr(batch_ridge, "_scalar_reference_fit", counted_reference)
    monkeypatch.setattr(batch_ridge, "_fit_ridge_batch_uncached", counted_numerical)

    @matching._cache_ridge_fits
    def repeated_batch():
        before = len(scalar_calls)
        computations = len(numerical_calls)
        first = first_event_fits(measurement, event, factors, emissions)
        assert first == expected
        assert len(scalar_calls) == before + 3
        first[0]["score"] = float("nan")
        first.pop()
        second = first_event_fits(measurement, event, factors.copy(), emissions.copy())
        assert second == expected
        second[0]["score"] = float("nan")
        second.pop()
        assert first_event_fits(measurement, event, factors, emissions) == expected
        assert len(scalar_calls) == before + 3
        assert len(numerical_calls) == computations + 1

    repeated_batch()
    assert len(reference_checks) == 9
    assert matching._ridge_fit_cache.get() is None
    # A later scoring context must compute its own scalar reference values.
    repeated_batch()
    assert len(reference_checks) == 18 and len(scalar_calls) == 6
    assert len(numerical_calls) == 2
    assert matching._ridge_fit_cache.get() is None


def test_real_cached_scalar_reference_tracks_mutation_and_capacity(recorded_case, monkeypatch):
    from dopplergeist import batch_ridge, matching

    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    arguments = (None, None, measurement, 0., event["f0_range_hz"], 343.,
                 _frequency_scale(event), event.get("quality", {}).get("source_drift_fraction", .02))
    expected = [_fit_ridge_uncached(*arguments, acoustic_result=(factors[i], emissions[i]))
                for i in (0, 1)]
    scalar_calls = []

    def counted_scalar(*args, **kwargs):
        scalar_calls.append(1)
        return _fit_ridge_uncached(*args, **kwargs)

    monkeypatch.setattr(matching, "_fit_ridge_uncached", counted_scalar)

    def changed_recorded_clock():
        acoustic = (factors[0].copy(), emissions[0].copy())
        first = batch_ridge._scalar_reference_fit(*arguments, acoustic_result=acoustic)
        assert first == expected[0] and len(scalar_calls) == 1
        first["score"] = float("nan")
        first["candidate_note"] = "local diagnostic annotation"
        assert batch_ridge._scalar_reference_fit(*arguments, acoustic_result=acoustic) == expected[0]
        assert len(scalar_calls) == 1
        # Reuse these array objects for another actual clock from this batch.
        # Cache identity must follow their contents rather than object identity.
        acoustic[0][:], acoustic[1][:] = factors[1], emissions[1]
        assert batch_ridge._scalar_reference_fit(*arguments, acoustic_result=acoustic) == expected[1]
        assert len(scalar_calls) == 2
        cache = matching._ridge_fit_cache.get()
        assert len(cache.entries) == 1
        acoustic[0][:], acoustic[1][:] = factors[0], emissions[0]
        assert batch_ridge._scalar_reference_fit(*arguments, acoustic_result=acoustic) == expected[0]
        assert len(scalar_calls) == 3 and len(cache.entries) == 1

    matching._cache_ridge_fits(changed_recorded_clock, max_entries=1)()
    assert matching._ridge_fit_cache.get() is None


def test_real_batch_cache_keys_follow_recorded_rows_and_measured_inputs(recorded_case, monkeypatch):
    from copy import deepcopy
    from dopplergeist import batch_ridge, matching

    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    changed_measurement = deepcopy(measurement)
    changed_measurement[2][0] = np.nextafter(changed_measurement[2][0], np.inf)
    changed_event = dict(event, f0_range_hz=[float(np.nextafter(event["f0_range_hz"][0], -np.inf)),
                                           event["f0_range_hz"][1]])
    # Reorder or replace rows with other actual clocks; no new trajectory data.
    order = np.arange(len(factors))
    order[[0, 1]] = order[[1, 0]]
    replaced_factors, replaced_emissions = factors.copy(), emissions.copy()
    replaced_factors[0], replaced_emissions[0] = factors[1], emissions[1]
    cases = [(measurement, event, factors, emissions),
             (measurement, event, factors[order], emissions[order]),
             (measurement, event, replaced_factors, replaced_emissions),
             (changed_measurement, event, factors, emissions),
             (measurement, changed_event, factors, emissions)]
    expected = [first_event_fits(*case) for case in cases]
    assert all(value is not None for value in expected)
    calls = []
    original = batch_ridge._fit_ridge_batch_uncached

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_ridge, "_fit_ridge_batch_uncached", counted)

    @matching._cache_ridge_fits
    def check():
        for index, (case, result) in enumerate(zip(cases, expected), 1):
            assert first_event_fits(*case) == result
            assert len(calls) == index
            assert first_event_fits(*case) == result
            assert len(calls) == index
        assert len(matching._ridge_fit_cache.get().batch_entries) == len(cases)
    check()


def test_real_batch_cache_respects_entry_and_byte_limits(recorded_case, monkeypatch):
    from dopplergeist import batch_ridge, matching

    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    order = np.arange(len(factors))[::-1]
    cases = [(measurement, event, factors, emissions),
             (measurement, event, factors[order], emissions[order])]
    expected = [first_event_fits(*case) for case in cases]
    assert all(value is not None for value in expected)
    calls = []
    original = batch_ridge._fit_ridge_batch_uncached

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_ridge, "_fit_ridge_batch_uncached", counted)

    def one_entry():
        cache = matching._ridge_fit_cache.get()
        for index in (0, 1, 0):
            assert first_event_fits(*cases[index]) == expected[index]
            assert len(cache.batch_entries) == 1
            assert 0 < cache.batch_bytes + cache.batch_container_reserve <= cache.batch_limit
            assert cache.batch_bytes == sum(size for _, size in cache.batch_entries.values())
        assert len(calls) == 3
    matching._cache_ridge_fits(one_entry, max_entries=1)()

    @matching._cache_ridge_fits
    def tiny_budget():
        cache = matching._ridge_fit_cache.get()
        assert first_event_fits(*cases[0]) == expected[0]
        assert cache.batch_entries
        reserve = cache.batch_container_reserve
        # The real result fits the raw limit, but not after the fixed backing
        # table reserve. Eviction must not discard that historical allowance.
        for limit in (reserve + cache.batch_bytes - 1, 1):
            cache.batch_limit = limit
            assert first_event_fits(*cases[0]) == expected[0]
            assert not cache.batch_entries and cache.batch_bytes == 0
            assert cache.batch_container_reserve == reserve
    tiny_budget()
    assert len(calls) == 6
    assert matching._ridge_fit_cache.get() is None


def test_real_batch_cache_preserves_noncanonical_array_layouts(recorded_case, monkeypatch):
    from dopplergeist import batch_ridge, matching

    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    layouts = [(np.asfortranarray(factors), np.asfortranarray(emissions)),
               (np.repeat(factors, 2, axis=0)[::2], np.repeat(emissions, 2, axis=0)[::2])]
    unaligned = []
    for values in (factors, emissions):
        array = np.ndarray(values.shape, dtype=values.dtype,
                           buffer=bytearray(values.nbytes + 1), offset=1)
        array[:] = values
        assert array.flags.c_contiguous and not array.flags.aligned
        unaligned.append(array)
    layouts.append(tuple(unaligned))
    expected = [first_event_fits(measurement, event, *layout) for layout in layouts]
    baseline = first_event_fits(measurement, event, factors, emissions)
    assert baseline is not None
    calls = []
    original = batch_ridge._fit_ridge_batch_uncached

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(batch_ridge, "_fit_ridge_batch_uncached", counted)

    @matching._cache_ridge_fits
    def check():
        assert first_event_fits(measurement, event, factors, emissions) == baseline
        for layout, result in zip(layouts, expected):
            assert all(np.array_equal(value, source) for value, source in zip(layout, (factors, emissions)))
            before = len(calls)
            for _ in range(2):
                assert first_event_fits(measurement, event, *layout) == result
            assert len(calls) == before + 2
        assert len(matching._ridge_fit_cache.get().batch_entries) == 1
    check()


def test_real_batch_cache_still_rejects_reference_disagreement(recorded_case, monkeypatch):
    from dopplergeist import batch_ridge, matching

    _, _, _, _, _, event, measurement, (factors, emissions) = recorded_case
    original = batch_ridge._scalar_reference_fit
    expected = first_event_fits(measurement, event, factors, emissions)
    assert expected is not None

    def disagree(*args, **kwargs):
        result = original(*args, **kwargs)
        return dict(result, score=float(np.nextafter(result["score"], np.inf)))

    @matching._cache_ridge_fits
    def cached_rejection():
        assert first_event_fits(measurement, event, factors, emissions) == expected
        with monkeypatch.context() as patch:
            patch.setattr(batch_ridge, "_scalar_reference_fit", disagree)
            assert first_event_fits(measurement, event, factors, emissions) is None
        assert first_event_fits(measurement, event, factors, emissions) == expected
    cached_rejection()

    @matching._cache_ridge_fits
    def uncached_rejection():
        with monkeypatch.context() as patch:
            patch.setattr(batch_ridge, "_scalar_reference_fit", disagree)
            assert first_event_fits(measurement, event, factors, emissions) is None
        assert not matching._ridge_fit_cache.get().batch_entries
    uncached_rejection()
