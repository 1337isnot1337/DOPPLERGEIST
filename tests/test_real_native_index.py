"""Native column parity on real ADS-B rows and unchanged representations."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from dopplergeist import data_access

ROOT = Path(__file__).resolve().parents[1]
RECORDED = sorted((ROOT / "research/trajectory-motion/frozen").glob("fresh-*.json"))


@pytest.fixture(scope="module")
def native_index():
    return pytest.importorskip("dopplergeist._native_index")


def recorded_rows():
    assert RECORDED, "The archived real observations are required"
    return json.loads(RECORDED[0].read_text())


def assert_same_columns(actual, expected):
    assert type(actual) is type(expected)
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        return
    assert list(actual.columns) == list(expected.columns)
    assert len(actual) == len(expected)
    for name, column in expected.columns.items():
        wanted, got = column.values, actual.columns[name].values
        assert got.dtype == wanted.dtype and got.shape == wanted.shape, name
        if got.dtype.hasobject:
            assert got.tolist() == wanted.tolist(), name
        else:
            assert got.tobytes() == wanted.tobytes(), name


def compare_python_and_native(records, native_index, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(data_access, "_native_payload_columns", None)
        expected = data_access._payload_frame(records)
    with monkeypatch.context() as patch:
        patch.setattr(data_access, "_native_payload_columns", native_index.payload_columns)
        actual = data_access._payload_frame(records)
    assert_same_columns(actual, expected)
    return actual


@pytest.mark.parametrize("source", RECORDED, ids=lambda source: source.stem)
def test_native_recorded_columns_match_python_bytes(source, native_index, monkeypatch):
    records = json.loads(source.read_text())
    before = native_index.successful_calls()
    frame = compare_python_and_native(records, native_index, monkeypatch)
    assert isinstance(frame, data_access._IndexColumns)
    assert native_index.successful_calls() == before + 1


def test_recorded_null_and_absent_optional_columns(native_index, monkeypatch):
    records = recorded_rows()
    assert any(row["east_mps"] is None for row in records)
    compare_python_and_native(records, native_index, monkeypatch)
    for name in data_access._PAYLOAD_COLUMNS[4:]:
        without = [{key: value for key, value in row.items() if key != name} for row in records]
        columns = native_index.payload_columns(without)
        assert columns is not None
        assert columns[data_access._PAYLOAD_COLUMNS.index(name)] is None
        frame = compare_python_and_native(without, native_index, monkeypatch)
        assert name not in frame


def test_real_noncanonical_representations_keep_python_fallback(native_index, monkeypatch):
    records = recorded_rows()
    variants = []
    for row_index in (0, -1):
        missing_optional = deepcopy(records)
        del missing_optional[row_index]["typecode"]
        variants.append(missing_optional)
    numeric_scalar = deepcopy(records)
    numeric_scalar[-1]["time_s"] = np.float64(numeric_scalar[-1]["time_s"])
    variants.append(numeric_scalar)

    class RecordedRow(dict):
        pass

    mapping_subclass = deepcopy(records)
    mapping_subclass[-1] = RecordedRow(mapping_subclass[-1])
    variants.extend((mapping_subclass, tuple(records)))
    for changed in variants:
        assert native_index.payload_columns(changed) is None
        compare_python_and_native(changed, native_index, monkeypatch)


def test_native_output_containers_do_not_mutate_recorded_input(native_index, monkeypatch):
    records = recorded_rows()
    original = deepcopy(records)
    first = native_index.payload_columns(records)
    second = native_index.payload_columns(records)
    assert first is not None and second is not None
    for left, right in zip(first, second):
        if left is not None:
            assert left is not right
            left.clear()
    assert records == original
    assert second[0] == [row["time_s"] for row in records]
    compare_python_and_native(records, native_index, monkeypatch)


def test_native_success_and_partial_fallback_release_references(native_index):
    records = recorded_rows()
    watched = records[0]["time_s"]
    before = sys.getrefcount(watched)
    columns = native_index.payload_columns(records)
    assert columns[0][0] is watched
    assert sys.getrefcount(watched) == before + 1
    del columns
    assert sys.getrefcount(watched) == before

    # A late mismatch leaves earlier list slots populated. Representation
    # changes preserve all recorded positions, timestamps and velocities.
    for name in ("lat", "typecode"):
        changed = deepcopy(records)
        del changed[-1][name]
        watched_values = (changed[0]["time_s"], changed[-1]["time_s"], changed[0]["typecode"])
        before = tuple(sys.getrefcount(value) for value in watched_values)
        for _ in range(32):
            assert native_index.payload_columns(changed) is None
        after = tuple(sys.getrefcount(value) for value in watched_values)
        assert after == before


def test_previous_real_prepared_index_stays_usable(monkeypatch):
    import os
    path = os.environ.get("DOPPLERGEIST_REAL_PREVIOUS_PREPARED_INDEX")
    if not path:
        pytest.skip("set a completed prepared index built by the previous source")
    from dopplergeist import index_compatibility
    from test_real_prepared_index import signature

    prepared = data_access.FlightIndex(path, track_cache_bytes=0)
    assert prepared._prepared_tracks
    # Reopening an older compatible index must not continually rehash the
    # numerical runtime as the bounded identity cache cycles through versions.
    data_access._prepared_track_identity.cache_clear()
    assert data_access.FlightIndex(path, track_cache_bytes=0)._prepared_tracks
    misses = data_access._prepared_track_identity.cache_info().misses
    assert data_access.FlightIndex(path, track_cache_bytes=0)._prepared_tracks
    assert data_access._prepared_track_identity.cache_info().misses == misses
    scope = prepared.report["prepared_tracks"]["scope"]
    expected = data_access.FlightIndex(path, track_cache_bytes=0)
    expected._prepared_tracks = False
    expected_tracks = list(expected.query(scope["bounds"], scope["time_range_s"]))
    actual_tracks = list(prepared.query(scope["bounds"], scope["time_range_s"]))
    assert expected_tracks
    assert [signature(track) for track in actual_tracks] == [signature(track) for track in expected_tracks]
    with monkeypatch.context() as patch:
        patch.setattr(data_access, "_native_payload_columns", None)
        assert data_access.FlightIndex(path, track_cache_bytes=0)._prepared_tracks
    with monkeypatch.context() as patch:
        patch.setattr(index_compatibility, "PREPARED_DATA_ACCESS_EQUIVALENCE", {})
        assert not data_access.FlightIndex(path, track_cache_bytes=0)._prepared_tracks
