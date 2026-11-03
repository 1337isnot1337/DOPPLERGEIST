"""Cache-hit behavior on a saved search tile and the corresponding real DEM."""
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest
import rasterio

from dopplergeist.data_access import CachedTerrain, DataUnavailable
from dopplergeist.tiled_search import _tile_coordinates


@pytest.fixture
def real_terrain():
    root = os.environ.get('DOPPLERGEIST_REAL_JOB_ROOT')
    cache = os.environ.get('DOPPLERGEIST_REAL_CACHE_ROOT')
    if not root or not cache:
        pytest.skip('set the real job and cache paths')
    job = Path(root)
    config = json.loads((job/'search/manifest.json').read_text())['configuration']
    payload = json.loads((job/'search/tile--14_7.json').read_text())['payload']
    points = _tile_coordinates(tuple(payload['cells']), config['budget']['spacing_m'], config['bounds'], config['crs'])
    terrain = CachedTerrain(Path(cache)/'terrain', offline=True, adopt_existing=True)
    return terrain, points


def test_real_cached_rasters_match_and_do_not_reopen(real_terrain, monkeypatch):
    terrain, points = real_terrain
    lat, lon = points.lat.to_numpy(), points.lon.to_numpy()
    first = terrain.sample(lat, lon)
    assert terrain._tile_cache
    opened = []
    original = rasterio.open
    def record(path, *args, **kwargs):
        opened.append(Path(path).name)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(rasterio, 'open', record)
    second = terrain.sample(lat, lon)
    np.testing.assert_array_equal(first, second)
    assert not any(name.startswith('Copernicus_DSM_COG_30_') for name in opened)
    assert terrain._tile_cache_bytes <= 32 * 1024 * 1024


def test_real_cached_raster_rejects_change_and_out_of_bounds(real_terrain, tmp_path):
    terrain, points = real_terrain
    lat, lon = points.lat.to_numpy(), points.lon.to_numpy()
    terrain.sample(lat, lon)
    path = next(iter(terrain._tile_cache))
    tag = path.name
    north = int(tag.split('_N')[1][:2])
    east = -int(tag.split('_W')[1][:3])
    selection = ((np.floor(lat - 1/2400) == north) & (np.floor(lon + 1/2400) == east))
    assert selection.any()
    copied = tmp_path/path.name
    shutil.copyfile(path, copied)
    terrain._raster_sample(copied, lat[selection], lon[selection])
    with pytest.raises(DataUnavailable, match='extent'):
        terrain._raster_sample(copied, np.array([0.0]), np.array([0.0]))
    stat = copied.stat()
    os.utime(copied, ns=(stat.st_atime_ns, stat.st_mtime_ns+1_000_000_000))
    with pytest.raises(DataUnavailable, match='changed after caching'):
        terrain._raster_sample(copied, lat[selection], lon[selection])
