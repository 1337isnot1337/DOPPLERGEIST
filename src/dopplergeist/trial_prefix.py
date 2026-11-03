"""Bounded reuse of fully eliminated association prefixes in one score call."""
from collections import OrderedDict
import inspect
import math
import sys
from types import GeneratorType

import numpy as np


_MAX_ENTRIES = 4096
_MAX_BYTES = 8 * 1024 * 1024
_COUNTS = dict(lookups=0, hits=0, residual_hits=0, stored=0, evicted=0,
               saved_event_steps=0, saved_trials=0)
_TRACK_METHODS = ("acoustic", "position", "speed_vector", "_position_velocity",
                  "_check_motion_support", "_check_motion_support_scalar",
                  "_unsupported_motion_intervals")
_OUTCOME_SIZE = sys.getsizeof((None, 0.0, None)) + sys.getsizeof(0.0) + 2 * sys.getsizeof(None)


def cache_stats():
    """Read process-local operation counters without wrapping numerical code."""
    from .matching import _ridge_fit_cache

    owner = _ridge_fit_cache.get()
    memo = getattr(owner, "prefix_memo", None)
    return dict(_COUNTS, entries=0 if memo is None else len(memo.entries),
                bytes=0 if memo is None else memo.size + sys.getsizeof(memo.entries))


def _canonical():
    # Import inside the call so direct imports of the helper introduce no
    # search/matching initialization cycle. Originals live in their providers.
    from . import acoustic_screen, batch_ridge, geometry, matching, native_acoustic, search

    current = (matching.fit_ridge, matching._fit_ridge_uncached,
               matching._iter_acoustic_trials, matching._source_fit,
               matching._RidgeFitCache.fit, matching._RidgeFitCache.acoustic_batch,
               matching._native_fit_irls, matching._native_ridge_module,
               getattr(matching._native_ridge_module, "event_fit_reason", None))
    batch = (batch_ridge.first_event_fits, batch_ridge._first_event_fits_with_ceilings,
             batch_ridge._cached_first_event_fits, batch_ridge._first_event_fits_uncached,
             batch_ridge._fit_diagnostics, batch_ridge._batch_fit_key,
             batch_ridge._frequency_scale, batch_ridge._ridge_fit_inputs,
             batch_ridge._fit_ridge_uncached)
    screen = (acoustic_screen.ridge_trial_rejections, acoustic_screen._cached_loss_lower_bounds,
              acoustic_screen._validated_loss_lower_bounds, acoustic_screen._loss_lower_bounds,
              acoustic_screen._frequency_scale)
    track = tuple(getattr(geometry.Track, name) for name in _TRACK_METHODS)
    track += (geometry._try_native_acoustic, geometry._packed_kinematics)
    ceiling = (search._association_event_ceiling, search._association_event_ceiling_uncached,
               search._ridge_trial_classification)
    groups = ((current, getattr(matching, "_CANONICAL_PREFIX_FUNCTIONS", ())),
              (batch, getattr(batch_ridge, "_CANONICAL_PREFIX_FUNCTIONS", ())),
              (screen, acoustic_screen._CANONICAL_SCREEN_FUNCTIONS),
              (track, geometry._CANONICAL_ACOUSTIC_FUNCTIONS),
              (ceiling, search._CANONICAL_CEILING_FUNCTIONS))
    return (all(len(now) == len(original) and all(a is b for a, b in zip(now, original))
                for now, original in groups)
            # Importing a consumer while matching is patched can retain a
            # custom alias after matching itself has been restored. Compare
            # imported helpers with the defining provider's original as well.
            and acoustic_screen._frequency_scale is matching._CANONICAL_SCORE_INPUT_FUNCTIONS[0]
            and batch_ridge._frequency_scale is matching._CANONICAL_SCORE_INPUT_FUNCTIONS[0]
            and batch_ridge._ridge_fit_inputs is matching._CANONICAL_SCORE_INPUT_FUNCTIONS[1]
            and batch_ridge._fit_argument_key is matching._CANONICAL_SCORE_INPUT_FUNCTIONS[3]
            and batch_ridge._fit_ridge_uncached is matching._CANONICAL_SCALAR_FITTER
            and matching._native_validate_ridge_events is matching._CANONICAL_NATIVE_EVENT_VALIDATOR
            and search._native_validate_ridge_events is matching._CANONICAL_NATIVE_EVENT_VALIDATOR
            and getattr(matching._native_ridge_module, "valid_ridge_events", None)
                is matching._CANONICAL_NATIVE_EVENT_VALIDATOR
            and native_acoustic._native is native_acoustic._CANONICAL_NATIVE
            and getattr(native_acoustic._native, "solve", None) is native_acoustic._CANONICAL_SOLVE
            and native_acoustic.try_acoustic is geometry._try_native_acoustic
            and matching._EMISSION_ITERATION_TOLERANCE_S == geometry._EMISSION_ITERATION_TOLERANCE_S == 1e-7)


