from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
from pyproj import Transformer
import pytest

from dopplergeist.audio import Spectrum
from dopplergeist.data_access import DataUnavailable, FlightIndex
from dopplergeist.geometry import Track, ecef
from dopplergeist.terrain import Terrain
from dopplergeist.tiled_search import SearchBudget, _score, grid_tiles, merge_candidates, search_national, tile_points


def scenario(tmp_path, count=2, receiver_offset=(0, 0)):
    inverse = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
    # Winning receiver x=0 is exactly on tile boundaries for all tile sizes.
    lon, lat = inverse.transform(receiver_offset[0], 1900000 + receiver_offset[1])
    origin = 1800000000.
    frames, tracks, events, measurements = [], [], [], []
    observer = ecef(lat, lon, 0)
    centers = 150. + np.arange(count) * 500
    for number, center in enumerate(centers):
        t = np.arange(center - 150, center + 151, 5)
        x = (t - center) * 80
        y = np.full(len(t), 1900000 + number * 200)
        flon, flat = inverse.transform(x, y)
        track = Track(f"flight{number}", t + origin, flat, flon, np.full(len(t), 1200))
        tracks.append(track)
        frames.append(pd.DataFrame({"flight_id": track.id, "time_s": track.time, "lat": flat,
                                    "lon": flon, "alt_m": 1200, "altitude_basis": "ellipsoidal"}))
        received = t[24:37]
        factor, _, _ = track.acoustic(origin + received, observer)
        spectrum = Spectrum(received, np.arange(80, 161), np.zeros((81, len(received))), np.zeros((81, len(received))))
        ridge = factor * 120
        measurements.append((spectrum, ridge, np.ones(len(ridge)), {}))
        cpa = track.closest_approaches(observer, 4000)[0]["receive_time"] - origin
        events.append({"start_s": float(received[0]), "end_s": float(received[-1]), "cpa_receive_s": cpa,
                       "speed_range_mps": [50, 110], "slant_range_m": [500, 4000], "f0_range_hz": [115, 125]})
    bounds = inverse.transform_bounds(-2200, 1897800, 2200, 1902200, densify_pts=21)
    times = [origin, origin + centers[-1] + 151]
    index = FlightIndex.build(tmp_path / "flights.sqlite", frames, sources=[],
                              coverage={"bounds": [-125, 24, -66, 50], "time_range_s": times, "all_aircraft": True})
    return index, tracks, events, measurements, bounds, times, origin


def compact(rows):
    return [(tuple(r["flight_ids"]), r["x"], r["y"], round(r["score"], 8), round(r["recording_start_time_s"], 5)) for r in rows]


def test_tiled_equals_untiled_boundary_and_locked_timing(tmp_path):
    index, tracks, events, measurements, bounds, times, origin = scenario(tmp_path)
    terrain = Terrain(constant_m=0)
    budget = SearchBudget(spacing_m=1000, tile_cells=2, top_k=200, refine_spacing_m=1000)
    settings = {"mode": "ridge", "time_origin": origin, "time_sweep_s": 0}
    all_points = pd.concat([tile_points(cells, 1000, bounds, terrain, "EPSG:5070") for _, cells in grid_tiles(bounds, 1000, 2)], ignore_index=True)
    all_points["point_id"] = np.arange(len(all_points))
    expected, _ = _score(all_points, tracks, events, measurements, budget, settings, {})
    result = search_national([index], terrain, events, measurements, time_range_s=times, output_dir=tmp_path / "run",
                             bounds=bounds, budget=budget, scoring=settings)
    assert result["status"] == "complete"
    assert compact(result["ranked"]) == compact(expected)
    assert result["ranked"][0]["x"] == 0 and result["ranked"][0]["y"] == 1900000
    replay = search_national([index], terrain, events, measurements, time_range_s=times, output_dir=tmp_path / "run",
                             bounds=bounds, budget=budget, scoring=settings)
    assert replay["tiles_resumed"] == replay["tiles_total"]
    assert compact(replay["ranked"]) == compact(result["ranked"])
    with pytest.raises(DataUnavailable, match="mismatch"):
        search_national([index], terrain, events, measurements, time_range_s=times, output_dir=tmp_path / "run",
                        bounds=bounds, budget=replace(budget, spacing_m=900), scoring=settings)


