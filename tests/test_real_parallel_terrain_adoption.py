"""Concurrent adoption of a real cached terrain raster."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import threading

import pytest

from dopplergeist.data_access import CachedTerrain, sha256


def test_real_raster_adoption_is_serialized(tmp_path, monkeypatch):
    source = os.environ.get("DOPPLERGEIST_REAL_TERRAIN_RASTER")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_TERRAIN_RASTER to a real cached DEM")
    source = Path(source)
    raster = tmp_path / source.name
    shutil.copyfile(source, raster)
    receipt = raster.with_name(raster.name + ".sha256.json")
    barrier = threading.Barrier(4)
    original_replace = Path.replace

    def synchronized_replace(path, target):
        if target == receipt:
            try:
                barrier.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", synchronized_replace)

    def adopt(_):
        terrain = object.__new__(CachedTerrain)
        terrain.files, terrain.adopt_existing, terrain.offline = {}, True, True
        return terrain._file("https://example.invalid/real-dem", raster, raster=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(adopt, range(4))) == [raster] * 4
    import json
    assert json.loads(receipt.read_text())["sha256"] == sha256(source)
