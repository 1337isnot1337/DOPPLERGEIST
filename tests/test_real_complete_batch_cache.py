"""Bounded whole-batch reuse on actual recorded ridge/trajectory inputs."""
import json
from pathlib import Path

import numpy as np
import pytest

from dopplergeist import batch_ridge, matching


def recorded():
    fixture = json.loads((Path(__file__).parent/'data/real-ridge-batch-arithmetic.json').read_text())
    measurement = (matching.RidgeTimes(np.asarray(fixture['times'])),
                   np.asarray(fixture['ridge']), np.asarray(fixture['weight']), {})
    return measurement, fixture['event'], np.asarray(fixture['factors']), np.asarray(fixture['emissions'])


def counted_kernel(monkeypatch):
    calls = []
    original = batch_ridge._first_event_fits_uncached

    def run(*args, **options):
        calls.append(1)
        return original(*args, **options)

    monkeypatch.setattr(batch_ridge, '_first_event_fits_uncached', run)
    return calls, original


def test_recorded_complete_batch_cache_preserves_values_and_caller_ownership(monkeypatch):
    measurement, event, factors, emissions = recorded()
    calls, original = counted_kernel(monkeypatch)
    expected = original(measurement, event, factors, emissions)
    assert expected is not None

    @matching._cache_ridge_fits
    def run():
        before = len(calls)
        first = batch_ridge.first_event_fits(measurement, event, factors, emissions)
        assert first == expected and len(calls) == before+1
        first[0]['f0_hz'] = -123.
        first.append({'caller_only': True})
        second = batch_ridge.first_event_fits(measurement, event, factors.copy(), emissions.copy())
        assert second == expected and len(calls) == before+1
        second[1].clear()
        third = batch_ridge.first_event_fits(measurement, event, factors, emissions)
        assert third == expected and len(calls) == before+1
        cache = matching._ridge_fit_cache.get()
        assert len(cache.batch_fit_entries) == 1
        assert cache.batch_fit_bytes == sum(len(key)+len(value) for key, value in cache.batch_fit_entries.items())
        assert 0 < cache.batch_fit_bytes <= cache.batch_fit_limit

    run()
    run()
    assert len(calls) == 2


def test_recorded_batch_layout_and_changed_inputs_do_not_share_results(monkeypatch):
    measurement, event, factors, emissions = recorded()
    calls, original = counted_kernel(monkeypatch)

    @matching._cache_ridge_fits
    def run():
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == original(
            measurement, event, factors, emissions)
        assert len(calls) == 1
        # Fortran layout keeps every observed value but changes reduction
        # strides. Each layout must reproduce its own unchanged kernel result.
        column_factors, column_emissions = np.asfortranarray(factors), np.asfortranarray(emissions)
        expected = original(measurement, event, column_factors, column_emissions)
        assert batch_ridge.first_event_fits(measurement, event, column_factors, column_emissions) == expected
        assert len(calls) == 2
        assert batch_ridge.first_event_fits(measurement, event, column_factors.copy(order='F'),
                                           column_emissions.copy(order='F')) == expected
        assert len(calls) == 2
        # Use a shorter portion of the recorded ridge, without manufacturing
        # samples. Its normalization and acoustic arrays require another key.
        shorter = (matching.RidgeTimes(measurement[0].time[:-1]),
                   measurement[1][:-1], measurement[2][:-1], {})
        assert batch_ridge.first_event_fits(shorter, event, factors[:, :-1], emissions[:, :-1]) == original(
            shorter, event, factors[:, :-1], emissions[:, :-1])
        assert len(calls) == 3
        quality = dict(event.get('quality', {}), frequency_loss_scale_hz=matching._frequency_scale(event)*1.01)
        changed_model = dict(event, quality=quality)
        assert batch_ridge.first_event_fits(measurement, changed_model, factors, emissions) == original(
            measurement, changed_model, factors, emissions)
        assert len(calls) == 4

    run()


