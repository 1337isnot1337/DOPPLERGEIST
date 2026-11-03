import gzip
import hashlib
import io
import json
import tarfile

import numpy as np
import pandas as pd
import pytest

from aircraft_geoloc.data_access import CachedTerrain, DataUnavailable, FlightIndex, archive_frames, download


def samples():
    return pd.DataFrame({"flight_id": ["jet"] * 6 + ["unknown"] * 3,
                         "time_s": [0, 5, 10, 100, 105, 110, 0, 5, 10],
                         "lat": [40.] * 9, "lon": np.linspace(-100.2, -99.8, 9),
                         "alt_m": [1000.] * 9, "typecode": ["B738"] * 6 + [""] * 3,
                         "altitude_basis": ["ellipsoidal"] * 3 + ["barometric"] * 6})


def test_whole_segments_jets_unknown_altitude_and_repeat(tmp_path):
    parquet = tmp_path / "input.parquet"
    frame = samples()
    frame.to_parquet(parquet)
    coverage = {"bounds": [-125, 24, -66, 50], "time_range_s": [0, 200], "all_aircraft": True}
    index = FlightIndex.from_parquet(tmp_path / "index.sqlite", parquet, coverage=coverage, class_map={"B738": "jet"})
    tracks = list(index.query([-101, 39, -99, 41], [4, 6]))
    assert [t.id for t in tracks] == ["jet:0", "unknown"]
    assert tracks[0].time.tolist() == [0, 5, 10]  # query does not clip
    assert tracks[0].typecode == "B738"
    assert tracks[0].aircraft_class == "jet" and tracks[1].aircraft_class == "unclassified"
    assert tracks[0].altitude_basis == ["ellipsoidal"] * 3
    assert np.isnan(tracks[0].position(11)).all()  # no gap extrapolation
    later = list(index.query([-101, 39, -99, 41], [104, 106]))
    assert later[0].id == "jet:1"
    assert later[0].altitude_basis == ["barometric"] * 3
    before = index.path.stat().st_mtime_ns
    replay = FlightIndex.from_parquet(index.path, parquet, coverage=coverage, class_map={"B738": "jet"})
    assert replay.path.stat().st_mtime_ns == before
    assert replay.coverage_for([-101, 39, -99, 41], [0, 200])["scope_complete"]
    assert not replay.coverage_for([-130, 39, -99, 41], [0, 200])["scope_complete"]
    with pytest.raises(DataUnavailable, match="different inputs"):
        FlightIndex.from_parquet(index.path, parquet, coverage=dict(coverage, all_aircraft=False), class_map={"B738": "jet"})


def test_truncated_parquet_and_payload_corruption(tmp_path):
    path = tmp_path / "bad.parquet"
    path.write_bytes(b"PAR1truncated")
    with pytest.raises(DataUnavailable, match="Parquet"):
        FlightIndex.from_parquet(tmp_path / "bad.sqlite", path, coverage={})
    index = FlightIndex.build(tmp_path / "index.sqlite", [samples()], sources=[], coverage={})
    import sqlite3
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE segments SET payload=?", (b"corrupt",))
    with pytest.raises(DataUnavailable, match="Corrupt flight payload"):
        list(index.query([-180, -90, 180, 90], [0, 200]))


class Response:
    def __init__(self, data, status=200, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size): yield self.data


class Session:
    def __init__(self, response): self.response, self.calls = response, []
    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_resumable_download_validates_ranges_and_offline_cache(tmp_path):
    path = tmp_path / "asset"
    path.with_name("asset.part").write_bytes(b"abc")
    session = Session(Response(b"def", 206, {"Content-Range": "bytes 3-5/6"}))
    digest = hashlib.sha256(b"abcdef").hexdigest()
    result = download("url", path, size=6, digest=digest, session=session)
    assert path.read_bytes() == b"abcdef" and result["sha256"] == digest
    assert session.calls[0]["headers"]["Range"] == "bytes=3-"
    download("url", path, size=6, offline=True)
    path.write_bytes(b"broken")
    with pytest.raises(DataUnavailable, match="corrupt"):
        download("url", path, size=6, offline=True)
    with pytest.raises(DataUnavailable, match="Offline"):
        download("url", tmp_path / "absent", offline=True)
    other = tmp_path / "other"
    other.with_name("other.part").write_bytes(b"abc")
    with pytest.raises(DataUnavailable, match="byte range"):
        download("url", other, size=6, session=Session(Response(b"abcdef")))
    assert not other.exists()
    with pytest.raises(DataUnavailable, match="Truncated download"):
        download("url", tmp_path / "truncated", size=6, session=Session(Response(b"abc")))


