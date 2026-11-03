"""Bounded numeric snapshots of canonical flight-decoder inputs.

Encode a Track reconstructed from the stored JSON payload. The original payload
and its integrity/implementation checks remain the caller's responsibility. The
snapshot stores float64 inputs and labels; Track reconstructs its spline and
private caches on every decode. No executable object format is read from disk.
"""
import json
import struct

import numpy as np

from .geometry import Track


FORMAT_VERSION = 1
_MAGIC = b"DGFLT64\0"
_PREFIX = struct.Struct("<8sIIQ")
_MAX_SAMPLES = 1_000_000
_MAX_HEADER_BYTES = 1024 * 1024
_MAX_PAYLOAD_BYTES = _PREFIX.size + _MAX_HEADER_BYTES + 7 * 8 * _MAX_SAMPLES
_MAX_LABEL_LENGTH = 1024
_COMPONENTS = ("east_mps", "north_mps", "up_mps")
_FIELDS = {"id", "typecode", "aircraft_class", "altitude_basis",
           "velocity_inferred_components", "velocity"}


def _invalid(reason):
    # data_access may import this codec while defining FlightIndex.
    from .data_access import DataUnavailable
    return DataUnavailable(f"Invalid prepared flight payload: {reason}")


def _label(value):
    return type(value) is str and len(value) <= _MAX_LABEL_LENGTH


def _metadata(track, count):
    if not all(_label(value) for value in (track.id, track.typecode,
                                           getattr(track, "aircraft_class", None))):
        raise _invalid("noncanonical flight labels")
    basis = getattr(track, "altitude_basis", None)
    if type(basis) is not list or len(basis) != count:
        raise _invalid("altitude labels do not match the trajectory")
    runs = []
    # JSON escapes use at most six bytes per character. Bound metadata while
    # forming runs, before serializing a potentially large alternating list.
    header_bound = 512 + 6 * sum(len(value) for value in
                                (track.id, track.typecode, track.aircraft_class))
    for label in basis:
        if not _label(label):
            raise _invalid("noncanonical altitude label")
        if runs and runs[-1][0] == label:
            runs[-1][1] += 1
        else:
            header_bound += 6 * len(label) + 32
            if header_bound > _MAX_HEADER_BYTES:
                raise _invalid("metadata exceeds the codec limit")
            runs.append([label, 1])
    inferred = getattr(track, "velocity_inferred_components", None)
    if (type(inferred) is not dict or set(inferred) != set(_COMPONENTS)
            or any(type(inferred[key]) is not int or not 0 <= inferred[key] <= count
                   for key in _COMPONENTS)):
        raise _invalid("noncanonical velocity-inference counts")
    return {"id": track.id, "typecode": track.typecode,
            "aircraft_class": track.aircraft_class, "altitude_basis": runs,
            "velocity_inferred_components": {key: inferred[key] for key in _COMPONENTS},
            "velocity": track.velocity is not None}


