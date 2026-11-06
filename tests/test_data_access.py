import gzip
import hashlib
import io
import json
import tarfile

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import CachedTerrain, DataUnavailable, FlightCache, FlightIndex, archive_frames, download


def samples():
    return pd.DataFrame({"flight_id": ["prop"] * 6 + ["unknown"] * 3,
                         "time_s": [0, 5, 10, 100, 105, 110, 0, 5, 10],
                         "lat": [40.] * 9, "lon": np.linspace(-100.2, -99.8, 9),
                         "alt_m": [1000.] * 9, "typecode": ["C172"] * 6 + [""] * 3,
                         "altitude_basis": ["ellipsoidal"] * 3 + ["barometric"] * 6})


def test_whole_segments_nonjet_unknown_altitude_and_repeat(tmp_path):
    parquet = tmp_path / "input.parquet"
    frame = samples()
    frame.to_parquet(parquet)
    coverage = {"bounds": [-125, 24, -66, 50], "time_range_s": [0, 200], "all_aircraft": True}
    index = FlightIndex.from_parquet(tmp_path / "index.sqlite", parquet, coverage=coverage, class_map={"C172": "piston"})
    tracks = list(index.query([-101, 39, -99, 41], [4, 6]))
    assert [t.id for t in tracks] == ["prop:0", "unknown"]
    assert tracks[0].time.tolist() == [0, 5, 10]  # query does not clip
    assert tracks[0].typecode == "C172"
    assert tracks[0].aircraft_class == "piston" and tracks[1].aircraft_class == "unclassified"
    assert tracks[0].altitude_basis == ["ellipsoidal"] * 3
    assert np.isnan(tracks[0].position(11)).all()  # no gap extrapolation
    later = list(index.query([-101, 39, -99, 41], [104, 106]))
    assert later[0].id == "prop:1"
    assert later[0].altitude_basis == ["barometric"] * 3
    before = index.path.stat().st_mtime_ns
    replay = FlightIndex.from_parquet(index.path, parquet, coverage=coverage, class_map={"C172": "piston"})
    assert replay.path.stat().st_mtime_ns == before
    assert replay.coverage_for([-101, 39, -99, 41], [0, 200])["scope_complete"]
    assert not replay.coverage_for([-130, 39, -99, 41], [0, 200])["scope_complete"]
    with pytest.raises(DataUnavailable, match="different inputs"):
        FlightIndex.from_parquet(index.path, parquet, coverage=dict(coverage, all_aircraft=False), class_map={"C172": "piston"})


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
    def json(self): return json.loads(self.data)
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
    trace = {"icao": "a12345", "timestamp": 1000, "t": "C172", "trace": [
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
    assert frames[0].typecode.tolist() == ["C172"] * 3
    assert frames[0].altitude_basis.tolist() == ["ellipsoidal"] * 3
    assert np.allclose(frames[0].alt_m, 3200 * .3048)
    paths[1].write_bytes(b"broken")
    with pytest.raises(DataUnavailable, match="archive"):
        list(archive_frames(paths))


def test_archive_ignores_readsb_partial_members(tmp_path):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        member = tarfile.TarInfo("traces/trace_full_a4414a.json.readsb_tmp")
        member.size = 0
        archive.addfile(member, io.BytesIO())
    path = tmp_path / "archive.tar"
    path.write_bytes(stream.getvalue())

    assert list(archive_frames([path])) == []


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


def test_index_bounds_include_hermite_excursion_between_samples(tmp_path):
    from pyproj import Transformer
    from dopplergeist.geometry import Track, velocity_ecef
    frame = pd.DataFrame({"flight_id": ["turn"] * 3, "time_s": [0., 10., 20.],
                          "lat": [40.] * 3, "lon": [-100.] * 3, "alt_m": [1000.] * 3,
                          "east_mps": [300., -300., 300.], "north_mps": [0.] * 3, "up_mps": [0.] * 3})
    velocity = velocity_ecef(frame.lat.to_numpy(), frame.lon.to_numpy(), frame.east_mps.to_numpy(), np.zeros(3), np.zeros(3))
    oracle = Track("turn", frame.time_s, frame.lat, frame.lon, frame.alt_m, velocity=velocity)
    lon, lat, _ = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True).transform(*oracle.position(5))
    assert lon > -99.995  # the whole measured-position box is far outside this query
    index = FlightIndex.build(tmp_path / "curve.sqlite", [frame], sources=[], coverage={})
    found = list(index.query([lon-.00001, lat-.00001, lon+.00001, lat+.00001], [4., 6.]))
    assert len(found) == 1
    assert np.allclose(found[0].position(5), oracle.position(5))


def test_index_partial_velocity_inference_preserves_measured_zero(tmp_path):
    frame = pd.DataFrame({"flight_id": ["partial"] * 3, "time_s": [0., 5., 10.],
                          "lat": [40.] * 3, "lon": [-100., -99.999, -99.998], "alt_m": [1000., 1050., 1100.],
                          "east_mps": [np.nan] * 3, "north_mps": [np.nan] * 3, "up_mps": [0.] * 3})
    index = FlightIndex.build(tmp_path / "partial.sqlite", [frame], sources=[], coverage={})
    track = list(index.query([-101, 39, -99, 41], [0, 10]))[0]
    lat, lon = np.deg2rad([40., -99.999])
    vertical = np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)])
    assert abs(np.dot(track.speed_vector(5), vertical)) < 1e-9
    assert np.linalg.norm(track.speed_vector(5)) > 10
    assert track.velocity_inferred_components["up_mps"] == 0


