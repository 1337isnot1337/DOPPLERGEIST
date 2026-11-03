"""Batched robust ridge fits with the scalar model's arithmetic order."""
import hashlib
import math
import pickle

import numpy as np

from . import matching
from .audio import Spectrum
from .matching import (RidgeTimes, _fit_argument_key, _fit_ridge_uncached,
                       _frequency_scale, _ridge_fit_cache, _ridge_fit_inputs)


def _batch_fit_key(measurement, event, factors, emissions):
    """Identify a complete batch without retaining its input arrays.

    Reduction layout is part of the input: equal values with different strides
    need not follow the same floating-point summation order.
    """
    if type(measurement) not in (tuple, list) or len(measurement) != 4:
        raise TypeError("Uncached custom measurement container")
    if type(measurement[0]) not in (RidgeTimes, Spectrum):
        raise TypeError("Uncached custom measurement time container")
    if type(event) is not dict or type(event.get("quality", {})) is not dict:
        raise TypeError("Uncached custom event container")
    digest = hashlib.sha256()
    settings = tuple(_fit_argument_key(value) for value in
        (_frequency_scale(event), event.get("quality", {}).get("source_drift_fraction", .02),
         event["f0_range_hz"]))
    digest.update(pickle.dumps(settings, protocol=5))
    for array in (measurement[0].time, measurement[1], measurement[2], factors, emissions):
        if type(array) is not np.ndarray or array.dtype.kind not in "biuf":
            raise TypeError("Uncached custom batch input")
        layout = (array.dtype.str, array.shape, array.strides, array.flags.aligned)
        digest.update(pickle.dumps(layout, protocol=5))
        digest.update(array.tobytes(order="C"))
    return digest.digest()


def first_event_fits(measurement, event, factors, emissions, *, legacy_arithmetic=False):
    """Reuse an identical complete fit batch within the current scoring call."""
    return _cached_first_event_fits(measurement, event, factors, emissions,
                                   legacy_arithmetic=legacy_arithmetic)


_CANONICAL_FIRST_EVENT_FITS = first_event_fits


class _CeilingFitBatch:
    """Private snapshot: independently copied fits and their validated ceilings."""

    __slots__ = ("fits", "limit", "ceilings")

    def __init__(self, fits, limit, ceilings):
        self.fits, self.limit, self.ceilings = fits, limit, ceilings


def _first_event_fits_with_ceilings(measurement, event, factors, emissions, limit, *,
                                   legacy_arithmetic=False):
    """Reuse a whole ceiling vector only for the unchanged, pure core validator.

    Noncanonical inputs and custom hooks retain the caller's per-row validation
    order. Fit-only snapshots can coexist with snapshots enriched by this path.
    """
    from . import search

    bounds = event.get("f0_range_hz") if type(event) is dict else None
    quality = event.get("quality", {}) if type(event) is dict else None
    fraction = quality.get("source_drift_fraction", .02) if type(quality) is dict else None
    canonical = (
        first_event_fits is _CANONICAL_FIRST_EVENT_FITS
        and _first_event_fits_uncached is _CANONICAL_BATCH_FITTER
        and _fit_diagnostics is _CANONICAL_FIT_DIAGNOSTICS
        and all(current is original for current, original in zip(
            (search._association_event_ceiling, search._association_event_ceiling_uncached,
             search._ridge_trial_classification), search._CANONICAL_CEILING_FUNCTIONS))
        and type(limit) is float and math.isfinite(limit) and limit > 0
        and type(bounds) in (list, tuple) and len(bounds) == 2
        and all(type(value) is float for value in (*bounds, fraction))
        and np.geterr() == {"divide": "warn", "over": "warn", "under": "ignore", "invalid": "warn"})
    if not canonical:
        return (first_event_fits(measurement, event, factors, emissions,
                                 legacy_arithmetic=legacy_arithmetic), None)
    return _cached_first_event_fits(measurement, event, factors, emissions,
                                   legacy_arithmetic=legacy_arithmetic, ceiling_limit=limit)


