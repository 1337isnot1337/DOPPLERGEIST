"""Named refinement reads against actual indexed aircraft observations."""
import json
import os
from pathlib import Path
import shutil
import sqlite3

import numpy as np
import pytest

from dopplergeist.automatic import _refinement_tracks
from dopplergeist.data_access import DataUnavailable, FlightIndex


@pytest.fixture(scope="module")
def recorded_index():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a recorded-data diagnostic")
    fixture = json.loads(Path(source).read_text())
    index = FlightIndex(fixture["real_index"])
    assert index.report["input_hash"] == fixture["index_input_hash"]
    bounds, times = fixture["query_bounds"], fixture["query_time_s"]
    observed = list(index.query(bounds, times))
    assert observed, "The recorded workload contains no trajectories"
    assert [track.id for track in observed] == sorted(fixture["track_ids"])
    return index, bounds, times, observed


def same_tracks(actual, expected):
    assert [track.id for track in actual] == [track.id for track in expected]
    for left, right in zip(actual, expected):
        for name in ("time", "lat", "lon", "altitude", "xyz", "relative_time", "velocity"):
            a, b = getattr(left, name), getattr(right, name)
            if a is None or b is None:
                assert a is b
            else:
                np.testing.assert_array_equal(a, b, strict=True)
        np.testing.assert_array_equal(left.spline.c, right.spline.c, strict=True)
        np.testing.assert_array_equal(left.derivative.c, right.derivative.c, strict=True)
        assert left.origin == right.origin
        for name in ("typecode", "altitude_basis", "aircraft_class", "velocity_inferred_components"):
            assert getattr(left, name) == getattr(right, name)


def test_named_envelope_matches_broad_query_across_sql_batches(recorded_index):
    index, bounds, times, observed = recorded_index
    with index.connect() as database:
        names = [row[0] for row in database.execute("SELECT name FROM segments ORDER BY name LIMIT 650")]
    # The real index contains enough names to cross the 500-parameter batch.
    assert len(names) > 500
    names = sorted(set(names) | {track.id for track in observed[:6]})
    requested = names[::-1] + names[:3] + ["missing-recorded-segment"]
    selected = set(requested)
    expected = [track for track in observed if track.id in selected]
    actual = list(index.lookup(requested, bounds=bounds, time_range=times))
    same_tracks(actual, expected)


def test_named_envelope_preserves_spatial_time_filters_and_old_index_fallback(recorded_index):
    original, bounds, times, observed = recorded_index
    index = FlightIndex(original.path)
    names = [track.id for track in observed[:6]]
    # A disjoint geographic envelope and out-of-day time query expose accidental
    # removal of either predicate without manufacturing trajectory observations.
    disjoint = (bounds[0] + 20, bounds[1], bounds[2] + 20, bounds[3])
    outside_time = (index.report["coverage"]["time_range_s"][1] + 86400,) * 2
    for box, window in ((disjoint, times), (bounds, outside_time),
                        (bounds, (observed[0].time[0], observed[0].time[0]))):
        expected = [track for track in index.query(box, window) if track.id in names]
        if window == outside_time:
            assert not expected
        if window == (observed[0].time[0], observed[0].time[0]):
            assert observed[0].id in {track.id for track in expected}
        same_tracks(list(index.lookup(names, bounds=box, time_range=window)), expected)
    # Older index metadata must disable spatial pruning in both entry points.
    index.report["continuous_geometry_bounds"] = False
    expected = [track for track in index.query(disjoint, times) if track.id in names]
    assert [track.id for track in expected] == names
    same_tracks(list(index.lookup(names, bounds=disjoint, time_range=times)), expected)
    index.report["continuous_geometry_bounds"] = True
    index.report["normalizer_sha256"] = "different-normalizer-version"
    same_tracks(list(index.lookup(names, bounds=disjoint, time_range=times)), expected)


def test_refinement_adapter_duplicates_and_sample_budget(recorded_index):
    index, bounds, times, observed = recorded_index
    needed = {track.id for track in observed[:6]}
    expected = [track for track in observed if track.id in needed]
    sample_limit = sum(len(track.time) for track in expected)

    class QueryAdapter:
        def query(self, box, window):
            assert tuple(box) == tuple(bounds) and tuple(window) == tuple(times)
            yield from observed

    for indexes in ([index], [index, index], [QueryAdapter()], [index, QueryAdapter()]):
        actual = _refinement_tracks(indexes, needed, bounds, times, sample_limit)
        same_tracks(list(actual.values()), expected)
        with pytest.raises(ValueError, match="^Refinement trajectory sample budget exceeded$"):
            _refinement_tracks(indexes, needed, bounds, times, sample_limit - 1)
    assert _refinement_tracks([index], {"missing-recorded-segment"}, bounds, times, 1) == {}


def test_named_envelope_requires_complete_scope_and_checks_payload(recorded_index, tmp_path):
    index, bounds, times, observed = recorded_index
    name = observed[0].id
    for settings in ({"bounds": bounds}, {"time_range": times}):
        with pytest.raises(ValueError, match="must be supplied together"):
            list(index.lookup([name], **settings))
    path = tmp_path / "corrupt-index.sqlite"
    shutil.copyfile(index.path, path)
    with sqlite3.connect(path) as database:
        database.execute("UPDATE segments SET payload_hash=? WHERE name=?", ("corrupt", name))
    with pytest.raises(DataUnavailable, match="Corrupt flight payload"):
        list(FlightIndex(path).lookup([name], bounds=bounds, time_range=times))