def test_date_acquisition_ingests_all_types_and_reuses_validated_offline_index(tmp_path):
    start = pd.Timestamp("2026-09-08T00:00:00Z").timestamp()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for identity, code in [("a12345", "C172"), ("b12345", "H500"), ("c12345", "ZZZZ")]:
            trace = {"icao": identity, "timestamp": start, "t": code, "trace": [
                [i, 40, -100+i*.001, 3000, 100, 90, 0, 0, {}, None, 3200, 0] for i in [0, 5, 10]]}
            raw = gzip.compress(json.dumps(trace).encode())
            member = tarfile.TarInfo(f"trace_full_{identity}.json"); member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    payload = stream.getvalue()
    asset = {"name": "day.tar.aa", "size": len(payload), "digest": "sha256:"+hashlib.sha256(payload).hexdigest(),
             "browser_download_url": "https://fixture.invalid/day.tar.aa"}

    class Provider:
        def __init__(self): self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            if url.startswith("https://api.github.com/"):
                return Response(json.dumps({"tag_name": "v2026.09.08-planes-readsb-staging-0", "assets": [asset]}).encode())
            if url == asset["browser_download_url"]:
                return Response(payload)
            if url.endswith("icao_aircraft_types.js"):
                return Response(b'let types={"C172":{"desc":"L1P"},"H500":{"desc":"H1T"}};')
            raise AssertionError(f"Unexpected network request: {url}")

    provider = Provider()
    index = FlightCache(tmp_path, session=provider).acquire_day("2026-09-08")
    tracks = list(index.query([-101, 39, -99, 41], [start, start+10]))
    assert {t.typecode: t.aircraft_class for t in tracks} == {"C172": "piston", "H500": "turbine"}
    assert all(t.altitude_basis == ["ellipsoidal"]*3 for t in tracks)
    assert len(provider.calls) == 3 and index.report["rows"] == 6
    repeat = FlightCache(tmp_path, offline=True, session=provider).acquire_day("2026-09-08")
    assert repeat.report == index.report and len(provider.calls) == 3
    assert index.report["coverage"]["release_tag"] == "v2026.09.08-planes-readsb-staging-0"
    index.path.unlink()
    (tmp_path / "2026-09-08/staging-0/day.tar.aa").write_bytes(payload[:100])
    with pytest.raises(DataUnavailable, match="Truncated cache"):
        FlightCache(tmp_path, offline=True, session=provider).acquire_day("2026-09-08")
    release_path = tmp_path / "2026-09-08/staging-0/release.json"
    release_path.write_text(json.dumps({"tag_name": "wrong-day", "assets": [asset]}))
    with pytest.raises(DataUnavailable, match="requested tag"):
        FlightCache(tmp_path, offline=True, session=provider).acquire_day("2026-09-08")
    with pytest.raises(DataUnavailable, match="Offline release"):
        FlightCache(tmp_path, offline=True, session=provider).acquire_day("2026-09-09")
