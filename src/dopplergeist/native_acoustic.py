"""Optional exact-order acceleration for the emission-time acoustic solver."""
import hashlib
import os
from pathlib import Path

import numpy as np
from scipy.interpolate import CubicHermiteSpline

_backend_choice = os.environ.get("DOPPLERGEIST_ACOUSTIC_BACKEND", "auto")
if _backend_choice not in {"auto", "python"}:
    raise ValueError("DOPPLERGEIST_ACOUSTIC_BACKEND must be 'auto' or 'python'")
_native = None
if _backend_choice == "auto":
    try:
        from . import _native_acoustic as _native
    except ImportError:
        _native = None

if _native is None:
    ACOUSTIC_BACKEND = "python-acoustic-v1"
else:
    _binary_hash = hashlib.sha256(Path(_native.__file__).read_bytes()).hexdigest()
    ACOUSTIC_BACKEND = f"native-c-acoustic-v1:{_binary_hash}"

_ERROR_POLICY = {"divide": "warn", "over": "warn", "under": "ignore", "invalid": "warn"}


def try_acoustic(track, t, observer, c, start, end, arrival_start, arrival_end, packed_factory):
    """Return exact outputs, or None to continue through the Python solver.

    Arrival endpoints retain NumPy's scalar BLAS norm. The existing packed
    spline object preserves its bounded cache and mutable-coefficient behavior.
    Motion-support validation stays in Python, including its diagnostic data.
    """
    if (_native is None or type(observer) is not np.ndarray
            or observer.dtype != np.float64 or observer.shape != (3,)
            or not t.size or not t.flags.c_contiguous or not observer.flags.c_contiguous
            or type(c) not in (float, int, np.float64)
            or type(track.origin) not in (float, np.float64)
            or any(type(value) not in (float, np.float64)
                   for value in (start, end, arrival_start, arrival_end))
            or type(track.spline) is not CubicHermiteSpline
            or type(track.derivative) is not CubicHermiteSpline
            or type(track.spline.axis) is not int or type(track.derivative.axis) is not int
            or track.spline.axis != 0 or track.derivative.axis != 0
            or track.spline.extrapolate is not False or track.derivative.extrapolate is not False
            or np.geterr() != _ERROR_POLICY):
        return None
    source = (track.spline.c, track.spline.x, track.derivative.c)
    if any(type(array) is not np.ndarray or array.dtype != np.float64
           or not array.flags.c_contiguous or not array.flags.aligned for array in source):
        return None
    packed = packed_factory(track.spline, track.derivative)
    arrays = (track.spline.c, track.spline.x, packed.c, packed.x)
    if (type(packed.axis) is not int or packed.axis != 0 or packed.extrapolate is not False
            or any(type(array) is not np.ndarray for array in arrays)):
        return None
    output = tuple(np.empty(t.shape) for _ in range(3))
    success = _native.solve(t, observer, *arrays, track.origin, start, end, c,
                           arrival_start, arrival_end, *output)
    if not success:
        return None
    track._check_motion_support(t, observer, c)
    return output


_CANONICAL_NATIVE = _native
_CANONICAL_SOLVE = getattr(_native, "solve", None)
