"""Batched versions of the existing robust first-event ridge fits."""
import numpy as np

from .matching import _fit_ridge_uncached, _frequency_scale, _ridge_fit_inputs


def first_event_fits(measurement, event, factors, emissions):
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
    if any(type(value) not in (int, float) for value in (sigma, fraction, low, high)):
        return None
    y, w = ridge[measured], weights[measured]
    independent = len(np.unique(times[measured]))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        w = w * independent / w.sum()
        span = np.maximum(np.ptp(emissions, axis=1), 1e-9)
        reference = (emissions.min(axis=1) + emissions.max(axis=1)) / 2
        u = (emissions - reference[:, None]) / span[:, None]
        cap = np.clip(np.median(y[None, :] / factors, axis=1), low, high) * fraction
        if not np.all(np.isfinite(cap) & (cap > 0)) or not np.all(np.isfinite(u)):
            return None
        factor2, u2 = factors**2, u**2
        effective = np.broadcast_to(w, factors.shape).copy()
        for _ in range(6):
            weighted_factor2, weighted_factor = effective * factor2, effective * factors
            a = np.sum(weighted_factor2, axis=1)
            r = np.sum(weighted_factor * y, axis=1)
            b = np.sum(weighted_factor2 * u, axis=1)
            # Preserve the scalar fitter's Python-float exponent rounding.
            try:
                prior = np.fromiter(((2 * sigma / float(value))**2 for value in cap),
                                    dtype=float, count=len(cap))
            except (OverflowError, ZeroDivisionError):
                return None
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
        try:
            penalty = np.fromiter(((2 * sigma * float(drift) / float(bound))**2 / independent
                                  for drift, bound in zip(beta, cap)), dtype=float, count=len(cap))
        except (OverflowError, ZeroDivisionError):
            return None
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
