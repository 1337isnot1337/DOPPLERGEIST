"""Worker initialization against operator-supplied real terrain, without a search."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import os
from pathlib import Path

import pytest

from dopplergeist.matching import prepare_events
from dopplergeist.parallel_tiles import initialize_tile_worker, score_tile
from dopplergeist.terrain import Terrain
from dopplergeist.tiled_search import SearchBudget

# Published ESID 762 site and a candidate from its saved real-audio search.
_POINTS = ((30.386361, -98.860931), (30.38874803589124, -98.87993276822816))
_barrier = None


def _initialize(args, barrier):
    global _barrier
    initialize_tile_worker(*args)
    _barrier = barrier


def _sample(_):
    from dopplergeist.parallel_tiles import _worker

    _barrier.wait(timeout=30)
    return os.getpid(), [float(_worker["terrain"].sample(lat, lon)) for lat, lon in _POINTS]


def test_real_explicit_dem_reopened_in_two_workers(tmp_path, capfd):
    names = ("DOPPLERGEIST_REAL_TERRAIN_DEM", "DOPPLERGEIST_REAL_TERRAIN_GEOID",
             "DOPPLERGEIST_REAL_TERRAIN_FLIGHT_INDEX")
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip("set real DEM, geoid and flight index paths to run the terrain worker check")
    dem, geoid, index = (str(Path(value)) for value in values)
    parent = Terrain([dem], geoid_path=geoid)
    try:
        expected = [float(parent.sample(lat, lon)) for lat, lon in _POINTS]
    finally:
        for raster in parent.rasters + parent.geoid.rasters:
            raster.close()

    context = get_context("spawn")
    barrier = context.Barrier(2)
    options = {"paths": [dem], "constant_m": None, "geoid_path": geoid}
    args = ([index], None, options, [], [], None, None, None, None, None, None,
            None, tmp_path / "worker-ledgers", "worker-check", "worker-check", "explicit")
    with ProcessPoolExecutor(max_workers=2, mp_context=context, initializer=_initialize,
                             initargs=(args, barrier)) as pool:
        observed = list(pool.map(_sample, range(2)))
    assert len({pid for pid, _ in observed}) == 2
    assert all(samples == expected for _, samples in observed)
    assert not capfd.readouterr().err


def test_real_explicit_tile_matches_direct_scoring(tmp_path):
    names = ("DOPPLERGEIST_REAL_TERRAIN_DEM", "DOPPLERGEIST_REAL_TERRAIN_GEOID",
             "DOPPLERGEIST_REAL_TERRAIN_FLIGHT_INDEX", "DOPPLERGEIST_REAL_TILE_JOB")
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip("set real terrain, index and ESID 762 job paths to replay a recorded tile")
    dem, geoid, index, saved_job = values
    job = Path(saved_job)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    original = json.loads((job / "search/tile--24_68.json").read_text())["payload"]
    raw = json.loads((job / "discovery/discovery.json").read_text())["events"]
    events, measurements = prepare_events(raw, c=343.0, max_distance_m=20000.0)
    assert events == config["events"]
    budget = SearchBudget(**config["budget"])
    parameters = dict(config["scoring"])
    window = parameters.pop("recording_start_window_s")
    options = {"paths": [dem], "constant_m": None, "geoid_path": geoid}

    def args(directory):
        return ([index], None, options, events, measurements, config["bounds"], config["time_range_s"],
                budget, parameters, config["filters"], window, config["crs"], tmp_path / directory,
                "real-tile-replay", "matched_group_support_minus_normalized_residual", "explicit")

    stage, cells = "coarse:-24_68", tuple(original["cells"])
    initialize_tile_worker(*args("direct"))
    direct, _ = score_tile(stage, cells)
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"),
                             initializer=initialize_tile_worker, initargs=args("worker")) as pool:
        worker, _ = pool.submit(score_tile, stage, cells).result()
    assert direct["grid_points"] > 0 and direct["ranked"]
    assert direct == worker