def test_budget_exhaustion_and_source_holes_are_partial(tmp_path):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    kwargs = dict(time_range_s=times, bounds=bounds, scoring={"mode": "ridge", "time_origin": origin, "time_sweep_s": 0})
    limited = search_national([index], Terrain(constant_m=0), events, measurements, output_dir=tmp_path / "limited",
                              budget=SearchBudget(max_tiles=1, tile_cells=1, refine_spacing_m=2000), **kwargs)
    assert limited["status"] == "partial" and limited["unsearched_tiles"] > 0
    overloaded = search_national([index], Terrain(constant_m=0), events, measurements, output_dir=tmp_path / "overloaded",
                                 budget=SearchBudget(max_tracks_per_tile=1, tile_cells=4, refine_spacing_m=2000), **kwargs)
    assert overloaded["status"] == "partial" and overloaded["tile_failures"]
    # A source scope ending before the query cannot establish complete coverage.
    kwargs["time_range_s"] = [times[0], times[1] + 1]
    missing = search_national([index], Terrain(constant_m=0), events, measurements, output_dir=tmp_path / "missing",
                             budget=SearchBudget(refine_spacing_m=2000), **kwargs)
    assert not missing["data_scope_complete"] and missing["status"] == "partial"


def test_merge_is_deterministic_and_preserves_repeat_approaches():
    base = {"score": 1., "flight_ids": ["a"], "x": 0., "y": 0., "recording_start_time_s": 0.}
    first = dict(base, pass_emission_times_s=[100.])
    second = dict(base, pass_emission_times_s=[300.])
    assert merge_candidates([second, first, first], 10) == [first, second]
    assert merge_candidates([first, second], 10) == merge_candidates([second, first], 10)


def test_ridge_only_adapter_and_exact_recording_clock(tmp_path):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    measurements = [(SimpleNamespace(time=spec.time), ridge, weight, fit) for spec, ridge, weight, fit in measurements]
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
                             output_dir=tmp_path / "ridge-only", bounds=bounds,
                             budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000),
                             scoring={"mode": "ridge", "recording_start_window_s": [origin, origin]})
    assert result["ranked"]
    assert all(row["recording_start_time_s"] == origin for row in result["ranked"])


def test_overlapping_refinement_scores_the_complete_grid_union_once(tmp_path, monkeypatch):
    from dopplergeist import tiled_search

    index, tracks, events, measurements, bounds, times, origin = scenario(tmp_path)
    # A translated alternative flight pair produces a competing location whose
    # refinement overlaps the first pair. Both associations must be retained.
    forward = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)
    inverse = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
    frames = []
    for track in list(tracks):
        x, y = forward.transform(track.lon, track.lat)
        lon, lat = inverse.transform(x + 1000, y)
        alternative = Track("alternative-" + track.id, track.time, lat, lon, track.altitude)
        tracks.append(alternative)
        for item in (track, alternative):
            frames.append(pd.DataFrame({"flight_id": item.id, "time_s": item.time,
                                        "lat": item.lat, "lon": item.lon, "alt_m": item.altitude,
                                        "altitude_basis": "ellipsoidal"}))
    index = FlightIndex.build(tmp_path / "alternatives.sqlite", frames, sources=[],
                              coverage=index.report["coverage"])
    terrain = Terrain(constant_m=0)
    budget = SearchBudget(spacing_m=1000, tile_cells=4, top_k=200,
                          refine_spacing_m=500, refine_finalists=4)
    settings = {"mode": "ridge", "time_origin": origin, "time_sweep_s": 0}
    requested, evaluated = [], []
    fine_phase = False

    def observe_points(cells, spacing, *args):
        nonlocal fine_phase
        fine_phase = spacing == budget.refine_spacing_m
        points = tile_points(cells, spacing, *args)
        if fine_phase:
            requested.append(points.copy())
        return points

    def observe_score(points, *args, **kwargs):
        if fine_phase:
            evaluated.extend(zip(points.x, points.y))
        return _score(points, *args, **kwargs)

    monkeypatch.setattr(tiled_search, "tile_points", observe_points)
    monkeypatch.setattr(tiled_search, "_score", observe_score)
    result = search_national([index], terrain, events, measurements, time_range_s=times,
                             output_dir=tmp_path / "overlap", bounds=bounds, budget=budget, scoring=settings)
    all_points = pd.concat(requested, ignore_index=True)
    union = all_points.drop_duplicates(["x", "y"]).copy()
    assert len(all_points) > len(union), "Fixture must include overlapping refinement rectangles"
    assert len(evaluated) == len(set(evaluated))
    assert set(evaluated) == set(zip(union.x, union.y))
    assert result["refinement_points_searched"] == len(union)
    assert result["refinement_points_skipped"] == len(all_points) - len(union)
    union["point_id"] = np.arange(len(union))
    expected, _ = _score(union, tracks, events, measurements, budget, settings, {})
    expected = merge_candidates(result["coarse_ranked"] + expected, budget.top_k)
    assert len({tuple(row["flight_ids"]) for row in expected}) >= 2
    assert compact(result["ranked"]) == compact(expected)


