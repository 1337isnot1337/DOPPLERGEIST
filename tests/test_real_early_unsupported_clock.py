"""Optional early-track bounds using archived real recording and aircraft."""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.geometry import Track, ecef
from dopplergeist.search import _CPA_DTYPE, _PreparedCPATrack, _ordered_cpa_rows, filter_association_event
from dopplergeist.terrain import Terrain
from dopplergeist.tiled_search import (SearchBudget, _association_clock_window, _event_receive_time_bounds, _expanded_bounds,
                                       _score, _tracks_for_points, tile_points)


def test_real_early_track_and_nonempty_tile(tmp_path, monkeypatch):
    names = ("DOPPLERGEIST_REAL_EARLY_JOB", "DOPPLERGEIST_REAL_EARLY_INDEX",
             "DOPPLERGEIST_REAL_EARLY_DEM", "DOPPLERGEIST_REAL_EARLY_GEOID")
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip("set real completed job, aircraft index, DEM and geoid paths")
    job, index_path, dem, geoid = map(Path, values)
    cfg = json.loads((job / "search/manifest.json").read_text())["configuration"]
    raw = json.loads((job / "discovery/discovery.json").read_text())["events"]
    params = dict(cfg["scoring"])
    window = params.pop("recording_start_window_s")
    filters = cfg["filters"]
    radius = max(event["slant_range_m"][1] for event in cfg["events"])
    events, measurements = prepare_events(raw, c=params["c"], max_distance_m=radius)
    assert events == cfg["events"]
    budget = SearchBudget(**cfg["budget"])
    index, terrain = FlightIndex(index_path), Terrain([dem], geoid_path=geoid)
    spec = importlib.util.spec_from_file_location("verify_early_clock",
        Path(__file__).parents[1] / "scripts/verify_upload_http.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    first_event, _ = _event_receive_time_bounds(events, params, filters, window)
    early_stages = []
    try:
        for f in sorted((job / "search/support").glob("coarse-*.json")):
            if f.stat().st_size > 1048576:
                continue
            support = json.loads(f.read_text())
            selected = [x for x in support.get("unsupported_cpa_tracks", [])
                        if x.get("emission_time_range_s") and
                        x["emission_time_range_s"][1] + radius / params["c"] + 1 < first_event]
            if not selected:
                continue
            tile_name = support["stage"].removeprefix("coarse:")
            payload = json.loads((job / "search" / f"tile-{tile_name}.json").read_text())["payload"]
            points = tile_points(payload["cells"], budget.spacing_m, cfg["bounds"], terrain, cfg["crs"])
            tracks = list(index.lookup([x["track_id"] for x in selected]))
            assert tracks
            rows, counts = _score(points, tracks, events, measurements, budget, params, filters, window)
            assert not rows and not counts["unsupported_cpa_tracks"]
            for item in counts["clock_excluded_unsupported_tracks"]:
                assert item["exclusion_kind"] == "before_events"
                assert verifier.valid_clock_exclusion(item, cfg)
                assert not verifier.valid_clock_exclusion({**item, "latest_possible_receive_s": item["earliest_event_receive_s"]}, cfg)
                assert not verifier.valid_clock_exclusion({**item, "earliest_event_receive_s": item["earliest_event_receive_s"] + 1}, cfg)
                assert not verifier.valid_clock_exclusion({**item, "latest_possible_receive_s": item["latest_emission_s"]}, cfg)
            assert len(counts["clock_excluded_unsupported_tracks"]) == len(tracks)
            # Diagnostic only: use the unchanged CPA proposer with its whole-
            # track guard bypassed to check the existing event filter. This is
            # not used as physical support or a location claim.
            observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
            point_ids = points.point_id.to_numpy(dtype=int)
            center, tolerance = _association_clock_window(window, params.get("time_sweep_s", 5.0))
            for track in tracks:
                with monkeypatch.context() as patch:
                    patch.setattr(Track, "validate_motion_support", lambda self, c: None)
                    raw_rows = _ordered_cpa_rows(_PreparedCPATrack(track, params["c"], budget.cpa_step_s).raw_rows(
                        observers, point_ids, radius), budget.cpa_step_s)
                if raw_rows:
                    table = pd.DataFrame(np.array(raw_rows, dtype=_CPA_DTYPE))
                    assert all(filter_association_event(table, event, filters.get("offset_tolerance_s", 5),
                                                        center, tolerance).empty for event in events)
            # Moving the same real recording clock across the boundary must
            # retain the unsupported source, with and without silence enabled.
            item = counts["clock_excluded_unsupported_tracks"][0]
            shift = item["latest_possible_receive_s"] - item["earliest_event_receive_s"]
            overlap = [v + shift - 1 for v in window]
            _, uncertain = _score(points, tracks, events, measurements, budget, params, filters, overlap)
            assert any(x["track_id"] == tracks[0].id for x in uncertain["unsupported_cpa_tracks"])
            _, silent = _score(points, tracks, events, measurements, budget, params,
                               {**filters, "silence": {"edge_margin_s": 60}}, window)
            assert any(x["track_id"] == tracks[0].id for x in silent["unsupported_cpa_tracks"])
            early_stages.append((payload, points))
        assert len(early_stages) == 2
        payload, points = max(early_stages, key=lambda pair: len(pair[0]["ranked"]))
        assert payload["ranked"]
        tracks, points = _tracks_for_points([index], _expanded_bounds(payload["cells"], budget.spacing_m, radius, cfg["crs"]),
                                            cfg["time_range_s"], budget, points, terrain, radius, params["c"])
        import dopplergeist.tiled_search as tiled
        with monkeypatch.context() as patch:
            patch.setattr(tiled, "_event_receive_time_bounds", lambda *args: None)
            old_rows, old_counts = _score(points, tracks, events, measurements, budget, params, filters, window)
        rows, counts = _score(points, tracks, events, measurements, budget, params, filters, window)
        assert rows and rows == old_rows
        assert counts["cpa_rows"] == old_counts["cpa_rows"]
        assert counts["candidates"] == old_counts["candidates"]
        assert counts["unclassified_candidate_assessments"] == old_counts["unclassified_candidate_assessments"]
        assert len(counts["clock_excluded_unsupported_tracks"]) > 0
        assert len(old_counts["unsupported_cpa_tracks"]) == len(counts["unsupported_cpa_tracks"]) + len(counts["clock_excluded_unsupported_tracks"])
    finally:
        for raster in terrain.rasters + terrain.geoid.rasters:
            raster.close()
