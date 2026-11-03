"""Vectorized feasibility bounds for measured Doppler ridges."""
import hashlib
import sys

import numpy as np

from .matching import _frequency_scale, _ridge_fit_cache


def ridge_trial_rejections(measurement, event, factors, emissions, *, score_floor=None, group_count=None):
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
    results return False so the ordinary physical fit handles them. When a
    retention floor and group count are supplied, also return finite upper
    scores for supported trials that cannot reach that floor. Other entries
    in the second array are NaN. Identical inputs reuse the floor-independent
    loss evidence inside one scoring context; each call applies its current
    retention floor and group count to that evidence.
    """
    factors = np.asarray(factors, dtype=float)
    emissions = np.asarray(emissions, dtype=float)
    trials = factors.shape[0] if factors.ndim else 0
    rejected = np.zeros(trials, dtype=bool)
    upper = np.full(trials, np.nan)
    def result():
        return (rejected, upper) if score_floor is not None else rejected
    if factors.ndim != 2 or emissions.shape != factors.shape:
        return result()
    try:
        sigma = float(_frequency_scale(event))
        fraction = float(event.get("quality", {}).get("source_drift_fraction", .02))
        low, high = map(float, event["f0_range_hz"])
        spec, ridge, weight, _ = measurement
        times, ridge, weight = (np.asarray(a, dtype=float) for a in (spec.time, ridge, weight))
    except (ValueError, TypeError, KeyError, AttributeError):
        return result()
    if (not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(fraction) or not 0 <= fraction <= .1
            or not np.isfinite(low) or not np.isfinite(high) or not 0 < low <= high
            or times.ndim != 1 or times.shape != ridge.shape or times.shape != weight.shape
            or not np.all(np.isfinite(weight)) or np.any(weight < 0)):
        return result()
    measured = np.isfinite(times) & np.isfinite(ridge) & (weight > 0)
    if measured.sum() < 10 or factors.shape[1] != measured.sum():
        return result()
    times, ridge, weight = times[measured], ridge[measured], weight[measured]
    evidence = _cached_loss_lower_bounds(times, ridge, weight, factors, emissions, sigma, fraction, high)
    if evidence is None:
        return result()
    active, valid, lower = evidence
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        rejected[active] = (valid & np.isfinite(lower)
                            & (lower > (3*sigma)**2*(1+1e-8)+1e-9))
        if (score_floor is not None and type(group_count) is int and group_count > 0
                and np.isfinite(score_floor) and 0 <= group_count-score_floor < 1):
            threshold = (3*sigma*(group_count-score_floor))**2*(1+1e-8)+1e-9
            ceiling = group_count-np.sqrt(lower)/(3*sigma)
            ceiling = np.maximum(0., np.nextafter(
                ceiling + 64*np.finfo(float).eps*(1+group_count+np.abs(ceiling)), np.inf))
            bounded = (valid & np.isfinite(lower) & (lower > threshold) & ~rejected[active]
                       & np.isfinite(ceiling) & (ceiling < score_floor))
            upper[active] = np.where(bounded, ceiling, np.nan)
    return result()


def _cached_loss_lower_bounds(times, ridge, weight, factors, emissions, sigma, fraction, high):
    """Reuse exact numerical inputs under the scoring context's memory limit."""
    cache = _ridge_fit_cache.get()
    arrays = times, ridge, weight, factors, emissions
    if cache is None:
        return _loss_lower_bounds(*arrays, sigma, fraction, high)
    entries = cache.screen_entries
    if cache.screen_limit <= 0 or cache.max_entries <= 0:
        entries.clear()
        cache.screen_bytes = 0
        return _loss_lower_bounds(*arrays, sigma, fraction, high)
    if np.geterr()["under"] != "ignore":
        # The numerical kernel inherits underflow handling. Preserve any
        # requested warning/exception instead of hiding it behind a cache hit.
        return _loss_lower_bounds(*arrays, sigma, fraction, high)
    # Layout affects reduction order. Keys retain input bytes and layout, but
    # never the much larger propagation arrays themselves. Parameters have
    # already been converted to finite Python floats by the public validator.
    key = (_loss_lower_bounds, tuple(value.hex() for value in (sigma, fraction, high)),
           tuple((value.dtype.str, value.shape, value.strides, value.flags.aligned,
                  hashlib.sha256(value.tobytes()).digest()) for value in arrays))
    # A caller may lower a budget between requests; enforce that budget on hits
    # as well as inserts rather than retaining an oversized previous context.
    while entries and (len(entries) > cache.max_entries or
                       cache.screen_bytes + sys.getsizeof(entries) > cache.screen_limit):
        _, (_, removed) = entries.popitem(last=False)
        cache.screen_bytes -= removed
    previous = entries.get(key)
    if previous is not None:
        entries.move_to_end(key)
        return previous[0]
    evidence = _loss_lower_bounds(*arrays, sigma, fraction, high)
    if evidence is None:
        return None

    def key_size(value):
        return sys.getsizeof(value) + (sum(map(key_size, value)) if isinstance(value, tuple) else 0)

    # Charge array data conservatively even if getsizeof already includes it.
    # Include entry containers and the OrderedDict's actual backing allocation.
    size = key_size(key) + sum(sys.getsizeof(value) + value.nbytes for value in evidence) + 256
    if size <= cache.screen_limit:
        while entries and (len(entries) >= cache.max_entries or
                           cache.screen_bytes + size + sys.getsizeof(entries) > cache.screen_limit):
            _, (_, removed) = entries.popitem(last=False)
            cache.screen_bytes -= removed
        # These arrays stay private. Public rejection and ceiling arrays are
        # created anew, so caller mutations cannot change cached evidence.
        for value in evidence:
            value.setflags(write=False)
        entries[key] = (evidence, size)
        cache.screen_bytes += size
        while entries and cache.screen_bytes + sys.getsizeof(entries) > cache.screen_limit:
            _, (_, removed) = entries.popitem(last=False)
            cache.screen_bytes -= removed
    return evidence


def _loss_lower_bounds(times, ridge, weight, factors, emissions, sigma, fraction, high):
    """Compute the existing dual bound without any candidate retention floor."""
    _, first = np.unique(times, return_index=True)
    first = np.sort(first)
    count = min(48, len(first))
    if count < 3:
        return None
    selected = first[np.linspace(0, len(first)-1, count, dtype=int)]
    active = np.flatnonzero(np.all(np.isfinite(factors), axis=1) & np.all(factors > 0, axis=1)
                            & np.all(np.isfinite(emissions), axis=1))
    if not len(active):
        return None
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
    return active, valid, lower
