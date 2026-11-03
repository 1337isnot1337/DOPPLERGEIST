"""Clock partition regression on an overloaded original-audio full-day cell."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from dopplergeist.data_access import CachedTerrain, FlightIndex, content_hash
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import association_candidates, prepare_events
from dopplergeist.search import cpa_table
from dopplergeist.tiled_search import (SearchBudget, _association_clock_window, _expanded_bounds,
    _split_tile_cells, _tile_anchor_window, _tracks_for_points, grid_tiles, tile_points)


def test_full_day_cell_clock_partitions_preserve_associations():
    job, cache = (os.environ.get(name) for name in ("DOPPLERGEIST_REAL_JOB_ROOT", "DOPPLERGEIST_REAL_CACHE_ROOT"))
    if not job or not cache:
        pytest.skip("set the real job and cache roots")
    job, cache = Path(job), Path(cache)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    events, _ = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    budget = SearchBudget(**config["budget"])
    cells = dict(grid_tiles(config["bounds"], budget.spacing_m, budget.tile_cells, config["crs"]))["-33_51"]
    for choice in (1, 2, 0, 1, 1):
        cells = _split_tile_cells(cells)[choice]
    terrain = CachedTerrain(cache / "terrain", offline=False)
    points = tile_points(cells, budget.spacing_m, config["bounds"], terrain, config["crs"])
    assert len(points) == 1
    indexes = [FlightIndex(cache / "flights" / day / "staging-0/all-types-v2-543f483cee75.sqlite")
               for day in ("2026-09-08", "2026-09-09")]
    parameters = dict(config["scoring"])
    window = parameters.pop("recording_start_window_s")
    radius = max(event["slant_range_m"][1] for event in events)
    tracks, points = _tracks_for_points(indexes, _expanded_bounds(cells, budget.spacing_m, radius, config["crs"]),
                                       config["time_range_s"], budget, points, terrain, radius, parameters.get("c", 343.))
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    tables, unsupported = [], 0
    for track in tracks:
        try:
            if not track.outside_observer_radius(observers, radius, parameters.get("c", 343.)):
                table = cpa_table([track], points, radius, parameters.get("c", 343.), budget.cpa_step_s)
                if len(table):
                    tables.append(table)
        except AcousticSupportError:
            unsupported += 1
    table = pd.concat(tables, ignore_index=True)
    center, tolerance = _association_clock_window(window, parameters.get("time_sweep_s", 5.))
    filters = config["filters"]
    kwargs = dict(offset_tolerance_s=filters.get("offset_tolerance_s", 5.), time_origin=center,
                  time_tolerance_s=tolerance, min_events=filters.get("min_events", 1),
                  max_events=filters.get("max_events") or len(events))
    with pytest.raises(ValueError, match="Association candidate budget exceeded"):
        association_candidates(table, events, max_candidates=budget.max_candidates_per_tile, **kwargs)
    baseline, _ = association_candidates(table, events, max_candidates=100000, **kwargs)
    pieces = []
    for i in range(8):
        tile = "-33_51~1~2~0~1~1" + "".join(f"~t{(i >> shift) & 1}" for shift in (2, 1, 0))
        anchor = _tile_anchor_window(tile, window, parameters, filters, events)
        result, _ = association_candidates(table, events, max_candidates=budget.max_candidates_per_tile,
                                           anchor_window=anchor, **kwargs)
        pieces.extend(result)
    assert sorted(content_hash(item) for item in pieces) == sorted(content_hash(item) for item in baseline)
    assert unsupported > 0
    print(f"real cell: {len(baseline)} associations preserved; {unsupported} unsupported tracks")


def test_real_clock_partition_restart_and_scores(tmp_path, monkeypatch):
    """Inject a capacity failure into a one-cell real-data engineering replay."""
    import shutil
    import dopplergeist.tiled_search as tiled

    job, cache, reference, terrain_path, index_path = (os.environ.get(name) for name in (
        "DOPPLERGEIST_REAL_JOB_ROOT", "DOPPLERGEIST_REAL_CACHE_ROOT",
        "DOPPLERGEIST_REAL_REFERENCE_ROOT", "DOPPLERGEIST_REAL_ENGINEERING_TERRAIN",
        "DOPPLERGEIST_REAL_DEVELOPMENT_INDEX"))
    if not all((job, cache, reference, terrain_path, index_path)):
        pytest.skip("set the real job, cache, reference and engineering terrain paths")
    job, cache, reference = Path(job), Path(cache), Path(reference)
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    # Two observed groups and a narrow known engineering clock keep this replay
    # small; the actual full-day upload run uses all detected groups and no clock.
    events, measurements = events[6:8], measurements[6:8]
    clock = json.loads((reference / "results/reference-local/ranked.json").read_text())[0]["recording_start_time_s"]
    index = FlightIndex(index_path)
    lon, lat = -73.53984955811066, 40.87662017144848
    bounds = (lon-.0001, lat-.0001, lon+.0001, lat+.0001)
    settings = {"mode": "robust_ridge", "time_sweep_s": 0.,
                "recording_start_window_s": [clock-10, clock+10]}
    budget = SearchBudget(spacing_m=2000, tile_cells=1, top_k=5, refine_spacing_m=2000)

    def run(name, progress=None):
        terrain = CachedTerrain(terrain_path, offline=True, adopt_existing=True)
        return tiled.search_national([index], terrain, events, measurements,
            time_range_s=index.report["coverage"]["time_range_s"], output_dir=tmp_path / name, bounds=bounds,
            budget=budget, scoring=settings, workers=1, search_progress=progress)

    baseline = run("baseline")
    original = tiled._score
    def force_split(*args, **kwargs):
        if kwargs.get("anchor_window") is None:
            raise ValueError("Association candidate budget exceeded; search is incomplete")
        return original(*args, **kwargs)
    progress = []
    with monkeypatch.context() as patch:
        patch.setattr(tiled, "_score", force_split)
        partitioned = run("partitioned", progress.append)
    keys = ("score", "lat", "lon", "flight_ids", "recording_start_time_s", "event_ids")
    project = lambda report: [{key: row.get(key) for key in keys} for row in report["ranked"]]
    assert baseline["ranked"] and project(partitioned) == project(baseline)
    assert baseline["grid_points_searched"] == partitioned["grid_points_searched"] == 1
    assert not partitioned["tile_failures"] and partitioned["tiles_completed"] == baseline["tiles_completed"] + 1
    assert progress == sorted(progress) and progress[-1] == 1.
    assert partitioned["finite_search_evidence"]["pruning_accounted_for"]
    resumed = run("partitioned")
    assert resumed["tiles_resumed"] == partitioned["tiles_completed"] and project(resumed) == project(partitioned)
    assert resumed["finite_search_evidence"] == partitioned["finite_search_evidence"]
    shutil.copytree(tmp_path / "partitioned", tmp_path / "corrupt")
    marker = next((tmp_path / "corrupt").glob("split-*.json"))
    record = json.loads(marker.read_text())
    record["children"].pop()
    marker.write_text(json.dumps(record))
    assert any("Corrupt tile subdivision checkpoint" in failure["reason"]
               for failure in run("corrupt")["tile_failures"])
