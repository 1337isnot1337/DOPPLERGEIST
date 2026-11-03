"""Optional exact-order reduction of a bounded CPA neighbour graph."""
import os

import numpy as np


_backend_choice = os.environ.get("DOPPLERGEIST_CPA_BACKEND", "auto")
if _backend_choice not in {"auto", "python"}:
    raise ValueError("DOPPLERGEIST_CPA_BACKEND must be 'auto' or 'python'")
_native = None
if _backend_choice == "auto":
    try:
        from . import _native_cpa as _native
    except ImportError:
        pass

CPA_BACKEND = "python-cpa-v1" if _native is None else "native-c-cpa-v1"
_ERROR_POLICY = {"divide": "warn", "over": "warn", "under": "ignore", "invalid": "warn"}


def try_cpa_edges(position, observers, counts, sample):
    """Return endpoint candidates and projected minima, or use the reference.

    The caller owns one bounded, sorted radius-neighbour graph. The extension
    streams its distances and projects only the sampled minima; it does not
    change the spatial query, spline endpoint solver, or row selection rules.
    """
    if _native is None or np.geterr() != _ERROR_POLICY:
        return None
    for array, dtype in ((position, np.float64), (observers, np.float64),
                         (counts, np.intp), (sample, np.intp)):
        if (type(array) is not np.ndarray or array.dtype != dtype
                or not array.flags.c_contiguous or not array.flags.aligned):
            return None
    if (position.ndim != 2 or position.shape[1] != 3
            or observers.ndim != 2 or observers.shape[1] != 3
            or counts.ndim != 1 or len(counts) != len(observers)
            or sample.ndim != 1):
        return None
    # Two consecutive samples cannot both satisfy d[k] < d[k+1]. Each
    # interior minimum therefore consumes at least two neighbour entries.
    capacity = sample.size // 2
    endpoints = np.empty((2, len(observers)), dtype=np.intp)
    indices = np.empty((2, capacity), dtype=np.intp)
    values = np.empty((2, capacity), dtype=np.float64)
    sizes = _native.select(position, observers, counts, sample, endpoints, indices, values)
    if sizes is None:
        return None
    first_count, last_count, minimum_count = sizes
    return ((endpoints[0, :first_count], endpoints[1, :last_count]),
            indices[0, :minimum_count], indices[1, :minimum_count],
            values[0, :minimum_count], values[1, :minimum_count])