def test_work_limit_does_not_enumerate_unsearched_national_grid(tmp_path):
    index, _, events, measurements, _, times, origin = scenario(tmp_path)
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
                             output_dir=tmp_path / "huge-grid",
                             budget=SearchBudget(spacing_m=1, tile_cells=32, max_tiles=1, refine_spacing_m=1),
                             scoring={"mode": "ridge", "time_origin": origin, "time_sweep_s": 0})
    assert result["status"] == "partial" and result["tiles_completed"] == 1
    assert result["tiles_total"] > 1000000000


def test_subset_matching_keeps_good_events_after_unmatched_proposal(tmp_path):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    for i, event in enumerate(events):
        event["event_id"] = f"supported-{i}"
    spurious = dict(events[0], event_id="noise-proposal", start_s=20., end_s=40., cpa_receive_s=30.)
    t = np.linspace(20, 40, 41)
    measurements = [(SimpleNamespace(time=t), np.full(len(t), 120.), np.ones(len(t)), {})] + measurements
    result = search_national([index], Terrain(constant_m=0), [spurious] + events, measurements,
                             time_range_s=times, output_dir=tmp_path / "subsets", bounds=bounds,
                             budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000),
                             scoring={"mode": "robust_ridge", "recording_start_window_s": [origin, origin], "time_sweep_s": 0},
                             filters={"association": "subsets", "min_events": 2, "max_events": 2})
    assert result["ranked"]
    best = result["ranked"][0]
    assert best["event_indices"] == [1, 2] and best["unmatched_event_ids"] == ["noise-proposal"]
    assert best["recording_start_time_s"] == origin
    assert best["x"] == 0 and best["y"] == 1900000


@pytest.mark.parametrize("count", [3, 4, 6])
def test_default_robust_driver_uses_all_groups_and_refines_them(tmp_path, count):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path, count=count, receiver_offset=(250, 250))
    for i, event in enumerate(events):
        event["event_id"] = f"supported-{i}"
    spurious = dict(events[0], event_id="noise-proposal", start_s=20., end_s=40., cpa_receive_s=30.)
    t = np.linspace(20, 40, 41)
    measurements = [(SimpleNamespace(time=t), np.full(len(t), 120.), np.ones(len(t)), {})] + measurements
    result = search_national([index], Terrain(constant_m=0), [spurious] + events, measurements,
                             time_range_s=times, output_dir=tmp_path / "all-events", bounds=bounds,
                             budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=250, refine_finalists=1),
                             scoring={"mode": "robust_ridge", "recording_start_window_s": [origin, origin], "time_sweep_s": 0})
    assert result["status"] == "complete" and result["all_event_groups_considered"]
    best = result["ranked"][0]
    assert best["event_indices"] == list(range(1, count+1))
    assert best["unmatched_event_ids"] == ["noise-proposal"]
    assert len(best["event_diagnostics"]) == count
    assert best["recording_start_time_s"] == origin
    assert best["score"] > result["coarse_ranked"][0]["score"]
    # This is an all-group/refinement regression, not a precision guarantee:
    # coarse finalist selection can miss a better mode between grid points.
    assert best["x"] % 1000 != 0 or best["y"] % 1000 != 0