def test_recorded_batch_cache_respects_byte_and_entry_limits(monkeypatch):
    measurement, event, factors, emissions = recorded()
    calls, original = counted_kernel(monkeypatch)

    def run():
        cache = matching._ridge_fit_cache.get()
        expected = original(measurement, event, factors, emissions)
        batch_ridge.first_event_fits(measurement, event, factors, emissions)
        batch_ridge.first_event_fits(measurement, event, factors[::-1], emissions[::-1])
        assert len(cache.batch_fit_entries) == 1
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == expected
        assert len(calls) == 3
        cache.batch_fit_entries.clear()
        cache.batch_fit_bytes = 0
        cache.batch_fit_limit = 1
        for _ in range(2):
            assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == expected
        assert not cache.batch_fit_entries and cache.batch_fit_bytes == 0
        assert len(calls) == 5

    matching._cache_ridge_fits(run, max_entries=1)()


def test_recorded_zero_drift_fallback_is_not_cached(monkeypatch):
    measurement, event, factors, emissions = recorded()
    calls, _ = counted_kernel(monkeypatch)
    no_drift = dict(event, quality=dict(event.get('quality', {}), source_drift_fraction=0.))

    @matching._cache_ridge_fits
    def run():
        for _ in range(2):
            assert batch_ridge.first_event_fits(measurement, no_drift, factors, emissions) is None
        assert len(calls) == 2
        cache = matching._ridge_fit_cache.get()
        assert not cache.batch_fit_entries and cache.batch_fit_bytes == 0

    run()


def test_recorded_warm_cache_does_not_hide_invalid_measurement_arity():
    measurement, event, factors, emissions = recorded()

    class DifferentIteration(list):
        def __iter__(self):
            return iter(measurement[:3])

    @matching._cache_ridge_fits
    def run():
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions) is not None
        for invalid in (measurement[:3], measurement+(None,), DifferentIteration(measurement)):
            with pytest.raises(ValueError, match='unpack'):
                batch_ridge.first_event_fits(invalid, event, factors, emissions)
        assert len(matching._ridge_fit_cache.get().batch_fit_entries) == 1

    run()


def test_recorded_fitter_replacement_clears_previous_snapshots(monkeypatch):
    measurement, event, factors, emissions = recorded()
    original = batch_ridge._first_event_fits_uncached
    expected = original(measurement, event, factors, emissions)
    calls = []

    def first(*args, **options):
        calls.append('first')
        return original(*args, **options)

    def second(*args, **options):
        calls.append('second')
        return original(*args, **options)

    @matching._cache_ridge_fits
    def run():
        for kernel, expected_calls in ((first, ['first']),
                                       (second, ['first', 'second']),
                                       (first, ['first', 'second', 'first'])):
            monkeypatch.setattr(batch_ridge, '_first_event_fits_uncached', kernel)
            for _ in range(2):
                assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == expected
            assert calls == expected_calls
            assert len(matching._ridge_fit_cache.get().batch_fit_entries) == 1

    run()


def test_recorded_custom_inputs_bypass_a_warm_cache(monkeypatch):
    from types import SimpleNamespace

    measurement, event, factors, emissions = recorded()
    calls, original = counted_kernel(monkeypatch)
    expected = original(measurement, event, factors, emissions)

    class CustomEvent(dict):
        pass

    custom_time = (SimpleNamespace(time=measurement[0].time), *measurement[1:])
    cases = ((custom_time, event), (measurement, CustomEvent(event)),
             (measurement, dict(event, quality=CustomEvent(event.get('quality', {})))))

    @matching._cache_ridge_fits
    def run():
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == expected
        for custom_measurement, custom_event in cases:
            before = len(calls)
            for _ in range(2):
                assert batch_ridge.first_event_fits(custom_measurement, custom_event, factors, emissions) == expected
            assert len(calls) == before + 2
        assert len(matching._ridge_fit_cache.get().batch_fit_entries) == 1

    run()


def test_recorded_cache_separates_legacy_arithmetic(monkeypatch):
    measurement, event, factors, emissions = recorded()
    calls, original = counted_kernel(monkeypatch)
    ordinary = original(measurement, event, factors, emissions)
    legacy = original(measurement, event, factors, emissions, legacy_arithmetic=True)
    assert ordinary is not None

    @matching._cache_ridge_fits
    def run():
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == ordinary
        assert len(calls) == 1
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions,
                                           legacy_arithmetic=True) == legacy
        assert len(calls) == 2
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions) == ordinary
        assert len(calls) == 2
        assert batch_ridge.first_event_fits(measurement, event, factors, emissions,
                                           legacy_arithmetic=True) == legacy
        assert len(calls) == (3 if legacy is None else 2)

    run()
