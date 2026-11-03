"""Vectorized feasibility bounds for measured Doppler ridges."""
import numpy as np

from .matching import _frequency_scale


def ridge_trial_rejections(measurement, event, factors, emissions):
    """Propose joint-trial rejections from a supported event's loss bound.

    The pseudo-Huber loss has a bounded convex dual. Any dual vector inside
    its domain gives a lower bound, including when source frequency and drift
    are constrained to the fitter's declared bounds. A subset of observed
    samples also gives a lower bound because every omitted loss and the drift
    penalty are nonnegative. Only bounds strictly above the existing 3-sigma
    association threshold can reject a trial.

    ``factors`` and ``emissions`` are the existing batched acoustic results,
    with one row per clock and one column per measured ridge sample. Incomplete
    support, invalid settings, ill-conditioned fits and uncertain numerical
    results return False so the ordinary physical fit handles them.
    """
    factors = np.asarray(factors, dtype=float)
    emissions = np.asarray(emissions, dtype=float)
    trials = factors.shape[0] if factors.ndim else 0
    rejected = np.zeros(trials, dtype=bool)
    if factors.ndim != 2 or emissions.shape != factors.shape:
        return rejected
    try:
        sigma = float(_frequency_scale(event))
        fraction = float(event.get("quality", {}).get("source_drift_fraction", .02))
        low, high = map(float, event["f0_range_hz"])
        spec, ridge, weight, _ = measurement
        times, ridge, weight = (np.asarray(a, dtype=float) for a in (spec.time, ridge, weight))
    except (ValueError, TypeError, KeyError, AttributeError):
        return rejected
    if (not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(fraction) or not 0 <= fraction <= .1
            or not np.isfinite(low) or not np.isfinite(high) or not 0 < low <= high
            or times.ndim != 1 or times.shape != ridge.shape or times.shape != weight.shape
            or not np.all(np.isfinite(weight)) or np.any(weight < 0)):
        return rejected
    measured = np.isfinite(times) & np.isfinite(ridge) & (weight > 0)
    if measured.sum() < 10 or factors.shape[1] != measured.sum():
        return rejected
    times, ridge, weight = times[measured], ridge[measured], weight[measured]
    _, first = np.unique(times, return_index=True)
    first = np.sort(first)
    count = min(48, len(first))
    if count < 3:
        return rejected
    selected = first[np.linspace(0, len(first)-1, count, dtype=int)]
    active = np.flatnonzero(np.all(np.isfinite(factors), axis=1) & np.all(factors > 0, axis=1)
                            & np.all(np.isfinite(emissions), axis=1))
    if not len(active):
        return rejected
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        x, full_emission = factors[active][:, selected], emissions[active]
        samples, y, w = full_emission[:, selected], ridge[selected], weight[selected]
        span = np.ptp(full_emission, axis=1)
        valid = span > 1e-5
        span = np.where(valid, span, 1.)
        u = (samples-(full_emission.min(axis=1)+full_emission.max(axis=1))[:, None]/2)/span[:, None]
        z = x*u
        a = np.sum(w*x*x, axis=1)
        b = np.sum(w*x*z, axis=1)
        d = np.sum(w*z*z, axis=1)
        det = a*d-b*b
        valid &= np.isfinite(det) & (det > 1e-10*a*d)
        det = np.where(valid, det, 1.)
        p, q = np.sum(w*x*y, axis=1), np.sum(w*z*y, axis=1)
        alpha, beta = (d*p-b*q)/det, (a*q-b*p)/det
        residual = y-alpha[:, None]*x-beta[:, None]*z
        dual_fraction = residual/np.hypot(sigma, residual)
        dual = 2*sigma*w*dual_fraction
        p, q = np.sum(x*dual, axis=1), np.sum(z*dual, axis=1)
        alpha, beta = (d*p-b*q)/det, (a*q-b*p)/det
        dual -= w*(alpha[:, None]*x+beta[:, None]*z)
        dual_fraction = dual/(2*sigma*w)
        dual_fraction /= np.maximum(1., np.max(np.abs(dual_fraction), axis=1)/(1-1e-10))[:, None]
        dual = 2*sigma*w*dual_fraction
        conjugate = 2*sigma*sigma*w*dual_fraction**2/(1+np.sqrt(1-dual_fraction**2))
        source_box = np.abs(np.sum(x*dual, axis=1))*high
        drift_box = np.abs(np.sum(z*dual, axis=1))*(fraction*high)
        value = np.sum(dual*y, axis=1)-np.sum(conjugate, axis=1)-source_box-drift_box
        error = 1e-7*(1+np.sum(np.abs(dual*y), axis=1)+np.sum(np.abs(conjugate), axis=1)
                       +source_box+drift_box)
        lower = np.maximum(0., value-error)/np.sum(weight)
        rejected[active] = (valid & np.isfinite(lower)
                            & (lower > (3*sigma)**2*(1+1e-8)+1e-9))
    return rejected
