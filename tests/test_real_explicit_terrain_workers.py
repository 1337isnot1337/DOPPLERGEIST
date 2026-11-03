"""Worker initialization against operator-supplied real terrain, without a search."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import os
from pathlib import Path

import pytest

from dopplergeist.parallel_tiles import initialize_tile_worker
from dopplergeist.terrain import Terrain

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
