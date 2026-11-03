"""Private immutable numerical inputs for one bounded point-scoring call."""
import hashlib
import math
import pickle
import sys

import numpy as np

_MISSING = object()
_FLOAT64 = np.dtype("float64")
_SETTING_KEYS = ("frequency_loss_scale_hz", "frequency_sigma_hz",
                 "frequency_uncertainty_hz", "source_drift_fraction")


def _plain_copy(value, remaining):
    """Copy JSON-like builtin containers without invoking custom copy hooks."""
    # Live discovery's support_fraction can be an immutable NumPy float64.
    # Keep its exact type and bits; serializing it first would hide this case.
    if type(value) not in (str, float, int, bool, type(None), np.float64, list, tuple, dict):
        raise TypeError("Custom scoring input retains its original path")
    remaining[0] -= sys.getsizeof(value)
    if remaining[0] < 0:
        raise TypeError("Prepared scoring input budget exceeded")
    if type(value) in (str, float, int, bool, type(None), np.float64):
        return value
    if type(value) in (list, tuple):
        copied = [_plain_copy(item, remaining) for item in value]
        return copied if type(value) is list else tuple(copied)
    if type(value) is dict and all(type(key) is str for key in value):
        return {_plain_copy(key, remaining): _plain_copy(item, remaining) for key, item in value.items()}
    raise TypeError("Custom scoring input retains its original path")


def _immutable(values):
    # A write-disabled owning array can be made writable again. Bytes backing
    # prevents that, so mutable callers cannot alter a prepared numeric value.
    return np.frombuffer(values.tobytes(), dtype=values.dtype).reshape(values.shape)


class _PreparedScoreInput:
    def __init__(self, event, measurement, sigma, fraction, size, argument_key):
        self.event, self.measurement = event, measurement
        self.arrays = (measurement[0].time, measurement[1], measurement[2])
        self.shapes = tuple(array.shape for array in self.arrays)
        self.strides = tuple(array.strides for array in self.arrays)
        self.bases = tuple(array.base for array in self.arrays)
        self.bounds = event["f0_range_hz"]
        self.bound_values = tuple(self.bounds)
        self.quality = event["quality"]
        self.settings = tuple(self.quality.get(key, _MISSING) for key in _SETTING_KEYS)
        self.sigma, self.fraction, self.size = sigma, fraction, size
        times, ridge, weight = self.arrays
        self.measured = _immutable(np.isfinite(times) & np.isfinite(ridge) & (weight > 0))
        self.selected = tuple(_immutable(array[self.measured]) for array in self.arrays)
        self.sample_count = len(self.selected[0])
        self.independent = len(np.unique(self.selected[0]))
        # Preserve the existing keys byte for byte. Only their invariant prefix
        # is prepared; each mutable acoustic batch is still hashed in full.
        observed, batch = hashlib.sha256(), hashlib.sha256()
        settings = tuple(argument_key(value) for value in (sigma, fraction, self.bounds))
        batch.update(pickle.dumps(settings, protocol=5))
        for array in self.arrays:
            values = array.tobytes()
            observed.update(repr(array.shape).encode())
            observed.update(values)
            layout = (array.dtype.str, array.shape, array.strides, array.flags.aligned)
            batch.update(pickle.dumps(layout, protocol=5))
            batch.update(values)
        self.measurement_key, self.batch_digest = observed.digest(), batch

    def current(self, measurement, event):
        if (measurement is not self.measurement or event is not self.event
                or measurement[0].time is not self.arrays[0]
                or event.get("quality") is not self.quality
                or event.get("f0_range_hz") is not self.bounds or len(self.bounds) != 2
                or any(value is not original for value, original in zip(self.bounds, self.bound_values))
                or any(self.quality.get(key, _MISSING) is not original
                       for key, original in zip(_SETTING_KEYS, self.settings))):
            return False
        # NumPy permits changing view metadata even when the bytes are immutable.
        # Retain layout guards as well as the immutable backing and object IDs.
        return all(array.dtype == _FLOAT64 and array.shape == shape and array.strides == stride
                   and array.base is base and not array.flags.writeable
                   for array, shape, stride, base in zip(self.arrays, self.shapes, self.strides, self.bases))


def _canonical_functions(matching):
    return (all(current is original for current, original in zip(
        (matching._frequency_scale, matching._ridge_fit_inputs,
         matching._prepare_ridge_fit_inputs, matching._fit_argument_key),
        matching._CANONICAL_SCORE_INPUT_FUNCTIONS))
        and matching.fit_ridge is matching._CANONICAL_FIT_RIDGE
        and matching._fit_ridge_uncached is matching._CANONICAL_SCALAR_FITTER
        and matching._iter_acoustic_trials is matching._CANONICAL_ACOUSTIC_TRIALS
        and matching._source_fit is matching._CANONICAL_PREFIX_FUNCTIONS[3]
        and matching._native_fit_irls is matching._CANONICAL_NATIVE_IRLS)