def test_explicit_smaller_event_cap_is_partial(tmp_path):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path, count=4)
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
                             output_dir=tmp_path / "capped", bounds=bounds,
                             budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000),
                             scoring={"mode": "robust_ridge", "time_origin": origin, "time_sweep_s": 0},
                             filters={"max_events": 3})
    assert result["status"] == "partial" and not result["all_event_groups_considered"]
    assert result["association_event_limit"] == 3 and result["event_limit_reason"]


def test_sixth_event_changes_the_joint_score(tmp_path):
    _, tracks, events, measurements, bounds, _, origin = scenario(tmp_path, count=6, receiver_offset=(250, 250))
    points = tile_points((1, 7601, 2, 7602), 250, bounds, Terrain(constant_m=0), "EPSG:5070")
    budget = SearchBudget()
    settings = {"mode": "robust_ridge", "time_origin": origin, "time_sweep_s": 0}
    clean, _ = _score(points, tracks, events, measurements, budget, settings, {})
    spec, ridge, weight, fit = measurements[-1]
    changed = measurements[:-1] + [(spec, ridge + .4 * (-1.) ** np.arange(len(ridge)), weight, fit)]
    perturbed, _ = _score(points, tracks, events, changed, budget, settings, {})
    assert clean and perturbed
    assert clean[0]["event_indices"] == perturbed[0]["event_indices"] == list(range(6))
    assert perturbed[0]["score"] < clean[0]["score"] - 1e-4
    assert perturbed[0]["event_diagnostics"][-1]["rmse_hz"] > clean[0]["event_diagnostics"][-1]["rmse_hz"] + .05


def test_uncertain_window_keeps_valid_shared_clock_beyond_cpa_anchor(tmp_path):
    _, tracks, events, measurements, bounds, _, origin = scenario(tmp_path, receiver_offset=(250, 250))
    for event in events:
        event["quality"] = {"cpa_tolerance_s": 20.}
    events[0]["cpa_receive_s"] += 12
    points = tile_points((1, 7601, 2, 7602), 250, bounds, Terrain(constant_m=0), "EPSG:5070")
    ranked, _ = _score(points, tracks, events, measurements, SearchBudget(),
                       {"mode": "robust_ridge", "time_sweep_s": 5., "time_step_s": .5}, {},
                       start_window=(origin-30, origin+30))
    assert ranked
    assert abs(ranked[0]["recording_start_time_s"]-origin) < .02
    assert ranked[0]["event_indices"] == [0, 1]


def test_narrow_trusted_window_near_sweep_edge_is_not_shrunk_again(tmp_path):
    _, tracks, events, measurements, bounds, _, origin = scenario(tmp_path, receiver_offset=(250, 250))
    points = tile_points((1, 7601, 2, 7602), 250, bounds, Terrain(constant_m=0), "EPSG:5070")
    observer = ecef(points.lat.iloc[0], points.lon.iloc[0], 0)
    shifted = []
    for track, (spec, _, weight, fit) in zip(tracks, measurements):
        factor, _, _ = track.acoustic(origin+7.05+spec.time, observer)
        shifted.append((spec, 120*factor, weight, fit))
    window = (origin+7., origin+7.1)
    ranked, _ = _score(points, tracks, events, shifted, SearchBudget(),
                       {"mode": "robust_ridge", "time_sweep_s": 5., "time_step_s": .5}, {}, start_window=window)
    assert ranked
    assert window[0] <= ranked[0]["recording_start_time_s"] <= window[1]
    assert ranked[0]["event_indices"] == [0, 1]


