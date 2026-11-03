"""Exact refinement and terrain.Terrain pixel reuse on archived real inputs."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest

from dopplergeist import matching, terrain
from dopplergeist.data_access import FlightIndex


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def recorded_profile():
    return json.loads((ROOT / "tests/data/real-refinement-profile.json").read_text())


@pytest.fixture(scope="module")
def real_rasters(recorded_profile):
    root = Path(os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT", ROOT))
    paths = tuple(root / name for name in recorded_profile["source"]["terrain_data"])
    if not all(path.is_file() for path in paths):
        pytest.skip("Restore the real data-terrain bundle or set DOPPLERGEIST_REAL_REFERENCE_ROOT")
    return paths


def close(sampler):
    for raster in sampler.rasters:
        raster.close()
    if sampler.geoid is not None:
        close(sampler.geoid)


def uncached(sampler):
    sampler._pixel_sources.clear()
    sampler._pixel_cache.clear()
    if sampler.geoid is not None:
        uncached(sampler.geoid)


@contextmanager
def samplers(paths, **options):
    fast, original = terrain.Terrain(paths, **options), terrain.Terrain(paths, **options)
    uncached(original)
    try:
        yield fast, original
    finally:
        close(fast)
        close(original)


def exact_height(actual, expected):
    assert actual.shape == expected.shape and actual.dtype == expected.dtype
    assert actual.tobytes() == expected.tobytes()
    assert actual.flags.writeable and expected.flags.writeable


@pytest.mark.parametrize("configuration", ["dem", "ellipsoidal", "geoid_last", "dem_last"])
def test_recorded_positions_keep_exact_heights(real_rasters, recorded_profile, configuration):
    dem, geoid = real_rasters
    paths = {"dem": [dem], "ellipsoidal": [dem],
             "geoid_last": [dem, geoid], "dem_last": [geoid, dem]}[configuration]
    options = {"geoid_path": geoid} if configuration == "ellipsoidal" else {}
    lat, lon = np.asarray(recorded_profile["positions"]).T
    with samplers(paths, **options) as (fast, original):
        assert fast._pixel_sources, "The actual GeoTIFF must exercise pixel reuse"
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        for a, b in zip(lat, lon):
            exact_height(fast.sample(a, b), original.sample(a, b))
            exact_height(fast.sample(a, b), original.sample(a, b))
        assert fast._pixel_cache
        changed = fast.sample(lat[0], lon[0])
        changed[...] += 1.
        exact_height(fast.sample(lat[0], lon[0]), original.sample(lat[0], lon[0]))


def test_pixel_cache_bound_uses_original_heights(real_rasters, recorded_profile, monkeypatch):
    monkeypatch.setattr(terrain, "_PIXEL_CACHE_MAX_ENTRIES", 2)
    with samplers([real_rasters[0]]) as (fast, original):
        for lat, lon in recorded_profile["positions"]:
            exact_height(fast.sample(lat, lon), original.sample(lat, lon))
            assert len(fast._pixel_cache) <= 2
        assert len(fast._pixel_cache) == 2
        lat, lon = recorded_profile["positions"][0]
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))


def test_closed_real_reader_keeps_original_error(real_rasters, recorded_profile):
    lat, lon = recorded_profile["positions"][0]
    with samplers([real_rasters[0]]) as (fast, original):
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        close(fast)
        close(original)
        with pytest.raises(Exception) as expected:
            original.sample(lat, lon)
        with pytest.raises(type(expected.value)) as actual:
            fast.sample(lat, lon)
        assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize("change", ["mtime", "replacement", "sidecar"])
def test_changed_real_raster_discards_cached_pixels(real_rasters, recorded_profile, tmp_path, change):
    copied = tmp_path / "observed.tif"
    shutil.copyfile(real_rasters[0], copied)
    lat, lon = recorded_profile["positions"][0]
    with samplers([copied]) as (fast, original):
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        assert fast._pixel_cache
        if change == "mtime":
            info = copied.stat()
            os.utime(copied, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        elif change == "replacement":
            replacement = tmp_path / "replacement.tif"
            shutil.copyfile(real_rasters[0], replacement)
            replacement.replace(copied)
        else:
            copied.with_name(copied.name + ".aux.xml").write_text("<PAMDataset/>\n")
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        assert not fast._pixel_cache and not fast._pixel_sources


def test_custom_reader_keeps_each_real_read(real_rasters, recorded_profile):
    class ReaderProxy:
        def __init__(self, reader):
            self.reader, self.calls = reader, 0

        def __getattr__(self, name):
            return getattr(self.reader, name)

        def read(self, *args, **kwargs):
            self.calls += 1
            return self.reader.read(*args, **kwargs)

    lat, lon = recorded_profile["positions"][0]
    with samplers([real_rasters[0]]) as (fast, original):
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        proxy = ReaderProxy(fast.rasters[0])
        fast.rasters = [proxy]
        for _ in range(2):
            exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        assert proxy.calls == 2


def test_replaced_dataset_keeps_new_real_values(real_rasters, recorded_profile):
    import rasterio

    lat, lon = recorded_profile["positions"][0]
    with samplers([real_rasters[0]]) as (fast, original):
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))
        close(fast)
        close(original)
        fast.rasters = [rasterio.open(real_rasters[1])]
        original.rasters = [rasterio.open(real_rasters[1])]
        for a, b in recorded_profile["positions"][:8]:
            exact_height(fast.sample(a, b), original.sample(a, b))


def test_real_pixel_nodata_metadata_and_constant(real_rasters, recorded_profile, tmp_path):
    import rasterio

    # Change only nodata metadata on a disposable copy of the real raster.
    # Every observed pixel value stays unchanged.
    copied = tmp_path / "nodata-metadata.tif"
    shutil.copyfile(real_rasters[0], copied)
    lat, lon = recorded_profile["positions"][0]
    reference = terrain.Terrain([real_rasters[0]])
    try:
        observed_height = reference.sample(lat, lon).item()
    finally:
        close(reference)
    with rasterio.open(copied, "r+", IGNORE_COG_LAYOUT_BREAK="YES") as writer:
        writer.nodata = observed_height
    with samplers([copied]) as (fast, original):
        for _ in range(2):
            with pytest.raises(ValueError) as expected:
                original.sample(lat, lon)
            with pytest.raises(ValueError) as actual:
                fast.sample(lat, lon)
            assert str(actual.value) == str(expected.value)
        assert fast._pixel_cache
        assert all(np.ma.getmaskarray(value).all() for value in fast._pixel_cache.values())
    with samplers([copied], constant_m=observed_height) as (fast, original):
        for _ in range(2):
            exact_height(fast.sample(lat, lon), original.sample(lat, lon))
            assert fast.sample(lat, lon).item() == observed_height
    with samplers([real_rasters[1], copied]) as (fast, original):
        exact_height(fast.sample(lat, lon), original.sample(lat, lon))


def encoded(value):
    def scalar(item):
        return item.tolist() if isinstance(item, np.ndarray) else item.item()
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=True, default=scalar)


@pytest.mark.parametrize("geographic_bounds", [False, True])
def test_real_complete_profile_keeps_all_fields_and_custom_dispatch(
        real_rasters, recorded_profile, monkeypatch, geographic_bounds):
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("Set DOPPLERGEIST_REAL_CPA_FIXTURE to the restored real-index fixture")
    diagnostic = json.loads(Path(source).read_text())
    candidate = recorded_profile["candidate"]
    index = FlightIndex(diagnostic["real_index"])
    assert index.report["input_hash"] == diagnostic["index_input_hash"]
    tracks = {track.id: track for track in index.lookup(candidate["flight_ids"])}
    assert set(tracks) == set(candidate["flight_ids"])
    events, measurements = matching.prepare_events(recorded_profile["events"], c=343., max_distance_m=20000.)
    options = {"radius_m": 500., "recording_start_window_s": recorded_profile["recording_start_window_s"], "c": 343.}
    if geographic_bounds:
        request = json.loads((ROOT / "benchmarks/reference-regional-upload-request.json").read_text())
        options["bounds_wsen"] = request["search"]["bounds_wsen"]
    refiner = matching.refine_candidate
    calls = []

    def later(*args, **kwargs):
        assert len(args) == 5
        assert set(kwargs) == {"radius_m", "clock_radius_s", "altitude_offsets_m", "crs", "c",
                               "recording_start_window_s", "bounds_wsen"}
        assert kwargs["bounds_wsen"] == options.get("bounds_wsen")
        calls.append("later")
        return refiner(*args, **kwargs)

    def first(*args, **kwargs):
        calls.append("first")
        assert len(args) == 5
        assert not any(key.startswith("_") for key in kwargs)
        monkeypatch.setattr(matching, "refine_candidate", later)
        return refiner(*args, **kwargs)

    with samplers([real_rasters[0]], geoid_path=real_rasters[1]) as (fast, original):
        actual = matching._cache_ridge_fits(matching.profile_candidate)(
            deepcopy(candidate), tracks, events, measurements, fast, **options)
        assert len(actual["sensitivity"]["profiles"]) == recorded_profile["expected_profile_count"]
        assert fast._pixel_cache and fast.geoid._pixel_cache
        # This public wrapper forces the existing unshared-transform path and
        # changes global dispatch after the nominal call, using real solves.
        monkeypatch.setattr(matching, "refine_candidate", first)
        expected = matching._cache_ridge_fits(matching.profile_candidate)(
            deepcopy(candidate), tracks, events, measurements, original, **options)
        assert encoded(actual) == encoded(expected)
        assert calls == ["first"] + ["later"] * 43
