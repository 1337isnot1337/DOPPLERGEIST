"""Optional retry regression on an actual overloaded full-day grid cell."""
from dataclasses import replace
import json
import os
from pathlib import Path
import time

import pytest

from dopplergeist.data_access import CachedTerrain, DataUnavailable, FlightIndex
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import prepare_events
from dopplergeist.tiled_search import (SearchBudget, _expanded_bounds, _score, _split_tile_cells,
                                       _tile_coordinates, _tracks, _tracks_for_points, grid_tiles)


def test_real_overloaded_cell_preserves_scores_and_support(tmp_path):
    job, cache = (os.environ.get(name) for name in ("DOPPLERGEIST_REAL_JOB_ROOT", "DOPPLERGEIST_REAL_CACHE_ROOT"))
    if not job or not cache:
        pytest.skip("set the real job and cache roots")
    job, cache = Path(job), Path(cache)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    budget = SearchBudget(**config["budget"])
    cells = dict(grid_tiles(config["bounds"], budget.spacing_m, budget.tile_cells, config["crs"]))["-32_51"]
    for choice in (1, 0, 0, 0, 0):
        cells = _split_tile_cells(cells)[choice]
    points = _tile_coordinates(cells, budget.spacing_m, config["bounds"], config["crs"])
    assert len(points) == 1
    terrain = CachedTerrain(cache / "terrain", offline=False)
    indexes = [FlightIndex(cache / "flights" / day / "staging-0/all-types-v2-543f483cee75.sqlite")
               for day in ("2026-09-08", "2026-09-09")]
    radius = max(event["slant_range_m"][1] for event in events)
    bounds = _expanded_bounds(cells, budget.spacing_m, radius, config["crs"])
    with pytest.raises(DataUnavailable, match="Tile track/sample memory budget exceeded"):
        _tracks(indexes, bounds, config["time_range_s"], budget)
    started = time.process_time()
    filtered, points = _tracks_for_points(indexes, bounds, config["time_range_s"], budget,
                                          points, terrain, radius, config["scoring"].get("c", 343.))
    retry_cpu = time.process_time() - started
    assert len(filtered) <= budget.max_tracks_per_tile
    assert sum(len(track.time) for track in filtered) <= budget.max_track_samples_per_tile
    wide = replace(budget, max_tracks_per_tile=10000, max_track_samples_per_tile=2000000)
    complete = _tracks(indexes, bounds, config["time_range_s"], wide)
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    expected, unsupported = [], 0
    for track in complete:
        try:
            distant = track.outside_observer_radius(observers, radius, config["scoring"].get("c", 343.))
        except AcousticSupportError:
            unsupported += 1
            distant = False
        if not distant:
            expected.append(track.id)
    assert [track.id for track in filtered] == expected and len(filtered) < len(complete)
    assert unsupported > 0
    parameters = dict(config["scoring"])
    window = parameters.pop("recording_start_window_s", None)
    kind = "matched_group_support_minus_normalized_residual"
    results = []
    for name, tracks in (("complete", complete), ("filtered", filtered)):
        ledger = RetentionLedger(tmp_path / f"{name}.sqlite", "real-distance-sieve", kind)
        rows, counts = _score(points, tracks, events, measurements, budget, parameters, config["filters"],
                              window, ledger=ledger, stage="coarse:real")
        results.append((rows, counts, ledger.checksum("coarse:real")))
    assert json.dumps(results[0], sort_keys=True, allow_nan=True) == json.dumps(results[1], sort_keys=True, allow_nan=True)
    print(f"real cell: {len(complete)} queried, {len(filtered)} retained, {unsupported} unsupported, retry CPU {retry_cpu:.2f}s")
