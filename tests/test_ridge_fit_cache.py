"""Behavioral controls for bounded, batch-local reuse of physical ridge fits."""
from types import SimpleNamespace

import numpy as np
import pytest

from aircraft_geoloc import matching
from aircraft_geoloc.finite_search import RetentionLedger
from aircraft_geoloc.geometry import Track, ecef
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import SearchBudget, _score, tile_points
from test_tiled_search import scenario


def test_six_event_batch_reuses_fits_without_changing_modes_or_assessments(tmp_path, monkeypatch):
    _, tracks, events, measurements, bounds, _, origin = scenario(
        tmp_path, count=6, receiver_offset=(250, 250))
    points = tile_points((1, 7601, 2, 7602), 250, bounds, Terrain(constant_m=0), "EPSG:5070")
    budget = SearchBudget(top_k=5)
    settings = {"mode": "robust_ridge", "time_origin": origin, "time_sweep_s": 0}
    compute_name = "_fit_ridge_uncached" if hasattr(matching, "_fit_ridge_uncached") else "fit_ridge"
    compute = getattr(matching, compute_name)
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return compute(*args, **kwargs)

    monkeypatch.setattr(matching, compute_name, counted)
    results, evidence, computations = [], [], []
    for name, score in [("reference", getattr(_score, "__wrapped__", _score)), ("cached", _score)]:
        directory = tmp_path / name
        directory.mkdir()
        ledger = RetentionLedger(directory / "retention.sqlite", "cache-control",
                                 "matched_group_support_minus_normalized_residual")
        calls = 0
        rows, counts = score(points, tracks, events, measurements, budget, settings, {},
                             ledger=ledger, stage="coarse:point")
        results.append((rows, counts))
        evidence.append(ledger.evidence(rows, complete=True, spacing_m=250, refine_spacing_m=250,
                                        max_event_groups=6, expected_stages={"coarse": 1}))
        computations.append(calls)
    assert results[0] == results[1]
    assert evidence[0] == evidence[1]
    rows, counts = results[1]
    assert counts["candidates"] == 63 and counts["unclassified_score_candidates"] == 0
    assert len(rows) == 5 and len(rows[0]["event_indices"]) == 6
    assert evidence[1]["complete"] and evidence[1]["evaluated_modes"] == 63
    assert evidence[1]["discarded_count"] == 58
    assert computations == [384, 6]