def _cached_first_event_fits(measurement, event, factors, emissions, *,
                             legacy_arithmetic=False, ceiling_limit=None):
    options = {"legacy_arithmetic": True} if legacy_arithmetic else {}
    cache = _ridge_fit_cache.get()
    kernel = _first_event_fits_uncached
    if cache is None or cache.max_entries < 1 or cache.batch_fit_limit <= 0:
        result = kernel(measurement, event, factors, emissions, **options)
        return result if ceiling_limit is None else (result, None)
    # A changed fitter must not reuse its predecessor's snapshots.
    if cache.batch_fit_function is not kernel:
        cache.batch_fit_entries.clear()
        cache.batch_fit_bytes = 0
        cache.batch_fit_function = kernel
    try:
        key = _batch_fit_key(measurement, event, factors, emissions)
        if legacy_arithmetic:
            key = hashlib.sha256(b"legacy-array-v1" + key).digest()
    except (TypeError, ValueError, KeyError, AttributeError):
        result = kernel(measurement, event, factors, emissions, **options)
        return result if ceiling_limit is None else (result, None)
    entries = cache.batch_fit_entries
    if key in entries:
        entries.move_to_end(key)
        # Only snapshots produced below from our own scalar-valued diagnostics
        # enter this private memory cache. No files or external pickles are read.
        saved = pickle.loads(entries[key])
        result = saved.fits if type(saved) is _CeilingFitBatch else saved
        if ceiling_limit is None:
            return result
        if type(saved) is _CeilingFitBatch and saved.limit == ceiling_limit:
            return result, saved.ceilings
    else:
        result = kernel(measurement, event, factors, emissions, **options)
    ceilings = None
    if result is not None:
        if ceiling_limit is not None:
            from .search import _association_event_ceiling
            ceilings = [_association_event_ceiling(fit, fit["score"], fit["f0_hz"], event, ceiling_limit)
                        for fit in result]
        saved = result if ceiling_limit is None else _CeilingFitBatch(result, ceiling_limit, ceilings)
        snapshot = pickle.dumps(saved, protocol=5)
        size = len(key) + len(snapshot)
        if size <= cache.batch_fit_limit:
            previous = entries.pop(key, None)
            if previous is not None:
                cache.batch_fit_bytes -= len(key) + len(previous)
            while entries and (cache.batch_fit_bytes + size > cache.batch_fit_limit
                               or len(entries) >= cache.max_entries):
                old_key, old_snapshot = entries.popitem(last=False)
                cache.batch_fit_bytes -= len(old_key) + len(old_snapshot)
            entries[key] = snapshot
            cache.batch_fit_bytes += size
    # None fallbacks and exceptions are never cached. The first caller also
    # owns its diagnostics: later mutations cannot change the stored bytes.
    return result if ceiling_limit is None else (result, ceilings)


