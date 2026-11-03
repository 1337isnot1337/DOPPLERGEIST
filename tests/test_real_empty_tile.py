"""Optional regression for an empty boundary tile in the real full-day run."""
import json
import os
from pathlib import Path

import pytest

from dopplergeist.data_access import DataUnavailable, FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.parallel_tiles import initialize_tile_worker, score_tile
from dopplergeist.tiled_search import SearchBudget, _expanded_bounds, _tile_coordinates, _tracks, grid_tiles


def test_real_empty_boundary_tile_does_not_load_overloaded_tracks(tmp_path):
    job = os.environ.get("DOPPLERGEIST_REAL_JOB_ROOT")
    cache = os.environ.get("DOPPLERGEIST_REAL_CACHE_ROOT")
    if not job or not cache:
        pytest.skip("set the real job and cache roots")
    job, cache = Path(job), Path(cache)
    manifest = json.loads((job / "search/manifest.json").read_text())
    config = manifest["configuration"]
    budget = SearchBudget(**config["budget"])
    cells = dict(grid_tiles(config["bounds"], budget.spacing_m, budget.tile_cells, config["crs"]))["-19_51"]
    assert len(_tile_coordinates(cells, budget.spacing_m, config["bounds"], config["crs"])) == 0
    paths = [cache / "flights" / day / "staging-0/all-types-v2-543f483cee75.sqlite"
             for day in ("2026-09-08", "2026-09-09")]
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    radius = max(event["slant_range_m"][1] for event in events)
    with pytest.raises(DataUnavailable, match="Tile track/sample memory budget exceeded"):
        _tracks([FlightIndex(path) for path in paths],
                _expanded_bounds(cells, budget.spacing_m, radius, config["crs"]), config["time_range_s"], budget)
    parameters = dict(config["scoring"])
    window = parameters.pop("recording_start_window_s", None)
    initialize_tile_worker(paths, cache / "terrain", {"offline": True}, events, measurements,
                           config["bounds"], config["time_range_s"], budget, parameters, config["filters"],
                           window, config["crs"], tmp_path, manifest["run_hash"],
                           "matched_group_support_minus_normalized_residual")
    payload, _ = score_tile("coarse:-19_51", cells)
    assert payload["grid_points"] == payload["tracks"] == 0
    assert payload["ranked"] == []
    assert payload["retention_checksum"]