def _prepare_score_inputs(events, measurements):
    """Snapshot supported ordinary inputs; other inputs keep public behavior.

    Preparation never raises a validation error before the original scorer
    would reach that input. A malformed/custom input simply stays on its old
    path. Memory is bounded by the existing scoring context's separate budget.
    """
    # A lazy dependency also supports importing scoring_inputs first.
    from . import matching

    cache = matching._ridge_fit_cache.get()
    if (cache is None or type(events) not in (list, tuple)
            or type(measurements) not in (list, tuple) or len(events) != len(measurements)
            or not _canonical_functions(matching) or np.geterr() != matching._NATIVE_RIDGE_ERROR_POLICY):
        return events, measurements
    copied_events, copied_measurements = list(events), list(measurements)
    for index, (event, measurement) in enumerate(zip(events, measurements)):
        if (type(event) is not dict or not all(type(key) is str for key in event)
                or type(event.get("quality")) is not dict
                or not all(type(key) is str for key in event["quality"])
                or any(type(event["quality"].get(key, 0.0)) not in (float, int, bool)
                       for key in _SETTING_KEYS)
                or type(measurement) not in (list, tuple) or len(measurement) != 4
                or type(measurement[0]) is not matching.RidgeTimes):
            continue
        bounds = event.get("f0_range_hz")
        if (type(bounds) not in (list, tuple) or len(bounds) != 2
                or not all(type(value) is float and math.isfinite(value) for value in bounds)
                or not 0 < bounds[0] <= bounds[1]):
            continue
        arrays = (measurement[0].time, measurement[1], measurement[2])
        if any(type(array) is not np.ndarray or array.dtype != _FLOAT64 or array.ndim != 1
               or array.strides != (array.itemsize,)
               or not array.flags.c_contiguous or not array.flags.aligned for array in arrays):
            continue
        available = cache.score_input_limit - cache.score_input_bytes
        size = 4 * sum(array.nbytes for array in arrays) + 2048
        if size > available or len(cache.score_inputs) >= cache.max_entries:
            continue
        try:
            sigma = matching._frequency_scale(event)
            fraction = event["quality"].get("source_drift_fraction", .02)
            if (type(sigma) is not float or type(fraction) is not float
                    or not math.isfinite(sigma) or not math.isfinite(3*sigma) or sigma <= 0
                    or not math.isfinite(fraction) or not 0 <= fraction <= .1):
                continue
            matching._ridge_fit_inputs(measurement, sigma, fraction)
            remaining = [available - size]
            copied_event = _plain_copy(event, remaining)
            metadata = _plain_copy(measurement[3], remaining)
            frozen = tuple(_immutable(array) for array in arrays)
            copied = (matching.RidgeTimes(frozen[0]), frozen[1], frozen[2], metadata)
            size += available - size - remaining[0]
            prepared = _PreparedScoreInput(copied_event, copied, sigma, fraction, size,
                                           matching._fit_argument_key)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
            continue
        cache.score_inputs[id(copied)] = prepared
        cache.score_input_bytes += size
        copied_events[index], copied_measurements[index] = copied_event, copied
    return copied_events, copied_measurements


def _prepared_score_input(measurement, event=None):
    from . import matching

    cache = matching._ridge_fit_cache.get()
    if cache is None:
        return None
    prepared = cache.score_inputs.get(id(measurement))
    if (prepared is not None and _canonical_functions(matching)
            and np.geterr() == matching._NATIVE_RIDGE_ERROR_POLICY
            and prepared.current(measurement, prepared.event if event is None else event)):
        return prepared
    return None


def _prepared_score_token(measurement, event):
    """Return an immutable identity only for this scope's unchanged snapshots."""
    return _prepared_score_input(measurement, event)


def _prepared_score_tokens(measurements, events):
    """Validate every snapshot while checking shared execution settings once."""
    from . import matching

    cache = matching._ridge_fit_cache.get()
    if (cache is None or not cache.score_inputs
            or type(measurements) not in (list, tuple) or type(events) not in (list, tuple)
            or len(measurements) != len(events) or not _canonical_functions(matching)
            or np.geterr() != matching._NATIVE_RIDGE_ERROR_POLICY):
        return None
    tokens = []
    for measurement, event in zip(measurements, events):
        prepared = cache.score_inputs.get(id(measurement))
        if prepared is None or not prepared.current(measurement, event):
            return None
        tokens.append(prepared)
    return tuple(tokens)
