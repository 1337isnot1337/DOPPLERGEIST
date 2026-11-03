"""Index decoding parity on unchanged archived ADS-B observations."""
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist import data_access


def _assert_track_equal(got, expected):
    assert vars(got).keys() == vars(expected).keys()
    for name, value in vars(expected).items():
        actual = getattr(got, name)
        if isinstance(value, np.ndarray):
            assert actual.dtype == value.dtype and actual.shape == value.shape
            assert actual.tobytes() == value.tobytes(), name
        elif name in {"spline", "derivative"}:
            assert actual.c.tobytes() == value.c.tobytes(), name
            assert actual.x.tobytes() == value.x.tobytes(), name
            assert actual.axis == value.axis and actual.extrapolate == value.extrapolate
        else:
            assert actual == value, name


def _recorded_segments():
    root = Path(__file__).resolve().parents[1] / "research/trajectory-motion/frozen"
    for source in sorted(root.glob("fresh-*.json")):
        rows = sorted(json.loads(source.read_text()), key=lambda row: row["time_s"])
        chunks = [[]]
        for row in rows:
            if chunks[-1] and row["time_s"] - chunks[-1][-1]["time_s"] > 30:
                chunks.append([])
            chunks[-1].append(row)
        for number, chunk in enumerate(chunks):
            if len(chunk) >= 3:
                yield f"{source.stem}:{number}", chunk


def test_recorded_columns_preserve_arrays_labels_and_velocity_inference():
    checked, inferred = 0, 0
    for name, records in _recorded_segments():
        frame = data_access._payload_frame(records)
        assert isinstance(frame, data_access._IndexColumns)
        expected = data_access._frame_track(name, pd.DataFrame(records))
        actual = data_access._frame_track(name, frame)
        _assert_track_equal(actual, expected)
        inferred += sum(actual.velocity_inferred_components.values())
        checked += 1
    assert checked >= 4 and inferred > 0


def test_noncanonical_column_representations_keep_pandas():
    name, recorded = next(_recorded_segments())
    # Numeric representations and optional labels change; every observed
    # position, time and velocity value remains the same.
    numeric = deepcopy(recorded)
    numeric[0]["time_s"] = np.float64(numeric[0]["time_s"])
    absent_label = deepcopy(recorded)
    del absent_label[0]["typecode"]
    null_label = deepcopy(recorded)
    null_label[0]["altitude_basis"] = None
    for records in (numeric, absent_label, null_label):
        actual = data_access._payload_frame(records)
        assert isinstance(actual, pd.DataFrame)
        pd.testing.assert_frame_equal(actual, pd.DataFrame(records))


def test_indexed_recorded_payloads_preserve_all_track_fields():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to a recorded-input workload")
    fixture = json.loads(Path(source).read_text())
    index = data_access.FlightIndex(fixture["real_index"])
    requested = set(fixture["track_ids"])
    checked = fast = 0
    with index.connect() as db:
        for name, payload in db.execute("SELECT name,payload FROM segments ORDER BY name"):
            if name not in requested:
                continue
            records = json.loads(gzip.decompress(payload))
            frame = data_access._payload_frame(records)
            fast += isinstance(frame, data_access._IndexColumns)
            actual = data_access._frame_track(name, frame)
            expected = data_access._frame_track(name, pd.DataFrame(records))
            _assert_track_equal(actual, expected)
            checked += 1
    assert checked == len(requested) and checked > 0 and fast > 0
