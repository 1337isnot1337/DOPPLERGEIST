"""Exact scalar terrain reuse on restored rasters and recorded candidate points."""
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest
import rasterio

from dopplergeist import terrain
from dopplergeist.terrain import Terrain


@pytest.fixture(scope="module")
def observed_terrain():
    root = Path(os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT",
                               Path(__file__).resolve().parents[1]))
    dem = root / "data/terrain/Copernicus_DSM_COG_10_N40_00_W074_00_DEM.tif"
    geoid = root / "data/terrain/us_nga_egm96_15.tif"
    if not dem.exists() or not geoid.exists():
        pytest.skip("Restore the real reference DEM and geoid rasters")
    trace = os.environ.get("DOPPLERGEIST_REAL_TERRAIN_TRACE")
    if trace:
        rows = json.loads(Path(trace).read_text())["rows"]
        points = np.asarray(rows, dtype=float)[:, :2]
        # Retain actual requests throughout the optimizer trace, without
        # constructing new coordinates or a simulated search workload.
        points = points[np.linspace(0, len(points)-1, min(256, len(points)), dtype=int)]
    else:
        choices = [root / "results/reference-local-fast/ranked.json",
                   root / "evidence/results/reference-local-fast/ranked.json"]
        source = next((path for path in choices if path.exists()), None)
        if source is None:
            pytest.skip("Restore the archived real reference candidate results")
        rows = json.loads(source.read_text())
        points = np.asarray([(row["lat"], row["lon"]) for row in rows])
    assert len(points) > 1
    return dem, geoid, points


def _close(sampler):
    for raster in sampler.rasters:
        raster.close()
    if sampler.geoid is not None:
        _close(sampler.geoid)


@pytest.mark.parametrize("with_geoid", [False, True])
def test_scalar_cache_preserves_real_vector_samples_and_result_ownership(observed_terrain, with_geoid):
    dem, geoid, points = observed_terrain
    sampler = Terrain([dem], geoid_path=geoid if with_geoid else None)
    try:
        expected = sampler.sample(points[:, 0], points[:, 1])
        for _ in range(2):
            actual = np.asarray([sampler.sample(lat, lon).item() for lat, lon in points])
            np.testing.assert_array_equal(actual, expected)
        assert sampler._pixel_cache
        lat, lon = points[0]
        result = sampler.sample([[lat]], [[lon]])
        assert result.shape == (1, 1)
        assert result.item() == expected[0]
        result[...] = np.nan
        assert sampler.sample(lat, lon).item() == expected[0]
        for pixels in sampler._pixel_cache.values():
            assert not pixels.flags.writeable
            if isinstance(pixels.mask, np.ndarray):
                assert not pixels.mask.flags.writeable
    finally:
        _close(sampler)


def test_scalar_cache_stays_bounded_on_actual_points(observed_terrain, monkeypatch):
    dem, _, points = observed_terrain
    sampler = Terrain([dem])
    monkeypatch.setattr(terrain, "_PIXEL_CACHE_MAX_ENTRIES", 2)
    try:
        expected = sampler.sample(points[:, 0], points[:, 1])
        for point, height in zip(points, expected):
            assert sampler.sample(*point).item() == height
            assert len(sampler._pixel_cache) <= 2
            assert all(pixels.shape == (1, 1) for pixels in sampler._pixel_cache.values())
        # The same observed points also take the explicit uncached read path.
        sampler._pixel_sources.clear()
        sampler._pixel_cache.clear()
        np.testing.assert_array_equal(
            [sampler.sample(*point).item() for point in points], expected)
    finally:
        _close(sampler)


def test_changed_real_raster_is_not_served_from_cache(observed_terrain, tmp_path):
    dem, _, points = observed_terrain
    copy = tmp_path / dem.name
    shutil.copy2(dem, copy)
    sampler = Terrain([copy])
    try:
        expected = sampler.sample(*points[0])
        assert sampler._pixel_cache
        stat = copy.stat()
        # Change file metadata, keeping the real measured terrain untouched.
        os.utime(copy, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        np.testing.assert_array_equal(sampler.sample(*points[0]), expected)
        assert not sampler._pixel_cache and not sampler._pixel_sources
    finally:
        _close(sampler)


def test_closed_real_reader_does_not_serve_cached_pixels(observed_terrain):
    dem, _, points = observed_terrain
    sampler = Terrain([dem])
    sampler.sample(*points[0])
    sampler.rasters[0].close()
    with pytest.raises(rasterio.errors.RasterioIOError):
        sampler.sample(*points[0])


def test_custom_reader_keeps_its_read_behavior(observed_terrain):
    dem, _, points = observed_terrain

    class ObservedReader:
        def __init__(self, reader):
            self.reader, self.windows = reader, []

        def __getattr__(self, name):
            return getattr(self.reader, name)

        def read(self, *args, **kwargs):
            self.windows.append(kwargs["window"])
            return self.reader.read(*args, **kwargs)

    sampler = Terrain([dem])
    reader = ObservedReader(sampler.rasters[0])
    sampler.rasters = [reader]
    try:
        first = sampler.sample(*points[0])
        second = sampler.sample(*points[0])
        np.testing.assert_array_equal(first, second)
        assert len(reader.windows) == 2
        assert all(window.width == window.height == 1 for window in reader.windows)
        assert not sampler._pixel_cache
    finally:
        _close(sampler)
