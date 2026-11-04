"""Prepared index checks using archived, unmodified ADS-B observations."""
import gzip
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from dopplergeist import data_access
from dopplergeist.data_access import DataUnavailable, FlightCache, FlightIndex


def test_real_unsplit_release_reaches_offline_archive_lookup(tmp_path):
    # Actual metadata from the ADSB.lol 2024-03-29 staging-0 release.
    tag = "v2024.03.29-planes-readsb-staging-0"
    name = tag + ".tar"
    directory = tmp_path / "2024-03-29/staging-0"
    directory.mkdir(parents=True)
    release = {"tag_name": tag, "assets": [{
        "name": name, "size": 1940520960,
        "browser_download_url": f"https://github.com/adsblol/globe_history_2024/releases/download/{tag}/{name}",
    }]}
    (directory / "release.json").write_text(json.dumps(release))
    # The valid release must reach the missing-file check, not be rejected as
    # lacking a split archive. No audio, tracks or archive bytes are generated.
    with pytest.raises(DataUnavailable, match=r"Offline cache miss: .*\.tar$"):
        FlightCache(tmp_path, offline=True).acquire_day("2024-03-29")


@pytest.fixture
def observed_index(tmp_path):
    source = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    frame = pd.DataFrame(json.loads(source.read_text()))
    coverage = {"bounds": [-180., -90., 180., 90.],
                "time_range_s": [float(frame.time_s.min()), float(frame.time_s.max())],
                "all_aircraft": False, "source_note": "Archived real observations; incomplete excerpt"}
    index = FlightIndex.build(tmp_path / "observed.sqlite", [frame], sources=[], coverage=coverage)
    assert index._prepared_tracks
    assert index.report["prepared_tracks"]["tracks"] > 0
    return index, coverage


def signature(track):
    arrays = []
    for name in ("time", "lat", "lon", "altitude", "velocity", "xyz", "relative_time",
                 "_xyz_min", "_xyz_max", "_speed_upper", "_speed_peak"):
        value = getattr(track, name)
        arrays.append(None if value is None else (value.dtype.str, value.shape, value.tobytes()))
    for name in ("spline", "derivative"):
        value = getattr(track, name)
        arrays.extend((part.dtype.str, part.shape, part.tobytes()) for part in (value.c, value.x))
    return (track.id, arrays, track.typecode, track.aircraft_class, track.altitude_basis,
            track.velocity_inferred_components, track.origin, track._max_sample_gap)


def queried(index, coverage):
    return list(index.query(coverage["bounds"], coverage["time_range_s"]))


