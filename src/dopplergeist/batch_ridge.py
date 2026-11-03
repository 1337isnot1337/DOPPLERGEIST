"""Batched versions of the existing robust ridge fits."""
import hashlib

import numpy as np

from .matching import (_fit_argument_key, _fit_ridge_uncached, _frequency_scale,
                       _ridge_fit_cache, _ridge_fit_inputs)


def _numeric_digest(values):
    digest = hashlib.sha256()
    for value in values:
        array = np.asarray(value, dtype=float)
        digest.update(array.dtype.str.encode())
        digest.update(repr(array.shape).encode())
        digest.update(array.tobytes())
    return digest.digest()


def _source_cache_key(measurement, event):
    """Hash every source-fit input; preserve numeric types and full precision."""
    try:
        spec, ridge, weight, _ = measurement
        parameters = tuple(_fit_argument_key(value) for value in
            (event["f0_range_hz"], _frequency_scale(event),
             event.get("quality", {}).get("source_drift_fraction", .02)))
        digest = hashlib.sha256(b"scalar-power-source-fit-v1")
        digest.update(repr(parameters).encode())
        digest.update(_numeric_digest((spec.time, ridge, weight)))
        return digest.digest()
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def supported_clock_fits(measurement, event, batch, eligible=None):
    """Fit supported rows together while leaving all other rows to the scalar path.

    A partially supported clock batch must not disable batching of its supported
    clocks. None entries mean only that the ordinary fitter must assess that row;
    they do not reject a clock or change its support classification.
    """
    if batch is None:
        return None
    factors, emissions = batch
    if factors.ndim != 2 or emissions.shape != factors.shape:
        return None
    supported = np.all(np.isfinite(factors) & (factors > 0) & np.isfinite(emissions), axis=1)
    if eligible is not None:
        eligible = np.asarray(eligible, dtype=bool)
        if eligible.shape != supported.shape:
            return None
        supported &= eligible
    selected = np.flatnonzero(supported)
    if not len(selected):
        return None
    fraction = event.get("quality", {}).get("source_drift_fraction", .02)
    if fraction <= 0:
        return None
    cache = _ridge_fit_cache.get()
    prefix = _source_cache_key(measurement, event) if cache is not None else None
    entries = cache.source_entries if prefix is not None else None
    results = [None] * len(factors)
    missing, keys = [], {}
    for index in selected:
        if entries is not None:
            key = (prefix, _numeric_digest((factors[index], emissions[index])))
            keys[index] = key
            if key in entries:
                entries.move_to_end(key)
                results[index] = entries[key].copy()
                continue
        missing.append(index)
    if len(missing) >= 4:
        fitted = first_event_fits(measurement, event, factors[missing], emissions[missing], True)
    elif missing and entries is not None:
        # Reusing a batch often leaves only one or two new clocks. Fit just
        # those clocks once instead of rerunning the three-row batch guard.
        fitted = [_fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
            343., _frequency_scale(event), fraction, acoustic_result=(factors[index], emissions[index]))
            for index in missing]
    else:
        fitted = None
    if fitted is not None:
        for index, result in zip(missing, fitted):
            results[index] = result
            if entries is not None:
                entries[keys[index]] = result.copy()
                if len(entries) > cache.max_entries:
                    entries.popitem(last=False)
    return results if any(result is not None for result in results) else None


def first_event_fits(measurement, event, factors, emissions, scalar_power_arithmetic=False):
    """Fit supported clocks together, or return None for the ordinary fitter.

    This uses the same six iterations and box constraints as the scalar fitter.
    The default preserves the established first-event vectorized powers; newly
    batched scalar paths request scalar power arithmetic explicitly. Checking
    representative rows can detect a discrepancy but cannot prove every row is
    bitwise equal. Unsupported or degenerate batches use the ordinary fitter.
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
    y, w = ridge[measured], weights[measured]
    independent = len(np.unique(times[measured]))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        w = w * independent / w.sum()
        span = np.maximum(np.ptp(emissions, axis=1), 1e-9)
        reference = (emissions.min(axis=1) + emissions.max(axis=1)) / 2
        u = (emissions - reference[:, None]) / span[:, None]
        centers = np.clip(np.median(y[None, :] / factors, axis=1), low, high)
        scalar_caps = [float(value)*fraction for value in centers] if scalar_power_arithmetic else None
        cap = np.asarray(scalar_caps) if scalar_power_arithmetic else centers*fraction
        if not np.all(np.isfinite(cap) & (cap > 0)) or not np.all(np.isfinite(u)):
            return None
        # Python float powers and NumPy squares can differ by one ULP. Preserve
        # the old first-event path, while matching scalar arithmetic on newly
        # batched paths so an intermediate Top-K cutoff cannot change.
        if scalar_power_arithmetic:
            try:
                prior = np.fromiter(((2*sigma/bound)**2 for bound in scalar_caps),
                                    dtype=float, count=len(cap))
            except OverflowError:
                return None
        else:
            prior = (2*sigma/cap)**2
        factor2, u2 = factors**2, u**2
        effective = np.broadcast_to(w, factors.shape).copy()
        for _ in range(6):
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
            effective = w / np.sqrt(1 + (residual / sigma)**2)
        loss = np.average(2 * sigma**2 * (np.sqrt(1 + (residual / sigma)**2) - 1), weights=w, axis=1)
        if scalar_power_arithmetic:
            try:
                penalty = np.fromiter(((2*sigma*float(drift)/bound)**2/independent
                                       for drift, bound in zip(beta, scalar_caps)), dtype=float, count=len(cap))
            except OverflowError:
                return None
        else:
            penalty = (2*sigma*beta/cap)**2/independent
        score = -np.sqrt(loss + penalty)
        rmse = np.sqrt(np.average(residual**2, weights=w, axis=1))
        outlier = np.average(np.abs(residual) > 3 * sigma, weights=w, axis=1)
    if not all(np.all(np.isfinite(value)) for value in (span, reference, score, rmse, outlier)):
        return None
    results = [{"score": float(score[i]), "f0_hz": float(alpha[i]),
             "source_drift_hz": float(beta[i]), "source_drift_hz_s": float(beta[i]/span[i]),
             "source_reference_emission_time_s": float(reference[i]), "source_span_s": float(span[i]),
             "drift_bound_hz": float(cap[i]), "drift_at_bound": bool(cap[i] and abs(beta[i]) > 0.99*cap[i]),
             "rmse_hz": float(rmse[i]), "support_fraction": 1.0, "sample_count": int(len(y)),
             "independent_sample_count": independent, "outlier_fraction": float(outlier[i])}
            for i in range(len(alpha))]
    # Check representative clocks with the existing fitter. This catches a
    # platform or arithmetic discrepancy and sends the whole batch down the
    # established path instead of using inconsistent fit diagnostics.
    for i in {0, len(results)//2, len(results)-1}:
        scalar = _fit_ridge_uncached(None, None, measurement, 0., event["f0_range_hz"],
                                     343., sigma, fraction, acoustic_result=(factors[i], emissions[i]))
        if results[i] != scalar:
            return None
    return results
