"""Conservative spline distance filtering on actual unsupported flight tracks."""
from dataclasses import replace
import json
import os
from pathlib import Path

import numpy as np
import pytest

from dopplergeist.data_access import CachedTerrain, FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import prepare_events
from dopplergeist.tiled_search import (SearchBudget, _expanded_bounds, _split_tile_cells,
                                       _tracks, grid_tiles, tile_points)


def test_real_unsupported_tracks_only_excluded_when_their_hulls_are_distant():
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
    radius = max(event["slant_range_m"][1] for event in events)
    terrain = CachedTerrain(cache / "terrain", offline=False)
    points = tile_points(cells, budget.spacing_m, config["bounds"], terrain, config["crs"])
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    indexes = [FlightIndex(cache / "flights" / day / "staging-0/all-types-v2-543f483cee75.sqlite")
               for day in ("2026-09-08", "2026-09-09")]
    tracks = _tracks(indexes, _expanded_bounds(cells, budget.spacing_m, radius, config["crs"]),
                     config["time_range_s"], replace(budget, max_tracks_per_tile=20000,
                                                    max_track_samples_per_tile=5000000))
    excluded = retained = 0
    for track in tracks:
        try:
            track.validate_motion_support()
        except AcousticSupportError:
            try:
                far = track.outside_observer_radius(observers, radius)
            except AcousticSupportError:
                retained += 1
                continue
            assert far
            # Independently check the original spline at all real observation
            # times and interval midpoints; the implementation's hull proof is
            # stronger than these sampled checks.
            times = np.sort(np.r_[track.time, (track.time[:-1] + track.time[1:]) / 2])
            distances = np.linalg.norm(track.position(times)[:, None, :] - observers[None, :, :], axis=2)
            assert np.all(distances > radius)
            excluded += 1
    assert excluded >= 122 and retained >= 20
    print(f"real unsupported trajectories: {excluded} proven distant, {retained} retained")