def test_finite_retention_bound_matches_untiled_and_recovers_missing_ledger(tmp_path):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    terrain = Terrain(constant_m=0)
    settings = {"mode": "ridge", "time_origin": origin, "time_sweep_s": 0}
    points = pd.concat([tile_points(cells, 1000, bounds, terrain, "EPSG:5070")
                        for _, cells in grid_tiles(bounds, 1000, 2)], ignore_index=True)
    points["point_id"] = np.arange(len(points))
    all_rows, _ = _score(points, list(index.query(bounds, times)), events, measurements,
                         SearchBudget(top_k=10000), settings, {})
    assert len(all_rows) > 1
    budget = SearchBudget(spacing_m=1000, tile_cells=2, top_k=1, refine_spacing_m=1000)
    kwargs = dict(time_range_s=times, output_dir=tmp_path / "finite", bounds=bounds, budget=budget, scoring=settings)
    first = search_national([index], terrain, events, measurements, **kwargs)
    finite = first["finite_search_evidence"]
    assert finite["complete"] and finite["pruning_accounted_for"]
    assert finite["evaluated_modes"] == len(all_rows)
    assert finite["discarded_count"] == len(all_rows)-1
    assert finite["best_discarded_score"] == pytest.approx(all_rows[1]["score"], abs=1e-8)
    assert first["core_assessed_mode_ids"] == [first["ranked"][0]["mode_id"]]
    # Completed tile JSON alone is not enough to reconstruct discarded modes.
    (tmp_path / "finite/retention.sqlite").unlink()
    repaired = search_national([index], terrain, events, measurements, **kwargs)
    assert repaired["tiles_resumed"] == 0
    assert repaired["finite_search_evidence"]["discarded_count"] == finite["discarded_count"]
    assert repaired["core_assessed_mode_ids"] == first["core_assessed_mode_ids"]


def test_successful_best_row_with_unknown_trials_has_no_optimistic_finite_bound(tmp_path, monkeypatch):
    from dopplergeist import tiled_search
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    original = tiled_search.score_candidate

    def incomplete(*args, **kwargs):
        result = original(*args, **kwargs)
        result["scoring_assessment"] = {"complete": False, "evaluated_trials": 1, "rejected_trials": 0,
                                        "unknown_trials": 1, "reasons": ["test_missing_support"]}
        return result

    monkeypatch.setattr(tiled_search, "score_candidate", incomplete)
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
                             output_dir=tmp_path / "unknown", bounds=bounds,
                             budget=SearchBudget(spacing_m=1000, tile_cells=4, top_k=1, refine_spacing_m=1000),
                             scoring={"mode": "robust_ridge", "time_origin": origin, "time_sweep_s": 0})
    assert result["ranked"] and result["status"] == "partial"
    assert not result["model_support_complete"]
    finite = result["finite_search_evidence"]
    assert not finite["complete"] and finite["unclassified_score_candidates"] > 0
    assert finite["best_discarded_score"] is None and finite["discarded_count"] > 0
    assert result["core_assessed_mode_ids"] == []


def test_evaluated_acoustic_rejection_is_distinct_from_unknown_support(tmp_path, monkeypatch):
    from dopplergeist import tiled_search
    _, tracks, events, measurements, bounds, _, origin = scenario(tmp_path)
    original = tiled_search.score_candidate

    def rejected(*args, **kwargs):
        result = original(*args, **kwargs)
        result.update(score=-np.inf, scoring_assessment={"complete": True, "evaluated_trials": 0,
                      "rejected_trials": 1, "unknown_trials": 0, "reasons": ["test_admissible_rejection"]})
        return result

    monkeypatch.setattr(tiled_search, "score_candidate", rejected)
    points = tile_points((0, 1900, 1, 1901), 1000, bounds, Terrain(constant_m=0), "EPSG:5070")
    ranked, counts = _score(points, tracks, events, measurements, SearchBudget(),
                            {"mode": "robust_ridge", "time_origin": origin, "time_sweep_s": 0}, {})
    assert not ranked and counts["evaluated_rejections"] == counts["candidates"] > 0
    assert counts["unclassified_score_candidates"] == 0


