"""Prepared payload parity and corruption checks on archived observations."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist import flight_payload
from dopplergeist.data_access import DataUnavailable, _frame_track


@pytest.fixture(scope="module")
def observed_tracks():
    root = Path(__file__).resolve().parents[1]
    tracks = []
    for source in sorted((root / "research/trajectory-motion/frozen").glob("fresh-*.json")):
        frame = pd.DataFrame(json.loads(source.read_text())).sort_values("time_s")
        for number, (_, rows) in enumerate(frame.groupby((frame.time_s.diff() > 30.).cumsum())):
            if len(rows) >= 3:
                tracks.append(_frame_track(f"{rows.flight_id.iloc[0]}:{number}", rows))
    assert tracks
    return tracks


def assert_exact_track(actual, expected):
    assert actual.id == expected.id and actual.typecode == expected.typecode
    for name in ("time", "lat", "lon", "altitude", "velocity", "xyz", "relative_time",
                 "_xyz_min", "_xyz_max", "_speed_upper", "_speed_peak"):
        left, right = getattr(actual, name), getattr(expected, name)
        if right is None:
            assert left is None
        else:
            assert left.dtype == right.dtype and left.shape == right.shape, name
            assert left.tobytes() == right.tobytes(), name
    for name in ("spline", "derivative"):
        left, right = getattr(actual, name), getattr(expected, name)
        assert left.axis == right.axis and left.extrapolate == right.extrapolate
        for field in ("x", "c"):
            assert getattr(left, field).tobytes() == getattr(right, field).tobytes()
    for name in ("origin", "_max_sample_gap", "altitude_basis", "aircraft_class",
                 "velocity_inferred_components"):
        assert getattr(actual, name) == getattr(expected, name), name


def test_observed_tracks_round_trip_exactly(observed_tracks):
    for expected in observed_tracks:
        payload = flight_payload.encode_track(expected)
        actual = flight_payload.decode_track(expected.id, payload)
        assert_exact_track(actual, expected)
        for name in ("time", "lat", "lon", "altitude", "velocity"):
            array = getattr(actual, name)
            if array is not None:
                assert array.flags.writeable and array.flags.c_contiguous


def test_missing_velocity_uses_same_recorded_positions(observed_tracks):
    original = observed_tracks[0]
    frame = pd.DataFrame({"time_s": original.time, "lat": original.lat,
                          "lon": original.lon, "alt_m": original.altitude})
    expected = _frame_track(original.id, frame)
    assert expected.velocity is None
    actual = flight_payload.decode_track(expected.id, flight_payload.encode_track(expected))
    assert_exact_track(actual, expected)


def test_decoded_tracks_are_independently_mutable(observed_tracks):
    expected = observed_tracks[0]
    payload = flight_payload.encode_track(expected)
    changed = flight_payload.decode_track(expected.id, payload)
    untouched = flight_payload.decode_track(expected.id, payload)
    changed.time[0] = np.nextafter(changed.time[0], np.inf)
    changed.altitude[0] += 1.
    if changed.velocity is not None:
        changed.velocity[0, 0] += 1.
    changed.altitude_basis[0] = "changed"
    changed.velocity_inferred_components["east_mps"] += 1
    assert_exact_track(untouched, expected)
    assert_exact_track(flight_payload.decode_track(expected.id, payload), expected)


def _header_variant(payload, mutate):
    magic, version, size, count = flight_payload._PREFIX.unpack_from(payload)
    first = flight_payload._PREFIX.size
    metadata = json.loads(payload[first:first+size])
    mutate(metadata)
    header = json.dumps(metadata, separators=(",", ":")).encode()
    return (flight_payload._PREFIX.pack(magic, version, len(header), count)
            + header + payload[first+size:])


def test_invalid_sizes_types_and_metadata_fail(observed_tracks):
    track = observed_tracks[0]
    payload = flight_payload.encode_track(track)
    magic, version, size, count = flight_payload._PREFIX.unpack_from(payload)
    invalid = [b"", payload[:-1], payload+b"x", b"x"+payload[1:], bytearray(payload),
               flight_payload._PREFIX.pack(magic, version+1, size, count)+payload[flight_payload._PREFIX.size:],
               flight_payload._PREFIX.pack(magic, version, flight_payload._MAX_HEADER_BYTES+1, count),
               flight_payload._PREFIX.pack(magic, version, size, flight_payload._MAX_SAMPLES+1)]
    for change in (
        lambda meta: meta.update(extra=True),
        lambda meta: meta.update(velocity=1),
        lambda meta: meta.update(aircraft_class=None),
        lambda meta: meta["velocity_inferred_components"].update(east_mps=True),
        lambda meta: meta.update(altitude_basis=[["ellipsoidal", count+1]]),
        lambda meta: meta.update(altitude_basis=[["ellipsoidal", -1]]),
    ):
        invalid.append(_header_variant(payload, change))
    for damaged in invalid:
        with pytest.raises(DataUnavailable):
            flight_payload.decode_track(track.id, damaged)
    with pytest.raises(DataUnavailable):
        flight_payload.decode_track(track.id+"-other", payload)
    with pytest.raises(DataUnavailable, match="sample budget exceeded"):
        flight_payload.decode_track(track.id, payload, max_samples=count-1)
    assert_exact_track(flight_payload.decode_track(track.id, payload, max_samples=count), track)


def test_nonfinite_numeric_payload_is_rejected(observed_tracks):
    track = observed_tracks[0]
    payload = flight_payload.encode_track(track)
    _, _, size, _ = flight_payload._PREFIX.unpack_from(payload)
    first = flight_payload._PREFIX.size+size
    damaged = payload[:first] + np.array([np.nan], dtype="<f8").tobytes() + payload[first+8:]
    with pytest.raises(DataUnavailable, match="invalid trajectory values"):
        flight_payload.decode_track(track.id, damaged)
