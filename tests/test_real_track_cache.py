"""Track reuse checks using archived ADS-B observations, never generated tracks."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sqlite3
from threading import Barrier

import numpy as np
import pandas as pd
import pytest

from dopplergeist import data_access
from dopplergeist.data_access import DataUnavailable, FlightIndex


def snapshot_size(track):
    return len(pickle.dumps(track, protocol=pickle.HIGHEST_PROTOCOL))


@pytest.fixture
def real_index(tmp_path):
    source = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen/canonical-observations.json"
    frame = pd.DataFrame(json.loads(source.read_text()))
    coverage = {"bounds": [-180, -90, 180, 90],
                "time_range_s": [float(frame.time_s.min()), float(frame.time_s.max())],
                "all_aircraft": False, "source_note": "Archived real trajectory-motion observations; incomplete excerpt"}
    index = FlightIndex.build(tmp_path / "real.sqlite", [frame], sources=[], coverage=coverage)
    return index.path, coverage


def assert_tracks_equal(actual, expected):
    assert [track.id for track in actual] == [track.id for track in expected]
    for got, want in zip(actual, expected):
        assert got is not want
        for name in ("time", "lat", "lon", "altitude", "velocity", "xyz", "_xyz_min", "_xyz_max",
                     "relative_time", "_speed_upper", "_speed_peak"):
            if getattr(want, name) is None:
                assert getattr(got, name) is None
            else:
                np.testing.assert_array_equal(getattr(got, name), getattr(want, name))
        for name in ("spline", "derivative"):
            np.testing.assert_array_equal(getattr(got, name).c, getattr(want, name).c)
            np.testing.assert_array_equal(getattr(got, name).x, getattr(want, name).x)
        for name in ("typecode", "origin", "_max_sample_gap", "aircraft_class", "altitude_basis",
                     "velocity_inferred_components"):
            assert getattr(got, name) == getattr(want, name)


def test_real_query_and_lookup_reuse_track_setup(real_index, monkeypatch):
    path, coverage = real_index
    expected = list(FlightIndex(path, track_cache_bytes=0).query(coverage["bounds"], coverage["time_range_s"]))
    original, calls = data_access._frame_track, []

    def decode(name, frame):
        calls.append(name)
        return original(name, frame)

    monkeypatch.setattr(data_access, "_frame_track", decode)
    cached = FlightIndex(path)
    first = list(cached.query(coverage["bounds"], coverage["time_range_s"]))
    assert_tracks_equal(first, expected)
    assert len(calls) == len(expected) > 0
    second = list(cached.query(coverage["bounds"], coverage["time_range_s"]))
    looked_up = list(cached.lookup(track.id for track in expected))
    assert_tracks_equal(second, expected)
    assert_tracks_equal(looked_up, expected)
    assert len(calls) == len(expected)
    assert cached._track_cache_bytes <= cached._track_cache_limit


def test_real_cached_tracks_do_not_share_caller_mutations(real_index):
    path, coverage = real_index
    expected = list(FlightIndex(path, track_cache_bytes=0).query(coverage["bounds"], coverage["time_range_s"]))
    cached = FlightIndex(path)
    for _ in range(2):  # Exercise both the initial return and a cache hit.
        got = list(cached.query(coverage["bounds"], coverage["time_range_s"]))
        assert_tracks_equal(got, expected)
        got[0].time[0] += 1
        got[0].spline.c[0, 0, 0] += 1
        got[0]._speed_peak[:] = 0
        got[0].altitude_basis[0] = "caller changed label"
        got[0].velocity_inferred_components["east_mps"] = -1
    assert_tracks_equal(list(cached.lookup(track.id for track in expected)), expected)


def test_real_cache_hit_still_checks_payload_integrity(real_index):
    path, coverage = real_index
    cached = FlightIndex(path)
    track = next(cached.query(coverage["bounds"], coverage["time_range_s"]))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE segments SET payload=? WHERE name=?", (b"corrupted index payload", track.id))
    with pytest.raises(DataUnavailable, match="Corrupt flight payload"):
        list(cached.lookup([track.id]))


def test_real_cache_observes_replaced_payload(real_index, monkeypatch):
    path, coverage = real_index
    cached = FlightIndex(path)
    expected = next(cached.query(coverage["bounds"], coverage["time_range_s"]))
    with sqlite3.connect(path) as db:
        old = db.execute("SELECT payload FROM segments WHERE name=?", (expected.id,)).fetchone()[0]
        # Change only the gzip header; every archived observation is unchanged.
        payload = gzip.compress(gzip.decompress(old), compresslevel=6, mtime=1)
        assert payload != old
        db.execute("UPDATE segments SET payload=?,payload_hash=? WHERE name=?",
                   (payload, hashlib.sha256(payload).hexdigest(), expected.id))
    original, calls = data_access._frame_track, []

    def decode(name, frame):
        calls.append(name)
        return original(name, frame)

    monkeypatch.setattr(data_access, "_frame_track", decode)
    assert_tracks_equal(list(cached.lookup([expected.id])), [expected])
    assert calls == [expected.id]


def test_real_cache_evicts_and_skips_oversized_tracks(real_index, monkeypatch):
    path, coverage = real_index
    tracks = list(FlightIndex(path, track_cache_bytes=0).query(coverage["bounds"], coverage["time_range_s"]))
    first, second = tracks[:2]
    sizes = [snapshot_size(track) for track in (first, second)]
    cached = FlightIndex(path, track_cache_bytes=max(sizes))
    original, calls = data_access._frame_track, []

    def decode(name, frame):
        calls.append(name)
        return original(name, frame)

    monkeypatch.setattr(data_access, "_frame_track", decode)
    for track in (first, second, first):
        assert_tracks_equal(list(cached.lookup([track.id])), [track])
        assert len(cached._track_cache) == 1
        assert cached._track_cache_bytes <= max(sizes)
    assert calls == [first.id, second.id, first.id]
    too_small = FlightIndex(path, track_cache_bytes=min(sizes) - 1)
    assert_tracks_equal(list(too_small.lookup([first.id])), [first])
    assert not too_small._track_cache
    assert too_small._track_cache_bytes == 0


def test_real_query_larger_than_cache_keeps_a_reusable_subset(real_index, monkeypatch):
    path, coverage = real_index
    expected = list(FlightIndex(path, track_cache_bytes=0).query(coverage["bounds"], coverage["time_range_s"]))
    size = snapshot_size(expected[0])
    cached = FlightIndex(path, track_cache_bytes=size)
    original, calls = data_access._frame_track, []
    serialize, snapshots = data_access.pickle.dumps, []

    def decode(name, frame):
        calls.append(name)
        return original(name, frame)

    def snapshot(track, **kwargs):
        snapshots.append(track.id)
        return serialize(track, **kwargs)

    monkeypatch.setattr(data_access, "_frame_track", decode)
    monkeypatch.setattr(data_access.pickle, "dumps", snapshot)
    assert_tracks_equal(list(cached.query(coverage["bounds"], coverage["time_range_s"])), expected)
    assert len(calls) == len(expected)
    assert len(cached._track_cache) == 1
    assert next(iter(cached._track_cache))[0] == expected[0].id
    assert_tracks_equal(list(cached.query(coverage["bounds"], coverage["time_range_s"])), expected)
    assert len(calls) == 2 * len(expected) - 1
    assert cached._track_cache_bytes == size
    assert len(snapshots) < len(calls)  # Admission failure avoids work on later misses.


def test_real_lookup_sample_budget_precedes_track_allocation(real_index, monkeypatch):
    path, coverage = real_index
    cached = FlightIndex(path)
    track = next(cached.query(coverage["bounds"], coverage["time_range_s"]))

    def must_not_decode(*args, **kwargs):
        raise AssertionError("Over-budget lookup allocated a Track")

    monkeypatch.setattr(data_access, "_frame_track", must_not_decode)
    monkeypatch.setattr(data_access.pickle, "loads", must_not_decode)
    for index in (cached, FlightIndex(path, track_cache_bytes=0)):
        with pytest.raises(DataUnavailable, match="Flight lookup sample budget exceeded"):
            list(index.lookup([track.id], max_samples=len(track.time) - 1))


def test_real_concurrent_cache_misses_do_not_double_count(real_index, monkeypatch):
    path, coverage = real_index
    expected = next(FlightIndex(path, track_cache_bytes=0).query(coverage["bounds"], coverage["time_range_s"]))
    cached = FlightIndex(path)
    original, ready = data_access._frame_track, Barrier(4)

    def concurrent_decode(name, frame):
        track = original(name, frame)
        # Force concurrent misses for one real payload. This also checks that
        # expensive decoding is outside the cache lock, rather than serializing it.
        ready.wait(timeout=10)
        return track

    monkeypatch.setattr(data_access, "_frame_track", concurrent_decode)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: list(cached.lookup([expected.id])), range(4)))
    for result in results:
        assert_tracks_equal(result, [expected])
    assert len(cached._track_cache) == 1
    assert cached._track_cache_bytes == sum(len(value[1]) for value in cached._track_cache.values())
    assert cached._track_cache_bytes <= cached._track_cache_limit