def test_streaming_split_readsb_archive(tmp_path):
    trace = {"icao": "a12345", "timestamp": 1000, "t": "B738", "trace": [
        [i, 40, -100 + i * .001, 3000, 100, 90, 0, 0, {}, None, 3200, 0] for i in [0, 5, 10]]}
    data = gzip.compress(json.dumps(trace).encode())
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        member = tarfile.TarInfo("traces/trace_full_a12345.json")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    raw = stream.getvalue()
    paths = [tmp_path / "archive.aa", tmp_path / "archive.ab"]
    paths[0].write_bytes(raw[:600]); paths[1].write_bytes(raw[600:])
    frames = list(archive_frames(paths))
    assert frames[0].typecode.tolist() == ["B738"] * 3
    assert frames[0].altitude_basis.tolist() == ["ellipsoidal"] * 3
    assert np.allclose(frames[0].alt_m, 3200 * .3048)
    paths[1].write_bytes(b"broken")
    with pytest.raises(DataUnavailable, match="archive"):
        list(archive_frames(paths))


def test_terrain_offline_datum_missing_and_corruption(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    tag = "Copernicus_DSM_COG_30_N40_00_W100_00_DEM"
    (tmp_path / "tileList.txt").write_text(tag + "/\n")
    for name, value in [(tag + ".tif", 100.), ("geoid.tif", -30.)]:
        with rasterio.open(tmp_path / name, "w", driver="GTiff", height=2, width=2, count=1,
                           dtype="float32", crs="EPSG:4326", transform=from_origin(-100, 41, .5, .5)) as raster:
            raster.write(np.full((2, 2), value, dtype="float32"), 1)
    terrain = CachedTerrain(tmp_path, offline=True, geoid_path=tmp_path / "geoid.tif", adopt_existing=True)
    assert terrain.sample([40.5], [-99.5]).tolist() == [70.]
    assert terrain.provenance()["vertical_datum"] == "EGM2008 converted to ellipsoidal"
    (tmp_path / (tag + ".tif")).unlink()
    with pytest.raises(DataUnavailable, match="Offline"):
        CachedTerrain(tmp_path, offline=True, geoid_path=tmp_path / "geoid.tif").sample([40.5], [-99.5])
    (tmp_path / "tileList.txt").write_text("broken")
    with pytest.raises(DataUnavailable, match="corrupt"):
        CachedTerrain(tmp_path, offline=True, geoid_path=tmp_path / "geoid.tif")


def test_terrain_degree_boundary_uses_published_cog_extent(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    tag = "Copernicus_DSM_COG_30_N39_00_W100_00_DEM"
    (tmp_path / "tileList.txt").write_text(tag + "/\n")
    for name, value in [(tag + ".tif", 100.), ("geoid.tif", -30.)]:
        with rasterio.open(tmp_path / name, "w", driver="GTiff", height=2, width=2, count=1,
                           dtype="float32", crs="EPSG:4326", transform=from_origin(-100, 40.000416666667, .5, .5)) as raster:
            raster.write(np.full((2, 2), value, dtype="float32"), 1)
    terrain = CachedTerrain(tmp_path, offline=True, geoid_path=tmp_path / "geoid.tif", adopt_existing=True)
    assert terrain.sample([40.], [-99.5]).tolist() == [70.]
    assert tag in str(terrain.provenance()["files"])