def _array_key(value, shape=None):
    if (type(value) is not np.ndarray or value.dtype != np.float64
            or value.ndim != 1 or not value.flags.c_contiguous or not value.flags.aligned
            or (shape is not None and value.shape != shape) or not np.all(np.isfinite(value))):
        return None
    return value.shape, value.strides, value.tobytes()


def _size(value):
    # Tokens and tracks belong to the enclosing score scope already. Charge
    # their references, but not their existing numerical arrays a second time.
    return sys.getsizeof(value) + (sum(map(_size, value)) if type(value) is tuple else 0)


class _PrefixMemo:
    def __init__(self):
        self.entries = OrderedDict()
        self.size = 0

    def trim(self, capacity, limit, extra=0):
        while self.entries and (len(self.entries) > capacity
                                or self.size + sys.getsizeof(self.entries) + extra > limit):
            _, (_, _, removed) = self.entries.popitem(last=False)
            self.size -= removed
            _COUNTS["evicted"] += 1


class _Request:
    def __init__(self, owner, common, pairs, tracks):
        self.owner, self.common, self.pairs, self.tracks = owner, common, pairs, tracks
        self.memo = owner.prefix_memo
        self.floor = float.fromhex(common[4])
        self.residual_common = common[:4] + (None, None) + common[6:]

    def lookup(self):
        _COUNTS["lookups"] += 1
        for length in range(1, len(self.pairs) + 1):
            prefix = self.pairs[:length]
            key = self.common, prefix
            previous = self.memo.entries.get(key)
            residual = False
            if previous is None and length < len(self.pairs) and len(self.pairs) - length >= self.floor:
                key = self.residual_common, prefix
                previous = self.memo.entries.get(key)
                residual = previous is not None
            if previous is not None:
                self.memo.entries.move_to_end(key)
                outcomes, rejected, bounded = previous[0]
                _COUNTS["hits"] += 1
                _COUNTS["residual_hits"] += residual
                _COUNTS["saved_event_steps"] += length
                _COUNTS["saved_trials"] += len(outcomes)
                # Only scalar-only rejection tuples are shared. The caller owns
                # the outer list, and no fit dictionary or exception is stored.
                return list(outcomes), rejected, bounded
        return None

    def remember(self, processed, outcomes, rejected, bounded):
        if (not processed or not outcomes
                or not all(type(outcome) is tuple and len(outcome) == 3
                           and outcome[0] is None and outcome[2] is None
                           and type(outcome[1]) is float and outcome[1] < math.inf
                           for outcome in outcomes)):
            return
        common = self.common
        if (processed < len(self.pairs) and len(self.pairs) - processed >= self.floor
                and bounded == 0 and all(outcome[1] == -math.inf for outcome in outcomes)):
            # Each finite contribution is nonnegative. While the unperformed
            # group count is at least the floor, neither a finite prefix bound
            # nor the dual floor screen can eliminate a clock. These -inf
            # outcomes therefore contain only residual rejections, independent
            # of the total group count/floor inside this same domain. Keeping
            # the prefix nonfinal also preserves the batched fit/ceiling path.
            common = self.residual_common
        key = common, self.pairs[:processed]
        value = tuple(outcomes), rejected, bounded
        # The cache shares the existing immutable-track contract of _score.
        # Retain tracks strongly so IDs cannot be recycled during this scope.
        retained = tuple(self.tracks[:processed])
        # Every outcome was checked above to have the same scalar-only schema.
        # This is the recursive charge without visiting each None/float again.
        value_size = (sys.getsizeof(value) + sys.getsizeof(value[0]) + len(outcomes) * _OUTCOME_SIZE
                      + sys.getsizeof(rejected) + sys.getsizeof(bounded))
        size = _size(key) + value_size + sys.getsizeof(retained) + 256
        capacity = min(self.owner.max_entries, _MAX_ENTRIES)
        if capacity < 1 or size + sys.getsizeof(self.memo.entries) > _MAX_BYTES:
            return
        previous = self.memo.entries.pop(key, None)
        if previous is not None:
            self.memo.size -= previous[2]
        self.memo.trim(capacity - 1, _MAX_BYTES, size)
        self.memo.entries[key] = value, retained, size
        self.memo.size += size
        self.memo.trim(capacity, _MAX_BYTES)
        _COUNTS["stored"] += 1