def test_prepared_query_and_lookup_match_original_bytes(observed_index, monkeypatch):
    index, coverage = observed_index
    legacy = FlightIndex(index.path, track_cache_bytes=0)
    legacy._prepared_tracks = False
    expected = queried(legacy, coverage)
    fast = FlightIndex(index.path, track_cache_bytes=0)
    calls = []
    from dopplergeist import flight_payload
    original = flight_payload.decode_track

    def counted(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(flight_payload, "decode_track", counted)
    actual = queried(fast, coverage)
    assert [signature(track) for track in actual] == [signature(track) for track in expected]
    assert len(calls) == len(expected)
    looked_up = list(fast.lookup([track.id for track in expected]))
    assert [signature(track) for track in looked_up] == [signature(track) for track in expected]
    assert len(calls) == 2 * len(expected)
    actual[0].time[0] += 1
    actual[0].spline.c[0, 0, 0] += 1
    actual[0].altitude_basis[0] = "caller modification"
    assert signature(next(fast.lookup([expected[0].id]))) == signature(expected[0])


def test_prepared_index_copy_preserves_source_and_input_identity(observed_index, tmp_path):
    index, coverage = observed_index
    before = data_access.sha256(index.path)
    destination = tmp_path / "prepared.sqlite"
    prepared = index.prepare(destination)
    assert data_access.sha256(index.path) == before
    assert prepared.report["input_hash"] == index.report["input_hash"]
    assert prepared.coverage_for(coverage["bounds"], coverage["time_range_s"]) == index.coverage_for(
        coverage["bounds"], coverage["time_range_s"])
    assert [signature(track) for track in queried(prepared, coverage)] == [
        signature(track) for track in queried(index, coverage)]
    with pytest.raises(FileExistsError):
        index.prepare(destination)


@pytest.mark.parametrize("bounds,times,nonempty", [
    ([-79., 35., -78., 36.], [1788899404., 1788900299.], True),
    ([-180., -90., 180., 90.], [1788899404.72, 1788899405.], True),
    ([-180., -90., 180., 90.], [0., 1.], False),
])
def test_scoped_preparation_preserves_all_query_and_lookup_tracks(
        observed_index, tmp_path, monkeypatch, bounds, times, nonempty):
    index, coverage = observed_index
    prepared = index.prepare(tmp_path / "scoped.sqlite", prepare_scope=(bounds, times))
    with index.connect() as db:
        complete_rows = dict(db.execute("SELECT id,payload FROM prepared_tracks"))
    with prepared.connect() as db:
        scoped_rows = dict(db.execute("SELECT id,payload FROM prepared_tracks"))
    assert bool(scoped_rows) is nonempty
    assert len(scoped_rows) < len(complete_rows)
    assert all(payload == complete_rows[identifier] for identifier, payload in scoped_rows.items())
    assert prepared.report["prepared_tracks"]["scope"] == {"bounds": bounds, "time_range_s": times}
    assert prepared.report["input_hash"] == index.report["input_hash"]
    assert prepared.coverage_for(coverage["bounds"], coverage["time_range_s"]) == index.coverage_for(
        coverage["bounds"], coverage["time_range_s"])
    legacy = FlightIndex(index.path, track_cache_bytes=0)
    legacy._prepared_tracks = False
    expected = queried(legacy, coverage)
    reader = FlightIndex(prepared.path, track_cache_bytes=0)
    from dopplergeist import flight_payload
    decode, calls = flight_payload.decode_track, []

    def counted(*args, **kwargs):
        calls.append(args[0])
        return decode(*args, **kwargs)

    monkeypatch.setattr(flight_payload, "decode_track", counted)
    assert [signature(track) for track in queried(reader, coverage)] == [signature(track) for track in expected]
    assert [signature(track) for track in reader.lookup([track.id for track in expected])] == [
        signature(track) for track in expected]
    assert len(calls) == 2 * len(scoped_rows)


def test_scoped_build_retains_every_original_segment(observed_index, tmp_path):
    index, coverage = observed_index
    source = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    frame = pd.DataFrame(json.loads(source.read_text()))
    scoped = FlightIndex.build(tmp_path / "scoped-build.sqlite", [frame], sources=[], coverage=coverage,
                               prepare_scope=([-79., 35., -78., 36.], coverage["time_range_s"]))
    for table in ("segments", "spatial"):
        with index.connect() as db:
            original = db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        with scoped.connect() as db:
            assert db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() == original
    assert scoped.report["input_hash"] == index.report["input_hash"]
    assert scoped.report["rows"] == index.report["rows"]
    assert 0 < scoped.report["prepared_tracks"]["tracks"] < index.report["prepared_tracks"]["tracks"]


def test_prepare_and_build_coordinate_the_destination(observed_index, tmp_path, monkeypatch):
    index, coverage = observed_index
    original_lock, locks = data_access.cache_lock, []

    @contextmanager
    def recorded_lock(path):
        locks.append(Path(path))
        with original_lock(path):
            yield

    monkeypatch.setattr(data_access, "cache_lock", recorded_lock)
    before = data_access.sha256(index.path)
    destination = tmp_path / "shared-destination.sqlite"
    prepared = index.prepare(destination)
    reused = FlightIndex.build(destination, [], sources=[], coverage=coverage)
    assert len(locks) == 2 and locks[0] == locks[1]
    assert prepared.report["input_hash"] == reused.report["input_hash"] == index.report["input_hash"]
    assert data_access.sha256(index.path) == before


def test_prepare_uses_metadata_from_the_copied_snapshot(observed_index, tmp_path):
    index, _ = observed_index
    with sqlite3.connect(index.path) as db:
        original = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        original["snapshot_note"] = "Same archived observations; updated report note"
        db.execute("UPDATE metadata SET value=?", (json.dumps(original),))
    before = data_access.sha256(index.path)
    index.report["coverage"]["all_aircraft"] = True
    index.report["input_hash"] = "caller-modified-report"
    prepared = index.prepare(tmp_path / "snapshot.sqlite")
    assert {key: value for key, value in prepared.report.items() if key != "prepared_tracks"} == {
        key: value for key, value in original.items() if key != "prepared_tracks"}
    assert data_access.sha256(index.path) == before


def test_prepared_reader_falls_back_after_implementation_change(observed_index, monkeypatch):
    index, coverage = observed_index
    expected = [signature(track) for track in queried(index, coverage)]
    monkeypatch.setattr(data_access, "_prepared_track_identity", lambda: "other-normalization-build")
    reader = FlightIndex(index.path, track_cache_bytes=0)
    assert reader._prepared_tracks is False
    assert [signature(track) for track in queried(reader, coverage)] == expected


def test_reader_rechecks_changed_preparation_metadata(observed_index, monkeypatch):
    index, coverage = observed_index
    expected = queried(index, coverage)
    reader = FlightIndex(index.path, track_cache_bytes=0)
    with sqlite3.connect(index.path) as db:
        report = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        report["prepared_tracks"]["builder"] = "other-normalization-build"
        db.execute("UPDATE metadata SET value=?", (json.dumps(report),))
    from dopplergeist import flight_payload

    def unavailable(*args, **kwargs):
        pytest.fail("Stale preparation metadata reached the numeric decoder")

    monkeypatch.setattr(flight_payload, "decode_track", unavailable)
    assert [signature(track) for track in queried(reader, coverage)] == [
        signature(track) for track in expected]
    assert [signature(track) for track in reader.lookup([track.id for track in expected])] == [
        signature(track) for track in expected]


@pytest.mark.parametrize("damaged,repair_digest", [
    (b"invalid prepared representation", False),
    (b"invalid prepared representation", True),
    ("wrong SQLite storage type", False),
    (17, False),
])
def test_damaged_optional_payload_uses_verified_original(observed_index, damaged, repair_digest):
    index, coverage = observed_index
    expected = [signature(track) for track in queried(index, coverage)]
    with sqlite3.connect(index.path) as db:
        if repair_digest:
            db.execute("UPDATE prepared_tracks SET payload=?,payload_hash=?",
                       (damaged, hashlib.sha256(damaged).hexdigest()))
        else:
            db.execute("UPDATE prepared_tracks SET payload=?", (damaged,))
    reader = FlightIndex(index.path, track_cache_bytes=0)
    assert [signature(track) for track in queried(reader, coverage)] == expected


@pytest.mark.parametrize("replacement", [
    None,
    "CREATE TABLE prepared_tracks(id INTEGER PRIMARY KEY, payload BLOB)",
    "CREATE TABLE prepared_tracks(id INTEGER, source_hash TEXT, payload BLOB, payload_hash TEXT)",
])
@pytest.mark.parametrize("opened_before_damage", [False, True])
def test_missing_or_malformed_optional_table_uses_original(observed_index, replacement, opened_before_damage):
    index, coverage = observed_index
    expected = queried(index, coverage)
    reader = FlightIndex(index.path, track_cache_bytes=0) if opened_before_damage else None
    with sqlite3.connect(index.path) as db:
        db.execute("DROP TABLE prepared_tracks")
        if replacement is not None:
            db.execute(replacement)
    if reader is None:
        reader = FlightIndex(index.path, track_cache_bytes=0)
        assert reader._prepared_tracks is False
    assert [signature(track) for track in queried(reader, coverage)] == [
        signature(track) for track in expected]
    assert [signature(track) for track in reader.lookup([track.id for track in expected])] == [
        signature(track) for track in expected]


def test_prepared_reader_does_not_hide_changed_original_payload(observed_index):
    index, coverage = observed_index
    first = queried(index, coverage)[0]
    with sqlite3.connect(index.path) as db:
        old = db.execute("SELECT payload FROM segments WHERE name=?", (first.id,)).fetchone()[0]
        changed = gzip.compress(gzip.decompress(old), mtime=1)
        db.execute("UPDATE segments SET payload=?,payload_hash=? WHERE name=?",
                   (changed, hashlib.sha256(changed).hexdigest(), first.id))
    reader = FlightIndex(index.path, track_cache_bytes=0)
    assert signature(next(reader.lookup([first.id]))) == signature(first)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE segments SET payload=? WHERE name=?", (b"damaged original", first.id))
    with pytest.raises(DataUnavailable, match="Corrupt flight payload"):
        list(reader.lookup([first.id]))


def test_prepared_lookup_preserves_sample_budget(observed_index):
    index, coverage = observed_index
    first = queried(index, coverage)[0]
    reader = FlightIndex(index.path, track_cache_bytes=0)
    with pytest.raises(DataUnavailable, match="Flight lookup sample budget exceeded"):
        list(reader.lookup([first.id], max_samples=len(first.time) - 1))
