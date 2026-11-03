"""Worker initialization against operator-supplied real terrain, without a search."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import os
from pathlib import Path

import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.matching import prepare_events
from dopplergeist.parallel_tiles import initialize_tile_worker, score_fine_tile, score_tile
from dopplergeist.terrain import Terrain
from dopplergeist.tiled_search import SearchBudget, _expanded_bounds, _score, _tracks_for_points, tile_points

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


def _score_one(task):
    _barrier.wait(timeout=30)
    payload, _ = score_tile(*task)
    return os.getpid(), payload


def _score_fine_one(task):
    return score_fine_tile(*task)[0]


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


def test_real_explicit_tiles_match_direct_scoring(tmp_path):
    names = ("DOPPLERGEIST_REAL_TERRAIN_DEM", "DOPPLERGEIST_REAL_TERRAIN_GEOID",
             "DOPPLERGEIST_REAL_TERRAIN_FLIGHT_INDEX", "DOPPLERGEIST_REAL_TILE_JOB")
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip("set real terrain, index and ESID 762 job paths to replay a recorded tile")
    dem, geoid, index, saved_job = values
    job = Path(saved_job)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
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

    tiles = []
    for identity in ("-24_68", "-23_68"):
        original = json.loads((job / f"search/tile-{identity}.json").read_text())["payload"]
        tiles.append((f"coarse:{identity}", tuple(original["cells"])))
    initialize_tile_worker(*args("direct"))
    direct = [score_tile(*tile)[0] for tile in tiles]
    context = get_context("spawn")
    barrier = context.Barrier(2)
    with ProcessPoolExecutor(max_workers=2, mp_context=context, initializer=_initialize,
                             initargs=(args("worker"), barrier)) as pool:
        workers = list(pool.map(_score_one, tiles))
    assert len({pid for pid, _ in workers}) == 2
    assert all(payload["grid_points"] > 0 and payload["ranked"] for payload in direct)
    assert direct == [payload for _, payload in workers]


def test_real_fine_piece_matches_spawned_worker(tmp_path):
    names = ("DOPPLERGEIST_REAL_TERRAIN_DEM", "DOPPLERGEIST_REAL_TERRAIN_GEOID",
             "DOPPLERGEIST_REAL_TERRAIN_FLIGHT_INDEX", "DOPPLERGEIST_REAL_TILE_JOB")
    values = [os.environ.get(name) for name in names]
    if not all(values):
        pytest.skip("set real terrain, index and ESID 762 job paths to replay a recorded piece")
    dem, geoid, index, saved_job = values
    job = Path(saved_job)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    raw = json.loads((job / "discovery/discovery.json").read_text())["events"]
    events, measurements = prepare_events(raw, c=343.0, max_distance_m=20000.0)
    budget = SearchBudget(**config["budget"])
    parameters = dict(config["scoring"])
    window = parameters.pop("recording_start_window_s")
    options = {"paths": [dem], "constant_m": None, "geoid_path": geoid}

    def args(directory):
        return ([index], None, options, events, measurements, config["bounds"], config["time_range_s"],
                budget, parameters, config["filters"], window, config["crs"], tmp_path / directory,
                "real-fine-replay", "matched_group_support_minus_normalized_residual", "explicit")

    report = json.loads((job / "search/search-report.json").read_text())
    row = report["coarse_ranked"][0]
    spacing = budget.refine_spacing_m
    x, y = round(row["x"] / spacing), round(row["y"] / spacing)
    task = ("fine:0:real", (x, y, x + 2, y + 2), spacing, [], None)
    terrain = Terrain([dem], geoid_path=geoid)
    try:
        points = tile_points(task[1], spacing, config["bounds"], terrain, config["crs"])
        radius = max(event["slant_range_m"][1] for event in events)
        tracks, points = _tracks_for_points(
            [FlightIndex(index)], _expanded_bounds(task[1], spacing, radius, config["crs"]),
            config["time_range_s"], budget, points, terrain, radius, parameters.get("c", 343.0))
        ledger = RetentionLedger(tmp_path / "serial.sqlite", "real-fine-replay",
                                 "matched_group_support_minus_normalized_residual")
        rows, counts = _score(points, tracks, events, measurements, budget, parameters, config["filters"], window,
                              ledger=ledger, stage=task[0], score_floor=None)
    finally:
        for raster in terrain.rasters + terrain.geoid.rasters:
            raster.close()
    initialize_tile_worker(*args("direct-fine"))
    direct, _ = score_fine_tile(*task)
    partial_task = (task[0] + ":partial", task[1], spacing, [(x, y, x + 1, y + 2)], None)
    partial, _ = score_fine_tile(*partial_task)
    fully_excluded, empty_path = score_fine_tile(task[0] + ":excluded", task[1], spacing,
                                                 [(x, y, x + 2, y + 2)], None)
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"),
                             initializer=initialize_tile_worker, initargs=args("worker-fine")) as pool:
        spawned = pool.submit(_score_fine_one, task).result(timeout=120)
        spawned_partial = pool.submit(_score_fine_one, partial_task).result(timeout=120)
    assert direct["grid_points"] > 0
    assert direct["grid_points"] == len(points)
    assert direct["ranked"] == rows
    assert direct["counts"] == counts
    assert direct["retention_checksum"] == ledger.checksum(task[0])
    assert direct == spawned
    assert partial["grid_points"] == len(points[points.x >= (x + 1) * spacing])
    assert partial["skipped"] + partial["grid_points"] == direct["grid_points"]
    assert partial == spawned_partial
    assert fully_excluded["skipped"] == direct["grid_points"]
    assert fully_excluded["grid_points"] == 0 and empty_path is None