def encode_track(track):
    """Encode exact inputs from a freshly decoded canonical Track.

    Noncanonical metadata or oversized trajectories are left to the original
    payload path. This function does not infer velocities or round any values.
    """
    if type(track) is not Track:
        raise _invalid("noncanonical Track type")
    if type(track.time) is not np.ndarray or track.time.ndim != 1:
        raise _invalid("noncanonical trajectory array")
    count = len(track.time)
    if not 3 <= count <= _MAX_SAMPLES:
        raise _invalid("trajectory sample count is outside the codec limit")
    arrays = [track.time, track.lat, track.lon, track.altitude]
    for values in arrays:
        if (type(values) is not np.ndarray or values.dtype != np.dtype(float)
                or values.shape != (count,) or not np.all(np.isfinite(values))):
            raise _invalid("noncanonical trajectory array")
    if not np.all(np.diff(track.time) > 0):
        raise _invalid("trajectory times are not strictly increasing")
    if track.velocity is not None:
        velocity = track.velocity
        if (type(velocity) is not np.ndarray or velocity.dtype != np.dtype(float)
                or velocity.shape != (count, 3) or not np.all(np.isfinite(velocity))):
            raise _invalid("noncanonical velocity array")
        arrays.append(velocity)
    try:
        header = json.dumps(_metadata(track, count), ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as error:
        raise _invalid("noncanonical metadata encoding") from error
    if len(header) > _MAX_HEADER_BYTES:
        raise _invalid("metadata exceeds the codec limit")
    return b"".join([_PREFIX.pack(_MAGIC, FORMAT_VERSION, len(header), count), header,
                     *(values.astype("<f8", copy=False).tobytes(order="C") for values in arrays)])


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON metadata")


def _decode_metadata(header, count, name):
    try:
        metadata = json.loads(header.decode("utf-8"), object_pairs_hook=_object,
                              parse_constant=_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise _invalid("malformed JSON metadata") from error
    if type(metadata) is not dict or set(metadata) != _FIELDS:
        raise _invalid("unexpected metadata fields")
    if (not all(_label(metadata[key]) for key in ("id", "typecode", "aircraft_class"))
            or metadata["id"] != name or type(metadata["velocity"]) is not bool):
        raise _invalid("flight identity or labels do not match")
    inferred = metadata["velocity_inferred_components"]
    if (type(inferred) is not dict or set(inferred) != set(_COMPONENTS)
            or any(type(inferred[key]) is not int or not 0 <= inferred[key] <= count
                   for key in _COMPONENTS)):
        raise _invalid("invalid velocity-inference counts")
    runs = metadata["altitude_basis"]
    if type(runs) is not list or not 1 <= len(runs) <= count:
        raise _invalid("invalid altitude label runs")
    length = 0
    for run in runs:
        if (type(run) is not list or len(run) != 2 or not _label(run[0])
                or type(run[1]) is not int or not 1 <= run[1] <= count - length):
            raise _invalid("invalid altitude label run")
        length += run[1]
    if length != count:
        raise _invalid("altitude labels do not match the trajectory")
    return metadata


def decode_track(name, payload, *, max_samples=None):
    """Return independent writable inputs and a reconstructed Track.

    Validate counts and byte lengths before allocating arrays or expanding label
    runs. A malformed or unsupported snapshot raises DataUnavailable so callers
    can use their original JSON payload under the same integrity checks.
    """
    if type(payload) is not bytes or not _PREFIX.size <= len(payload) <= _MAX_PAYLOAD_BYTES:
        raise _invalid("invalid payload size or buffer type")
    if not _label(name):
        raise _invalid("noncanonical flight identifier")
    if max_samples is not None and (type(max_samples) is not int or max_samples < 0):
        raise _invalid("invalid sample budget")
    magic, version, header_size, count = _PREFIX.unpack_from(payload)
    if magic != _MAGIC or version != FORMAT_VERSION:
        raise _invalid("unsupported magic or format version")
    if not 3 <= count <= _MAX_SAMPLES or not 0 < header_size <= _MAX_HEADER_BYTES:
        raise _invalid("sample or metadata count exceeds the codec limit")
    if max_samples is not None and count > max_samples:
        from .data_access import DataUnavailable
        raise DataUnavailable("Flight lookup sample budget exceeded")
    offset = _PREFIX.size + header_size
    if offset > len(payload):
        raise _invalid("truncated metadata")
    metadata = _decode_metadata(payload[_PREFIX.size:offset], count, name)
    columns = 7 if metadata["velocity"] else 4
    if len(payload) != offset + columns * count * 8:
        raise _invalid("numeric payload length does not match the header")
    arrays = []
    for _ in range(4):
        arrays.append(np.frombuffer(payload, dtype="<f8", count=count, offset=offset)
                      .astype(float, copy=True))
        offset += count * 8
    velocity = None
    if metadata["velocity"]:
        velocity = np.frombuffer(payload, dtype="<f8", count=3 * count, offset=offset)
        velocity = velocity.reshape(count, 3).astype(float, copy=True)
    try:
        track = Track(name, *arrays, metadata["typecode"], velocity)
    except (ValueError, TypeError, OverflowError, FloatingPointError) as error:
        raise _invalid("invalid trajectory values") from error
    track.altitude_basis = [label for label, length in metadata["altitude_basis"]
                            for _ in range(length)]
    track.aircraft_class = metadata["aircraft_class"]
    track.velocity_inferred_components = {
        key: metadata["velocity_inferred_components"][key] for key in _COMPONENTS}
    return track
