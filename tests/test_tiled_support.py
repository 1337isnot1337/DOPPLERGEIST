import json

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from dopplergeist import tiled_search
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, Track
from dopplergeist.terrain import Terrain
from dopplergeist.tiled_search import SearchBudget, _score, search_national, tile_points
from test_tiled_search import compact, scenario


def with_bad_copy(tmp_path):
    index, tracks, events, measurements, bounds, times, origin = scenario(tmp_path)
    first = tracks[0]
    bad = Track("unsupported-source", first.time, first.lat, first.lon, first.altitude)
    frames = [pd.DataFrame({"flight_id": t.id, "time_s": t.time, "lat": t.lat, "lon": t.lon,
                            "alt_m": t.altitude, "altitude_basis": "ellipsoidal"}) for t in tracks + [bad]]
    mixed = FlightIndex.build(tmp_path / "mixed.sqlite", frames, sources=[], coverage=index.report["coverage"])
    return index, mixed, tracks, bad, events, measurements, bounds, times, origin


def test_typed_legacy_candidate_failure_preserves_clean_rows_and_resume_diagnostics(tmp_path, monkeypatch):
    index, mixed, _, _, events, measurements, bounds, times, origin = with_bad_copy(tmp_path)
    settings = {"mode": "ridge", "time_origin": origin, "time_sweep_s": 0}
    budget = SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000)
    kwargs = dict(time_range_s=times, bounds=bounds, budget=budget, scoring=settings)
    clean = search_national([index], Terrain(constant_m=0), events, measurements,
                            output_dir=tmp_path / "clean", **kwargs)
    acoustic = Track.acoustic

    def guarded(self, *args, **kwargs):
        if self.id == "unsupported-source":
            raise AcousticSupportError(self.id, "non_monotone_arrival")
        return acoustic(self, *args, **kwargs)

    monkeypatch.setattr(Track, "acoustic", guarded)
    output = tmp_path / "mixed-search"
    result = search_national([mixed], Terrain(constant_m=0), events, measurements, output_dir=output, **kwargs)
    assert compact(result["ranked"]) == compact(clean["ranked"])
    assert result["tiles_completed"] == result["tiles_total"] and not result["tile_failures"]
    assert result["data_scope_complete"] and not result["model_support_complete"]
    assert result["status"] == "partial" and not result["finite_search_evidence"]["complete"]
    assert result["finite_search_evidence"]["best_discarded_score"] is None
    assert result["model_support"]["unclassified_score_candidates"] > 0
    assert result["model_support"]["unreported_trial_envelopes"] > 0
    diagnostics = [json.loads(p.read_text()) for p in (output / "support").glob("*.json")]
    failed = [r for d in diagnostics for r in d["unclassified_candidate_assessments"]]
    assert failed and all(r["support_failure"] == {"track_id": "unsupported-source", "reason": "non_monotone_arrival"}
                          for r in failed)
    assert all("unsupported-source" in r["flight_ids"] for r in failed)
    assert any(t.id == "unsupported-source" for t in mixed.query(bounds, times)), "Source is retained unchanged"
    replay = search_national([mixed], Terrain(constant_m=0), events, measurements, output_dir=output, **kwargs)
    assert replay["tiles_resumed"] == replay["tiles_total"]
    assert replay["model_support"] == result["model_support"]
    assert compact(replay["ranked"]) == compact(result["ranked"])


def test_cpa_support_failure_records_conservative_whole_track_loss_and_keeps_other_tracks(tmp_path, monkeypatch):
    _, _, tracks, bad, events, measurements, bounds, _, origin = with_bad_copy(tmp_path)
    points = tile_points((0, 1900, 2, 1901), 1000, bounds, Terrain(constant_m=0), "EPSG:5070")
    settings = {"mode": "ridge", "time_origin": origin, "time_sweep_s": 0}
    budget = SearchBudget(max_cpa_rows=200)
    expected, expected_counts = _score(points, tracks, events, measurements, budget, settings, {})
    original = tiled_search.cpa_table
    calls = 0

    def guarded(selected, *args, **kwargs):
        nonlocal calls
        if selected[0].id == bad.id:
            calls += 1
            if calls > 1:
                raise AcousticSupportError(bad.id, "non_monotone_arrival")
        return original(selected, *args, **kwargs)

    monkeypatch.setattr(tiled_search, "cpa_table", guarded)
    ranked, counts = _score(points, [bad]+tracks, events, measurements, budget, settings, {})
    assert compact(ranked) == compact(expected) and ranked
    assert counts["cpa_rows"] == expected_counts["cpa_rows"], "Partial rows from failed source are not counted as covered"
    failure, = counts["unsupported_cpa_tracks"]
    assert failure["track_id"] == bad.id and failure["reason"] == "non_monotone_arrival"
    assert failure["emission_time_range_s"] == [bad.time[0], bad.time[-1]]
    assert failure["receiver_point_count"] == len(points)
    assert failure["coverage_envelope"] == "whole_track_whole_stage_conservative"
    empty, counts = _score(points, [bad], events, measurements, budget, settings, {})
    assert not empty and len(counts["unsupported_cpa_tracks"]) == 1


def test_all_unsupported_cpa_sources_return_empty_partial_search_with_diagnostics(tmp_path, monkeypatch):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)

    def unsupported(tracks, *args, **kwargs):
        raise AcousticSupportError(tracks[0].id, "non_monotone_arrival")

    monkeypatch.setattr(tiled_search, "cpa_table", unsupported)
    output = tmp_path / "all-unsupported"
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
        output_dir=output, bounds=bounds, budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000),
        scoring={"mode": "ridge", "time_origin": origin, "time_sweep_s": 0})
    assert not result["ranked"] and result["status"] == "partial"
    assert result["tiles_completed"] == result["tiles_total"] and not result["tile_failures"]
    assert result["data_scope_complete"] and not result["model_support_complete"]
    assert result["model_support"]["unsupported_cpa_track_evaluations"] > 0
    assert not result["finite_search_evidence"]["complete"]
    assert list((output / "support").glob("coarse-*.json"))