def fit_inputs(tmp_path):
    _, tracks, _, measurements, _, _, origin = scenario(tmp_path)
    observer = ecef(tracks[0].lat[len(tracks[0].lat) // 2],
                    tracks[0].lon[len(tracks[0].lon) // 2], 0)
    return tracks[0], observer, measurements[0], origin, (115., 125.)


def test_fit_cache_keys_include_physical_inputs_and_measurement_contents(tmp_path, monkeypatch):
    base = fit_inputs(tmp_path)
    track, observer, measurement, start, frequency_bounds = base
    compute = matching._fit_ridge_uncached
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return compute(*args, **kwargs)

    monkeypatch.setattr(matching, "_fit_ridge_uncached", counted)

    @matching._cache_ridge_fits
    def evaluate():
        arguments = dict(track=track, observer=observer, measurement=measurement, start_time=start,
                         f0_bounds=frequency_bounds, c=343., sigma_hz=1., drift_fraction=.02)
        assert matching.fit_ridge(**arguments) == compute(**arguments)
        assert matching.fit_ridge(**arguments) == compute(**arguments)
        assert calls == 1
        alternate = Track(track.id, track.time, track.lat, track.lon + .001, track.altitude)
        nearby = observer.copy()
        nearby[0] = np.nextafter(nearby[0], np.inf)
        variants = [("track", alternate), ("observer", nearby), ("start_time", start + .1),
                    ("f0_bounds", (116., 126.)), ("c", 342.), ("sigma_hz", 1.1), ("drift_fraction", .01)]
        for field, value in variants:
            changed = dict(arguments, **{field: value})
            assert matching.fit_ridge(**changed) == compute(**changed)
        # Reusing the same arrays after an in-place measurement edit must miss.
        for field in range(3):
            if field == 0:
                measurement[0].time[0] += .001
            else:
                measurement[field][0] += .1
            assert matching.fit_ridge(**arguments) == compute(**arguments)
        assert calls == 1 + len(variants) + 3

    evaluate()


def test_cache_eviction_copies_results_and_releases_scope_on_error(tmp_path, monkeypatch):
    arguments = fit_inputs(tmp_path)
    compute = matching._fit_ridge_uncached
    expected = compute(*arguments)
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return compute(*args, **kwargs)

    monkeypatch.setattr(matching, "_fit_ridge_uncached", counted)

    def batch():
        first = matching.fit_ridge(*arguments)
        first["f0_hz"] = -999.
        assert matching.fit_ridge(*arguments) == expected
        for shift in (.1, .2):
            changed = (*arguments[:3], arguments[3] + shift, arguments[4])
            assert matching.fit_ridge(*changed) == compute(*changed)
        assert len(matching._ridge_fit_cache.get().entries) == 2
        assert matching.fit_ridge(*arguments) == expected
        assert calls == 4
        raise RuntimeError("end this batch")

    cached = matching._cache_ridge_fits(batch, max_entries=2)
    with pytest.raises(RuntimeError, match="end this batch"):
        cached()
    assert matching._ridge_fit_cache.get() is None
    assert matching.fit_ridge(*arguments) == expected
    assert calls == 5


def test_typed_support_errors_are_never_replaced_with_cached_fit(tmp_path, monkeypatch):
    from aircraft_geoloc.geometry import AcousticSupportError

    arguments = fit_inputs(tmp_path)
    original = matching._fit_ridge_uncached
    calls = 0

    def unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AcousticSupportError(arguments[0].id, "test_unavailable_source")

    monkeypatch.setattr(matching, "_fit_ridge_uncached", unavailable)

    @matching._cache_ridge_fits
    def batch():
        for _ in range(2):
            with pytest.raises(AcousticSupportError, match="test_unavailable_source"):
                matching.fit_ridge(*arguments)
        assert len(matching._ridge_fit_cache.get().entries) == 0

    batch()
    assert calls == 2
    monkeypatch.setattr(matching, "_fit_ridge_uncached", original)
    assert np.isfinite(matching.fit_ridge(*arguments)["score"])


def test_invalid_scalar_measurement_does_not_reuse_a_one_sample_fit(tmp_path):
    track, observer, _, start, bounds = fit_inputs(tmp_path)
    one_sample = (SimpleNamespace(time=np.array([10.])), np.array([120.]), np.array([1.]), {})
    scalar = (SimpleNamespace(time=np.array(10.)), np.array(120.), np.array(1.), {})

    @matching._cache_ridge_fits
    def batch():
        assert matching.fit_ridge(track, observer, one_sample, start, bounds)["support_fraction"] == 0
        with pytest.raises(ValueError, match="one-dimensional arrays"):
            matching.fit_ridge(track, observer, scalar, start, bounds)

    batch()


def test_scalar_precision_is_preserved_in_the_fit_cache_key(tmp_path):
    arguments = fit_inputs(tmp_path)
    ridge = arguments[2][1]
    ridge += .4 * (-1.) ** np.arange(len(ridge))
    single = np.float32(1.234567)
    double = float(single)
    expected = [matching._fit_ridge_uncached(*arguments, sigma_hz=value) for value in (single, double)]
    assert expected[0] != expected[1], "The fixture must expose scalar arithmetic precision"

    @matching._cache_ridge_fits
    def batch():
        assert [matching.fit_ridge(*arguments, sigma_hz=value) for value in (single, double)] == expected

    batch()
