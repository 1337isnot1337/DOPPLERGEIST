"""Bounded reconciliation of measured tonal tracks; no physical-source inference.

All time differences below are seconds. Pairwise constant-scale fits have one
parameter; group-wide reconciliation prevents weak transitive bridges.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib

import numpy as np
from scipy import ndimage


class DiscoveryError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass
class Ridge:
    points: np.ndarray
    origins: tuple


def identifier(prefix, points, source=""):
    # IDs depend on observations, not input enumeration or proposal count.
    values = np.ascontiguousarray(points[:, :3], dtype="<f8")
    return prefix + hashlib.sha256(source.encode() + values.tobytes()).hexdigest()[:20]


def key(ridge):
    p = ridge.points
    return (float(p[0, 0]), float(np.median(p[:, 1])), identifier("", p))


def intervals(times, hop):
    """Union of observation cells, not of spectrogram-window footprints."""
    result = []
    for t in sorted(set(float(t) for t in times)):
        left, right = max(0.0, t - hop / 2), t + hop / 2
        if result and left <= result[-1][1] + 1e-8:
            result[-1][1] = max(result[-1][1], right)
        else:
            result.append([left, right])
    return result


def uncertainty(points, settings):
    f = points[:, 1]
    smooth = ndimage.median_filter(f, size=min(5, len(f) // 2 * 2 + 1), mode="nearest")
    return float(max(1 / settings.window_s, 1.4826 * np.median(np.abs(f - smooth))))


def aligned(a, b, settings):
    # Use measured times and interpolate only within a supported observation gap.
    first, last = max(a[0, 0], b[0, 0]), min(a[-1, 0], b[-1, 0])
    times = a[(a[:, 0] >= first) & (a[:, 0] <= last), 0]
    if len(times) < 3:
        return None
    following = np.clip(np.searchsorted(b[:, 0], times), 0, len(b) - 1)
    previous = np.maximum(0, following - 1)
    exact = np.abs(b[following, 0] - times) < 1e-7
    supported = exact | ((b[following, 0] - b[previous, 0] <= settings.max_gap_s)
                         & (times >= b[previous, 0]))
    times = times[supported]
    if len(times) < 3:
        return None
    return times, np.interp(times, a[:, 0], a[:, 1]), np.interp(times, b[:, 0], b[:, 1])


def motion(points, settings):
    """Evidence and explicit rejection thresholds, independent of duration gate."""
    t, f, w = points[:, :3].T
    cells = intervals(t, settings.hop_s)
    observed = sum(right - left for left, right in cells)
    span = t[-1] - t[0] + settings.hop_s
    sigma = uncertainty(points, settings)
    smooth = ndimage.median_filter(f, size=5, mode="nearest")
    dt = np.diff(t)
    # Missing intervals do not contribute to moving fraction or smoothness.
    valid = dt <= settings.max_gap_s
    slopes = np.diff(smooth) / dt
    excursion = float(np.quantile(smooth, .95) - np.quantile(smooth, .05))
    required = max(settings.min_drop_hz, float(np.median(f)) * settings.min_fractional_drop, 4 * sigma)
    moving = valid & (np.abs(slopes) > max(.05, excursion / max(span, 1) * .2))
    moving_fraction = float(np.sum(dt[moving]) / max(np.sum(dt[valid]), settings.hop_s))
    # Local prediction on actual timestamps, with uncertainty in Hz and slope.
    errors = []
    for i in range(2, len(t)):
        if dt[i - 1] > settings.max_gap_s:
            continue
        first = max(0, i - 5)
        local_dt = np.diff(t[first:i])
        local_good = local_dt <= settings.max_gap_s
        rates = np.diff(f[first:i]) / local_dt
        if not np.any(local_good):
            continue
        rate = float(np.median(rates[local_good]))
        tolerance = 3 * sigma + max(.5, abs(rate) * .5) * dt[i - 1]
        errors.append(abs(f[i] - f[i - 1] - rate * dt[i - 1]) / tolerance)
    discontinuity = float(np.quantile(errors, .95)) if errors else 0.0
    signs = np.sign(slopes[moving])
    # A turn requires a sustained resolved leg; repeated reversals are modulation
    # or unresolved wandering, not a compulsory descending-flight template.
    runs = []
    for sign, duration, observed in zip(np.sign(slopes), dt, valid):
        if not observed or abs(sign) == 0:
            continue
        if runs and runs[-1][0] == sign:
            runs[-1][1] += min(duration, settings.hop_s)
        else:
            runs.append([sign, min(duration, settings.hop_s)])
    sustained = [sign for sign, duration in runs if duration >= max(1.5, span * .08)]
    turns = sum(a != b for a, b in zip(sustained, sustained[1:]))
    total_variation = float(np.sum(np.abs(np.diff(smooth))[valid]))
    variation_ratio = total_variation / max(excursion, sigma)
    direction = "stationary"
    if len(signs):
        direction = "turning" if turns else ("rising" if np.median(signs) > 0 else "falling")
    metrics = dict(observed_duration_s=float(observed), span_s=float(span), support_fraction=float(observed / span),
                   frequency_excursion_hz=excursion, required_excursion_hz=float(required),
                   frequency_uncertainty_hz=sigma, moving_fraction=moving_fraction,
                   prediction_error_q95=discontinuity, sustained_turns=int(turns),
                   variation_ratio=float(variation_ratio), median_contrast=float(np.median(w)), direction=direction)
    checks = [(excursion >= required, "unresolved_frequency_motion", excursion, required, ">="),
              (moving_fraction >= .35, "insufficient_distributed_motion", moving_fraction, .35, ">="),
              (discontinuity <= 1, "discontinuous_motion", discontinuity, 1, "<="),
              (turns <= 1, "repeated_modulation", turns, 1, "<="),
              (variation_ratio <= 2.8, "wandering_or_modulation", variation_ratio, 2.8, "<=")]
    reasons = [dict(reason=name, measured=float(value), threshold=float(limit), comparison=op)
               for passed, name, value, limit, op in checks if not passed]
    return metrics, reasons


class Associations:
    def __init__(self, settings):
        self.limit = settings.max_associations
        self.count = 0
        self.decisions = []
        self.decision_counts = Counter()
        self.trace_limit = settings.max_diagnostic_traces

    def charge(self):
        self.count += 1
        if self.count > self.limit:
            raise DiscoveryError("association_budget_exceeded", f"Association work exceeded {self.limit} pairs")

    def record(self, kind, left, right, **evidence):
        self.decision_counts[kind] += 1
        if len(self.decisions) < self.trace_limit:
            self.decisions.append(dict(kind=kind, left=list(left.origins), right=list(right.origins), **evidence))


def combine(a, b):
    points = np.concatenate((a.points, b.points))
    # Deterministic tie break, strongest contrast per timestamp; no invented data.
    points = points[np.lexsort((points[:, 1], -points[:, 2], points[:, 0]))]
    _, keep = np.unique(points[:, 0], return_index=True)
    return Ridge(points[np.sort(keep)], tuple(sorted(set(a.origins + b.origins))))


def deduplicate(ridges, settings, work):
    result = []
    for ridge in sorted(ridges, key=key):
        for i, previous in enumerate(result):
            if previous.points[-1, 0] < ridge.points[0, 0]:
                continue
            # Tracks measured in the same chunk can be near-unison components.
            if {x.split(":")[0] for x in ridge.origins} & {x.split(":")[0] for x in previous.origins}:
                continue
            if abs(np.median(ridge.points[:, 1]) - np.median(previous.points[:, 1])) > .2 * np.median(ridge.points[:, 1]):
                continue
            work.charge()
            shared = aligned(ridge.points, previous.points, settings)
            if shared is None or len(shared[0]) < 8:
                continue
            residual = float(np.quantile(np.abs(shared[1] - shared[2]), .95))
            tolerance = .6 / settings.window_s
            # Whole overlap agreement prevents reconciling paths that branch.
            if residual <= tolerance:
                work.record("duplicate_chunk_measurement", ridge, previous, residual_q95_hz=residual, threshold_hz=tolerance)
                result[i] = combine(previous, ridge)
                break
        else:
            result.append(ridge)
    return sorted(result, key=key)


def stitch(ridges, settings, work):
    ridges = sorted(ridges, key=key)
    incoming, outgoing = [[] for _ in ridges], [[] for _ in ridges]
    for i, left in enumerate(ridges):
        a = left.points
        for j in range(i + 1, len(ridges)):
            right, b = ridges[j], ridges[j].points
            gap = b[0, 0] - a[-1, 0]
            if b[0, 0] > a[-1, 0] + settings.max_fragment_gap_s:
                break
            if gap <= settings.hop_s * 1.1:
                continue
            if abs(b[0, 1] - a[-1, 1]) > .3 * a[-1, 1]:
                continue
            work.charge()
            if len(a) < 4 or len(b) < 4:
                continue
            tail, head = a[a[:, 0] >= a[-1, 0] - 4], b[b[:, 0] <= b[0, 0] + 4]
            if len(tail) < 3 or len(head) < 3:
                continue
            sa = float(np.polyfit(tail[:, 0] - tail[-1, 0], tail[:, 1], 1)[0])
            sb = float(np.polyfit(head[:, 0] - head[0, 0], head[:, 1], 1)[0])
            sigma = uncertainty(a, settings) + uncertainty(b, settings)
            tolerance = 2 * sigma + .25 * min(abs(sa), abs(sb)) * gap
            error = max(abs(b[0, 1] - a[-1, 1] - sa * gap), abs(b[0, 1] - a[-1, 1] - sb * gap))
            # Both observed legs must move in the same direction. A turn in an
            # unobserved gap is deliberately unresolved.
            support = sum(y - x for x, y in intervals(np.r_[a[:, 0], b[:, 0]], settings.hop_s))
            if (sa * sb <= 0 or min(abs(sa), abs(sb)) < .1 or
                max(abs(sa), abs(sb)) > 3 * min(abs(sa), abs(sb)) or
                gap > .35 * support or error > tolerance):
                continue
            outgoing[i].append(j)
            incoming[j].append(i)
            work.record("continuation_candidate", left, right, gap_s=float(gap), prediction_error_hz=float(error), threshold_hz=float(tolerance))
    following = {i: js[0] for i, js in enumerate(outgoing) if len(js) == 1 and len(incoming[js[0]]) == 1}
    for i, js in enumerate(outgoing):
        for j in js:
            work.record("stitch" if following.get(i) == j else "ambiguous_continuation", ridges[i], ridges[j])
    consumed, result = set(), []
    for i, ridge in enumerate(ridges):
        if i in consumed:
            continue
        current, joined = i, ridge
        while current in following:
            current = following[current]
            joined = combine(joined, ridges[current])
            consumed.add(current)
        result.append(joined)
    return result


def family(scales, tolerance=.006):
    """Minimum-complexity integer family, bounded to orders 1..12.

    Absence of this secondary model does not prohibit coherent nonharmonic
    episodes, which require stronger envelope evidence instead.
    """
    scales = np.asarray(scales) / min(scales)
    fits = []
    for base in range(1, 13):
        orders = np.rint(scales * base).astype(int)
        if max(orders) <= 12 and np.max(np.abs(scales - orders / base) / scales) <= tolerance:
            fits.append(orders.tolist())
    return min(fits, key=lambda orders: (sum(orders), orders)) if fits else None


def related(a, b, settings):
    shared = aligned(a, b, settings)
    if shared is None or len(shared[0]) < 8:
        return None
    t, f, g = shared
    support = len(t) * settings.hop_s
    if support < .6 * min(len(a), len(b)) * settings.hop_s:
        return None
    scale = float(np.exp(np.median(np.log(g / f))))
    sigma = uncertainty(b, settings) + scale * uncertainty(a, settings)
    error = float(np.quantile(np.abs(g - scale * f), .9))
    # Uncertainty cannot license an arbitrary ratio fit to unresolved motion.
    excursion = min(float(np.ptp(f)) * scale, float(np.ptp(g)))
    if excursion < max(6 * sigma, .03 * np.median(g)) or error > min(2 * sigma, .004 * np.median(g)):
        return None
    corr = float(np.corrcoef(f, g)[0, 1]) if np.std(f) > 0 and np.std(g) > 0 else 0.0
    if not np.isfinite(corr) or corr < .96:
        return None
    harmonic = family([1, scale])
    envelope = None
    if a.shape[1] > 3 and b.shape[1] > 3:
        x, y = np.interp(t, a[:, 0], a[:, 3]), np.interp(t, b[:, 0], b[:, 3])
        if min(np.std(x), np.std(y)) >= 1:
            envelope = float(np.corrcoef(x, y)[0, 1])
    if harmonic is None and (envelope is None or not np.isfinite(envelope) or envelope < .65):
        return None
    # Contradictory measured envelopes block even a convenient integer ratio.
    if envelope is not None and np.isfinite(envelope) and envelope < -.25:
        return None
    return dict(scale=scale, residual_q90_hz=error, threshold_hz=float(min(2 * sigma, .004 * np.median(g))),
                frequency_correlation=corr, envelope_correlation=envelope,
                shared_observations=int(len(t)), integer_orders=harmonic)


def reconcile(ridges, settings, work):
    """Reconcile strong connections under one group-wide scale model.

    Every member of a group of >=3 needs two resolved-motion witnesses. Every
    overlapping pair is checked against the joint fit, even when its own span
    is too short to establish motion. This permits partial harmonic support
    without permitting a chain of single weak bridges.
    """
    ridges = sorted(ridges, key=key)
    edges = {}
    for i, a in enumerate(ridges):
        for j in range(i + 1, len(ridges)):
            b = ridges[j]
            if b.points[0, 0] > a.points[-1, 0]:
                break
            work.charge()
            evidence = related(a.points, b.points, settings)
            if evidence:
                edges[i, j] = evidence
    def fit(indices):
        work.charge()
        if len(indices) > settings.max_episode_components:
            return None
        positions = {x:i for i,x in enumerate(indices)}
        internal = []
        for ix,x in enumerate(indices):
            for y in indices[ix+1:]:
                work.charge()
                if (x,y) in edges:
                    internal.append((x,y,edges[x,y]))
        if len(indices)>2 and any(sum(x==i or y==i for x,y,_ in internal)<2 for i in indices):
            return None
        matrix, values = [], []
        for x,y,e in internal:
            row = np.zeros(len(indices))
            row[positions[y]], row[positions[x]] = 1., -1.
            matrix.append(row[1:]); values.append(np.log(e["scale"]))
        scales = np.exp(np.r_[0., np.linalg.lstsq(np.asarray(matrix),values,rcond=None)[0]])
        for ix,x in enumerate(indices):
            for iy in range(ix+1,len(indices)):
                y = indices[iy]
                work.charge()
                shared = aligned(ridges[x].points,ridges[y].points,settings)
                if shared is None:
                    continue
                ratio = scales[iy]/scales[ix]
                error = float(np.quantile(np.abs(shared[2]-ratio*shared[1]),.9))
                sigma = uncertainty(ridges[y].points,settings)+ratio*uncertainty(ridges[x].points,settings)
                if error > 2*sigma:
                    return None
        return scales.tolist()
    groups = [{i} for i in range(len(ridges))]
    owners = {i:g for g in groups for i in g}
    fitted = {frozenset(g):[1.] for g in groups}
    ordered = sorted(edges.items(),key=lambda item:(item[1]["residual_q90_hz"]/item[1]["threshold_hz"],item[0]))
    changed = True
    while changed:
        changed = False
        for (i,j),evidence in ordered:
            left, right = owners[i], owners[j]
            if left is right:
                continue
            scales = fit(sorted(left|right))
            if scales is None:
                continue
            work.record("joint_episode",ridges[i],ridges[j],**evidence)
            left.update(right)
            for member in right:
                owners[member] = left
            groups.remove(right)
            fitted[frozenset(left)] = scales
            changed = True
    for (i,j),evidence in ordered:
        if owners[i] is not owners[j]:
            work.record("unresolved_episode_relation",ridges[i],ridges[j],
                        reason="insufficient_joint_witnesses_or_inconsistent_group_fit",**evidence)
    result = []
    for group in groups:
        indices = sorted(group)
        scales = fitted[frozenset(group)]
        result.append(([ridges[x] for x in indices],scales,family(scales)))
    return result