def test_actual_classified_robust_scorer_supplies_finite_core_ids(tmp_path):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
        output_dir=tmp_path / "classified", bounds=bounds,
        budget=SearchBudget(spacing_m=1000, tile_cells=4, top_k=2, refine_spacing_m=1000),
        scoring={"mode": "robust_ridge", "recording_start_window_s": [origin, origin], "time_sweep_s": 0})
    assert result["ranked"] and result["status"] == "complete" and result["model_support_complete"]
    assert result["finite_search_evidence"]["complete"]
    assert result["core_assessed_mode_ids"] == [r["mode_id"] for r in result["ranked"]]
    assert result["model_support"]["evaluated_trials"] > 0
    assert result["model_support"]["unknown_trials"] == result["model_support"]["unreported_trial_envelopes"] == 0


def test_real_interior_supersonic_track_is_partial_before_cpa_filters_and_preserves_clean_rows(tmp_path):
    index, tracks, events, measurements, bounds, times, origin = scenario(tmp_path)
    inverse = Transformer.from_crs("EPSG:5070", "EPSG:4326", always_xy=True)
    lon, lat = inverse.transform([-1000., 0., 1000.], [1900000.]*3)
    # Measured zero knot motion hides an interior Hermite speed > 700 m/s.
    bad = pd.DataFrame({"flight_id": "actual-invalid-observations", "time_s": origin+np.array([149., 151., 153.]),
                        "lat": lat, "lon": lon, "alt_m": 1200., "altitude_basis": "ellipsoidal",
                        "east_mps": 0., "north_mps": 0., "up_mps": 0.})
    frames = [pd.DataFrame({"flight_id": t.id, "time_s": t.time, "lat": t.lat, "lon": t.lon,
                            "alt_m": t.altitude, "altitude_basis": "ellipsoidal"}) for t in tracks]
    mixed = FlightIndex.build(tmp_path / "actual-mixed.sqlite", frames+[bad], sources=[], coverage=index.report["coverage"])
    raw = next(t for t in mixed.query(bounds, times) if t.id == "actual-invalid-observations")
    assert np.max(np.linalg.norm(raw.speed_vector(raw.time), axis=1)) == 0
    assert np.linalg.norm(raw.speed_vector(origin+150)) > 700
    kwargs = dict(time_range_s=times, bounds=bounds,
                  budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000),
                  scoring={"mode": "ridge", "time_origin": origin, "time_sweep_s": 0})
    clean = search_national([index], Terrain(constant_m=0), events, measurements,
                            output_dir=tmp_path / "actual-clean", **kwargs)
    output = tmp_path / "actual-mixed"
    result = search_national([mixed], Terrain(constant_m=0), events, measurements, output_dir=output, **kwargs)
    assert compact(result["ranked"]) == compact(clean["ranked"])
    assert result["status"] == "partial" and not result["model_support_complete"]
    assert result["data_scope_complete"] and not result["tile_failures"]
    assert result["model_support"]["unsupported_cpa_track_evaluations"] > 0
    assert not result["finite_search_evidence"]["complete"]
    failures = [f for p in (output / "support").glob("*.json")
                for f in json.loads(p.read_text())["unsupported_cpa_tracks"]]
    assert failures and all(f["track_id"] == raw.id and f["reason"] == "non_subsonic_motion" for f in failures)
    assert all(f["emission_time_range_s"] == [raw.time[0], raw.time[-1]] for f in failures)
    assert all(f["reported_intervals"]["emission_intervals_s"] for f in failures)
    assert all("receive_intervals_s" not in f["reported_intervals"] for f in failures)


def test_cpa_programming_error_is_not_relabelled_as_source_support(tmp_path, monkeypatch):
    _, tracks, events, measurements, bounds, _, origin = scenario(tmp_path)
    points = tile_points((0, 1900, 1, 1901), 1000, bounds, Terrain(constant_m=0), "EPSG:5070")

    def broken(*args, **kwargs):
        raise ValueError("configuration defect")

    monkeypatch.setattr(tiled_search, "cpa_table", broken)
    with pytest.raises(ValueError, match="configuration defect"):
        _score(points, tracks, events, measurements, SearchBudget(), {"mode": "ridge", "time_origin": origin}, {})


def test_refinement_support_loss_is_persisted_and_cannot_be_complete(tmp_path, monkeypatch):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    original = tiled_search._score

    def fine_failure(*args, **kwargs):
        rows, counts = original(*args, **kwargs)
        if kwargs.get("stage", "").startswith("fine:"):
            counts["unsupported_cpa_tracks"] = [{"track_id": "unknown-fine-competitor", "reason": "non_monotone_arrival"}]
        return rows, counts

    monkeypatch.setattr(tiled_search, "_score", fine_failure)
    output = tmp_path / "fine"
    result = search_national([index], Terrain(constant_m=0), events, measurements, time_range_s=times,
        output_dir=output, bounds=bounds, budget=SearchBudget(spacing_m=1000, tile_cells=4,
        refine_spacing_m=500, refine_finalists=1), scoring={"mode": "ridge", "time_origin": origin, "time_sweep_s": 0})
    assert result["ranked"] and result["refinement_points_searched"] > 0
    assert result["status"] == "partial" and not result["model_support_complete"]
    assert result["model_support"]["unsupported_cpa_track_evaluations"] > 0
    assert list((output / "support").glob("fine-*.json"))
    assert result["finite_search_evidence"]["best_discarded_score"] is None
