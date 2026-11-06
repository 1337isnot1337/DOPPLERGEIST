"""Exact helper checks using archived observations and real restored rasters."""
from copy import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from dopplergeist import terrain, tiled_search
from dopplergeist.data_access import DataUnavailable, FlightIndex, content_hash
from dopplergeist.geometry import ecef


ROOT = Path(__file__).resolve().parents[1]


def _json_geometry_digest(track):
    return content_hash([track.id, track.time.tolist(), track.xyz.tolist(), track.spline.c.tolist()])


@pytest.fixture(scope="module")
def independent_real_tracks(tmp_path_factory):
    source = ROOT / "research/trajectory-motion/frozen/canonical-observations.json"
    frame = pd.DataFrame(json.loads(source.read_text()))
    frame = frame.loc[frame.typecode.isin(["C172", "H500"])].copy()
    coverage = {"bounds": [-180, -90, 180, 90],
                "time_range_s": [float(frame.time_s.min()), float(frame.time_s.max())],
                "all_aircraft": False,
                "source_note": "Archived real trajectory-motion observations; incomplete excerpt"}
    path = tmp_path_factory.mktemp("real-helper-index") / "real.sqlite"
    FlightIndex.build(path, [frame], sources=[], coverage=coverage)
    decoded = [list(FlightIndex(path, track_cache_bytes=0).query(
        coverage["bounds"], coverage["time_range_s"])) for _ in range(2)]
    assert len(decoded[0]) >= 2
    return decoded


def test_geometry_identity_matches_old_json_for_independent_decodes(independent_real_tracks):
    first, second = independent_real_tracks
    assert [track.id for track in first] == [track.id for track in second]
    all_tracks = first + second
    old = [_json_geometry_digest(track) for track in all_tracks]
    new = [tiled_search._track_geometry_digest(track) for track in all_tracks]
    # The encoding changes; its equality relation must remain identical.
    assert [[a == b for b in old] for a in old] == [[a == b for b in new] for a in new]
    for left, right in zip(first, second):
        assert left is not right
        np.testing.assert_array_equal(left.time, right.time)
        np.testing.assert_array_equal(left.xyz, right.xyz)
        np.testing.assert_array_equal(left.spline.c, right.spline.c)


@pytest.mark.parametrize("layout", ["fortran", "big_endian", "strided"])
def test_geometry_identity_preserves_values_across_storage_layouts(independent_real_tracks, layout):
    def rearrange(values):
        if layout == "fortran":
            return np.asfortranarray(values)
        if layout == "big_endian":
            return np.asarray(values, dtype=">f8")
        # Repeat storage, then view every other element: no observation changes.
        return np.repeat(values, 2, axis=-1)[..., ::2]

    for track in independent_real_tracks[0]:
        other = SimpleNamespace(id=track.id, time=rearrange(track.time),
                                xyz=rearrange(track.xyz),
                                spline=SimpleNamespace(c=rearrange(track.spline.c)))
        assert _json_geometry_digest(other) == _json_geometry_digest(track)
        assert tiled_search._track_geometry_digest(other) == tiled_search._track_geometry_digest(track)


class _DecodedIndex:
    def __init__(self, tracks):
        self.tracks = tracks

    def query(self, bounds, time_range):
        return iter(self.tracks)


@pytest.mark.parametrize("use_observer", [False, True])
def test_duplicate_track_selection_matches_json_identity(independent_real_tracks, monkeypatch, use_observer):
    indexes = [_DecodedIndex(tracks) for tracks in independent_real_tracks]
    kwargs = {}
    if use_observer:
        row = json.loads((ROOT / "evidence/results/reference-local-fast/ranked.json").read_text())[0]
        kwargs = {"observers": ecef([row["lat"]], [row["lon"]], [row["elev_m"]]), "radius": 25000.0}
    args = (indexes, [-180, -90, 180, 90], [-np.inf, np.inf], tiled_search.SearchBudget())
    actual = tiled_search._tracks(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(tiled_search, "_track_geometry_digest", _json_geometry_digest)
        expected = tiled_search._tracks(*args, **kwargs)
    assert [id(track) for track in actual] == [id(track) for track in expected]
    assert len({track.id for track in actual}) == len(actual)
    if use_observer:
        # Exercise identities stored as digests after a real distant-track skip.
        assert len(actual) < len(independent_real_tracks[0])
    else:
        assert len(actual) == len(independent_real_tracks[0])


def test_conflicting_real_track_identity_is_still_rejected(independent_real_tracks, monkeypatch):
    first, second = independent_real_tracks[0][:2]
    conflict = copy(second)
    conflict.id = first.id  # A metadata collision; both observed geometries stay intact.
    assert _json_geometry_digest(first) != _json_geometry_digest(conflict)
    args = ([_DecodedIndex([first]), _DecodedIndex([conflict])],
            [-180, -90, 180, 90], [-np.inf, np.inf], tiled_search.SearchBudget())
    with pytest.raises(DataUnavailable, match="Conflicting flight segment identity"):
        tiled_search._tracks(*args)
    with monkeypatch.context() as patch:
        patch.setattr(tiled_search, "_track_geometry_digest", _json_geometry_digest)
        with pytest.raises(DataUnavailable, match="Conflicting flight segment identity"):
            tiled_search._tracks(*args)


@pytest.mark.parametrize("with_geoid", [False, True])
def test_cached_raster_transform_preserves_actual_candidate_heights(monkeypatch, with_geoid):
    dem = ROOT / "data/terrain/Copernicus_DSM_COG_10_N40_00_W074_00_DEM.tif"
    geoid = ROOT / "data/terrain/us_nga_egm96_15.tif"
    if not dem.exists() or (with_geoid and not geoid.exists()):
        pytest.skip("Restore the actual reference DEM/geoid to exercise terrain sampling")
    rows = json.loads((ROOT / "evidence/results/reference-local-fast/ranked.json").read_text())
    lat = np.asarray([row["lat"] for row in rows])
    lon = np.asarray([row["lon"] for row in rows])
    sampler = terrain.Terrain([dem], geoid_path=geoid if with_geoid else None)
    terrain._raster_transformer.cache_clear()
    try:
        actual = sampler.sample(lat, lon)
        actual_scalar = np.asarray([sampler.sample(a, b).item() for a, b in zip(lat[:16], lon[:16])])
        assert terrain._raster_transformer.cache_info().hits > 0
        with monkeypatch.context() as patch:
            patch.setattr(terrain, "_raster_transformer",
                          lambda crs: Transformer.from_crs("EPSG:4326", crs, always_xy=True))
            expected = sampler.sample(lat, lon)
            expected_scalar = np.asarray([sampler.sample(a, b).item()
                                          for a, b in zip(lat[:16], lon[:16])])
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(actual_scalar, expected_scalar)
    finally:
        for raster in sampler.rasters:
            raster.close()
        if sampler.geoid:
            for raster in sampler.geoid.rasters:
                raster.close()