def request(tracks, events, measurements, observer, starts, c, acoustic_batches,
            score_floor, use_dual, legacy_first_batch):
    """Prepare exact prefix keys only for the private immutable scoring scope.

    A complete eliminated prefix is independent of the remaining events' data.
    General entries retain the exact group count and floor. Residual-only
    entries may omit them only while every prefix still has enough unperformed
    groups to reach the floor. Every clock's original bound and both screen
    counters remain unchanged.
    Other iterators, custom numerical hooks and mutable public inputs keep the
    original traversal. No entry survives its enclosing fit-cache scope.
    """
    from . import geometry, matching

    owner = matching._ridge_fit_cache.get()
    memo = getattr(owner, "prefix_memo", None)
    if memo is not None:
        memo.trim(min(owner.max_entries, _MAX_ENTRIES), _MAX_BYTES)
    if (owner is None or type(owner) is not matching._RidgeFitCache or owner.max_entries < 1
            or _MAX_ENTRIES < 1 or _MAX_BYTES < 1 or not owner.score_inputs
            or type(score_floor) is not float or not math.isfinite(score_floor)
            or type(c) is not float or not math.isfinite(c) or c <= 0
            or type(use_dual) is not bool or type(legacy_first_batch) is not bool
            or type(tracks) not in (list, tuple) or type(events) not in (list, tuple)
            or type(measurements) not in (list, tuple)
            or not len(tracks) == len(events) == len(measurements)
            or type(acoustic_batches) is not GeneratorType
            or acoustic_batches.gi_code is not matching._CANONICAL_ACOUSTIC_TRIALS.__code__
            or inspect.getgeneratorstate(acoustic_batches) != inspect.GEN_CREATED
            or any(name in owner.__dict__ for name in ("fit", "acoustic_batch"))
            or not _canonical()):
        return None
    arguments = acoustic_batches.gi_frame.f_locals
    if (arguments["tracks"] is not tracks or arguments["measurements"] is not measurements
            or arguments["observer"] is not observer or arguments["c"] is not c
            or type(arguments["max_samples"]) is not int or arguments["max_samples"] < 1):
        return None
    observer_key, starts_key = _array_key(observer, (3,)), _array_key(starts)
    if observer_key is None or starts_key is None or _array_key(arguments["starts"]) != starts_key:
        return None
    tokens = matching._prepared_score_tokens(measurements, events)
    if tokens is None:
        return None
    pairs = []
    for track, token in zip(tracks, tokens):
        if type(track) is not geometry.Track or any(name in track.__dict__ for name in _TRACK_METHODS):
            return None
        pairs.append((id(track), token))
    if not hasattr(owner, "prefix_memo"):
        owner.prefix_memo = _PrefixMemo()
    owner.prefix_memo.trim(min(owner.max_entries, _MAX_ENTRIES), _MAX_BYTES)
    common = (observer_key, starts_key, type(c), c, score_floor.hex(), len(events),
              use_dual, legacy_first_batch, arguments["max_samples"])
    return _Request(owner, common, tuple(pairs), tracks)