def _first_event_fits_uncached(measurement, event, factors, emissions, *, legacy_arithmetic=False):
    """Fit supported clocks together, or return None for the ordinary fitter.

    This uses the same six iterations, box constraints, and diagnostics as the
    scalar fitter. Unsupported, degenerate or numerically nonfinite batches
    fall back rather than changing their classification.
    """
    sigma = _frequency_scale(event)
    fraction = event.get("quality", {}).get("source_drift_fraction", 0.02)
    times, ridge, weights = _ridge_fit_inputs(measurement, sigma, fraction)
    measured = np.isfinite(times) & np.isfinite(ridge) & (weights > 0)
    factors, emissions = np.asarray(factors, dtype=float), np.asarray(emissions, dtype=float)
    if (measured.sum() < 10 or factors.ndim != 2 or emissions.shape != factors.shape
            or factors.shape[1] != measured.sum() or not len(factors)
            or not np.all(np.isfinite(factors)) or not np.all(factors > 0)
            or not np.all(np.isfinite(emissions)) or fraction <= 0):
        return None
    low, high = event["f0_range_hz"]
    # Keep scalar numeric promotion for noncanonical parameter types.
    if not legacy_arithmetic and any(type(value) not in (int, float) for value in (sigma, fraction, low, high)):
        return None
    y, w = ridge[measured], weights[measured]
    independent = len(np.unique(times[measured]))
    diagnostic_error_policy = np.geterr()
    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        w = w * independent / w.sum()
        span = np.maximum(np.ptp(emissions, axis=1), 1e-9)
        reference = (emissions.min(axis=1) + emissions.max(axis=1)) / 2
        u = (emissions - reference[:, None]) / span[:, None]
        cap = np.clip(np.median(y[None, :] / factors, axis=1), low, high) * fraction
        if not np.all(np.isfinite(cap) & (cap > 0)) or not np.all(np.isfinite(u)):
            return None
        native = matching._native_fit_irls
        # Contiguous rows use the native kernel's same pairwise reduction order.
        # Other layouts and scalar promotion rules retain the vectorized path.
        # Saved first-group batches must keep their original array powers and
        # scalar compatibility checks even when the native fitter is installed.
        if (not legacy_arithmetic and native is not None
                and all(type(value) is float for value in (sigma, fraction, low, high))
                and factors.flags.c_contiguous and emissions.flags.c_contiguous
                and factors.flags.aligned and emissions.flags.aligned):
            native_rows = []
            try:
                batch = matching._native_fit_irls_batch
                if batch is not None and native is matching._CANONICAL_NATIVE_FIT_IRLS:
                    output = np.empty((len(factors), 5), dtype=float)
                    if batch(factors, u, y, w, cap, low, high, sigma, independent, output):
                        native_rows = output
                else:
                    # Preserve custom scalar hooks and older installed binaries.
                    for factor, normalized_time, bound in zip(factors, u, cap):
                        fit = native(factor, normalized_time, y, w, low, high,
                                     float(bound), sigma, independent)
                        if fit is None:
                            break
                        native_rows.append(fit)
                if len(native_rows) == len(factors):
                    score, alpha, beta, rmse, outlier = np.asarray(native_rows, dtype=float).T
                    if all(np.all(np.isfinite(value)) for value in
                           (span, reference, score, alpha, beta, rmse, outlier)):
                        # Metadata is normally assembled after the ignored-error block.
                        with np.errstate(**diagnostic_error_policy):
                            return _fit_diagnostics(score, alpha, beta, rmse, outlier,
                                                    span, reference, cap, len(y), independent)
            except (BufferError, TypeError, ValueError, OverflowError):
                pass
        factor2, u2 = factors**2, u**2
        effective = np.broadcast_to(w, factors.shape).copy()
        # The scalar fitter squares Python floats here. NumPy's array square
        # can differ by one ULP, which changes later IRLS steps and mode scores.
        try:
            prior = ((2 * sigma / cap)**2 if legacy_arithmetic else
                     np.fromiter(((2 * sigma / float(value))**2 for value in cap),
                                 dtype=float, count=len(cap)))
        except (OverflowError, ZeroDivisionError):
            return None
        for iteration in range(6):
            weighted_factor2, weighted_factor = effective * factor2, effective * factors
            a = np.sum(weighted_factor2, axis=1)
            r = np.sum(weighted_factor * y, axis=1)
            b = np.sum(weighted_factor2 * u, axis=1)
            d = np.sum(weighted_factor2 * u2, axis=1) + prior
            s = np.sum(weighted_factor * u * y, axis=1)
            determinant = a*d - b*b
            if (not all(np.all(np.isfinite(value)) for value in (a, r, b, prior, d, s, determinant))
                    or np.any(a <= 0) or np.any(d <= 0) or np.any(determinant <= 0)):
                return None
            alpha, beta = (r*d - s*b)/determinant, (s*a - r*b)/determinant
            if not np.all(np.isfinite(alpha) & np.isfinite(beta)):
                return None
            outside = np.flatnonzero(~((low <= alpha) & (alpha <= high) & (np.abs(beta) <= cap)))
            if len(outside):
                ao, ro, bo, do, so, co = (value[outside] for value in (a, r, b, d, s, cap))
                candidates = np.stack([
                    np.stack([np.full(len(outside), low), np.clip((so-bo*low)/do, -co, co)], axis=1),
                    np.stack([np.full(len(outside), high), np.clip((so-bo*high)/do, -co, co)], axis=1),
                    np.stack([np.clip((ro+bo*co)/ao, low, high), -co], axis=1),
                    np.stack([np.clip((ro-bo*co)/ao, low, high), co], axis=1),
                ], axis=1)
                errors = factors[outside, None, :] * (candidates[:, :, 0, None] +
                         candidates[:, :, 1, None] * u[outside, None, :]) - y
                costs = np.sum(effective[outside, None, :] * errors**2, axis=2) + prior[outside, None] * candidates[:, :, 1]**2
                if not np.all(np.isfinite(costs)):
                    return None
                chosen = candidates[np.arange(len(outside)), np.argmin(costs, axis=1)]
                alpha[outside], beta[outside] = chosen[:, 0], chosen[:, 1]
            residual = factors * (alpha[:, None] + beta[:, None] * u) - y
            residual_scale = np.sqrt(1 + (residual / sigma)**2)
            if iteration < 5:
                effective = w / residual_scale
        loss = np.average(2 * sigma**2 * (residual_scale - 1), weights=w, axis=1)
        try:
            penalty = ((2 * sigma * beta / cap)**2 / independent if legacy_arithmetic else
                       np.fromiter(
                           ((2 * sigma * float(drift) / float(bound))**2 / independent
                            for drift, bound in zip(beta, cap)), dtype=float, count=len(cap)))
        except (OverflowError, ZeroDivisionError):
            return None
        score = -np.sqrt(loss + penalty)
        rmse = np.sqrt(np.average(residual**2, weights=w, axis=1))
        outlier = np.average(np.abs(residual) > 3 * sigma, weights=w, axis=1)
    if not all(np.all(np.isfinite(value)) for value in (span, reference, score, rmse, outlier)):
        return None
    results = _fit_diagnostics(score, alpha, beta, rmse, outlier, span, reference, cap, len(y), independent)
    if legacy_arithmetic:
        # Saved searches before the scalar-consistent correction used this
        # array arithmetic and these three fallback checks for the first group.
        # Preserve their exact scores while batching later groups normally.
        for i in {0, len(results)//2, len(results)-1}:
            scalar = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
                                         343., sigma, fraction, acoustic_result=(factors[i], emissions[i]))
            if results[i] != scalar:
                return None
    return results


def _fit_diagnostics(score, alpha, beta, rmse, outlier, span, reference, cap, sample_count, independent):
    return [{"score": float(score[i]), "f0_hz": float(alpha[i]),
             "source_drift_hz": float(beta[i]), "source_drift_hz_s": float(beta[i]/span[i]),
             "source_reference_emission_time_s": float(reference[i]), "source_span_s": float(span[i]),
             "drift_bound_hz": float(cap[i]), "drift_at_bound": bool(cap[i] and abs(beta[i]) > 0.99*cap[i]),
             "rmse_hz": float(rmse[i]), "support_fraction": 1.0, "sample_count": int(sample_count),
             "independent_sample_count": independent, "outlier_fraction": float(outlier[i])}
            for i in range(len(alpha))]


_CANONICAL_BATCH_FITTER = _first_event_fits_uncached
_CANONICAL_FIT_DIAGNOSTICS = _fit_diagnostics
