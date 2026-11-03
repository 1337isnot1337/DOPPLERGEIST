"""Conservative detected-event adapters and robust emission-time ridge matching.

Scores are penalized residuals, never probabilities. Geometry from a straight-pass
audio fit is a proposal diagnostic, not a reliable exclusion bound for real tracks.
"""
from collections import OrderedDict
from bisect import bisect_left, bisect_right
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
import hashlib
from itertools import chain

import numpy as np
from pyproj import Transformer
from scipy.optimize import minimize

from .geometry import Track, ecef


@dataclass
class RidgeTimes:
    time: np.ndarray


_ridge_fit_cache = ContextVar("ridge_fit_cache", default=None)


def _fit_argument_key(value):
    """Preserve scalar precision and array shape without rounding fit inputs."""
    if type(value) is float:
        return (float, value.hex())
    if type(value) in (int, bool):
        return (type(value), value)
    if type(value) in (list, tuple):
        return (type(value), tuple(_fit_argument_key(item) for item in value))
    if type(value) is np.ndarray or isinstance(value, np.generic):
        array = np.asarray(value)
        if array.dtype.kind in "biuf":
            return (type(value), array.dtype.str, array.shape, array.tobytes())
    raise TypeError("Unsupported fit-cache argument representation")


class _RidgeFitCache:
    """Bounded reuse for an immutable set of tracks within one scoring batch."""

    def __init__(self, max_entries):
        self.max_entries = max_entries
        self.entries = OrderedDict()

    def fit(self, track, observer, measurement, start_time, f0_bounds, c, sigma_hz, drift_fraction):
        arguments = (track, observer, measurement, start_time, f0_bounds, c, sigma_hz, drift_fraction)
        try:
            parameters = tuple(_fit_argument_key(value) for value in
                               (observer, start_time, f0_bounds, c, sigma_hz, drift_fraction))
        except (TypeError, ValueError):
            # Let the fitter handle custom representations and their validation.
            return _fit_ridge_uncached(*arguments)
        # Measurements may be equivalent copies or modified arrays. Hash the
        # numeric inputs actually used by the fit, without retaining their data.
        spec, ridge, weight, _ = measurement
        observed = hashlib.sha256()
        for values in (spec.time, ridge, weight):
            values = np.asarray(values, dtype=float)
            observed.update(repr(values.shape).encode())
            observed.update(values.tobytes())
        key = (id(track), parameters, observed.digest())
        if key in self.entries:
            self.entries.move_to_end(key)
            return deepcopy(self.entries[key][1])
        result = _fit_ridge_uncached(*arguments)
        # Keep the track alive so a different trajectory cannot reuse its id.
        # The enclosing batch already owns these tracks. Exceptions are not cached.
        self.entries[key] = (track, deepcopy(result))
        if len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        return result


def _cache_ridge_fits(function, *, max_entries=4096):
    """Reuse fits only while this batch's tracks stay unchanged.

    Each call has at most 4,096 entries by default. Context-local state prevents
    reuse between concurrent jobs, nested batches or later calls. Cached results
    are copied so candidate diagnostics remain independently mutable.
    """
    if type(max_entries) is not int or max_entries < 1:
        raise ValueError("Fit-cache capacity must be a positive integer")

    @wraps(function)
    def run(*args, **kwargs):
        token = _ridge_fit_cache.set(_RidgeFitCache(max_entries))
        try:
            return function(*args, **kwargs)
        finally:
            _ridge_fit_cache.reset(token)

    return run


def _frequency_scale(event):
    quality = event.get("quality", {})
    return quality.get("frequency_loss_scale_hz", quality.get("frequency_sigma_hz",
                       max(1.0, quality.get("frequency_uncertainty_hz", 1.0))))


def _source_fit(factor, u, y, weight, bounds, cap, scale):
    """Exact two-variable box least squares; avoid iterative bounded solves."""
    a = np.sum(weight*factor**2)
    r = np.sum(weight*factor*y)
    if not cap:
        return np.array([np.clip(r/a, *bounds), 0.0])
    b = np.sum(weight*factor**2*u)
    prior = (2*scale/cap)**2
    d = np.sum(weight*factor**2*u**2)+prior
    s = np.sum(weight*factor*u*y)
    determinant = a*d-b*b
    unconstrained = np.array([(r*d-s*b)/determinant, (s*a-r*b)/determinant])
    if bounds[0] <= unconstrained[0] <= bounds[1] and abs(unconstrained[1]) <= cap:
        return unconstrained
    # A convex quadratic's constrained minimum lies on one of these four edges.
    candidates = np.array([[f, np.clip((s-b*f)/d, -cap, cap)] for f in bounds] +
                          [[np.clip((r-b*drift)/a, *bounds), drift] for drift in (-cap, cap)])
    residuals = factor*(candidates[:, :1]+candidates[:, 1:]*u)-y
    costs = np.sum(weight*residuals**2, axis=1)+prior*candidates[:, 1]**2
    return candidates[np.argmin(costs)]


def _altitude_bias(track, bias_m):
    """Shift one geodetic trajectory while preserving its measured derivatives."""
    displacement = ecef(track.lat, track.lon, track.altitude+bias_m)-track.xyz
    velocity = track.speed_vector(track.time)+np.gradient(displacement, track.relative_time, axis=0)
    shifted = Track(track.id, track.time, track.lat, track.lon, track.altitude+bias_m,
                    track.typecode, velocity)
    shifted.altitude_basis = getattr(track, "altitude_basis", ["unspecified"]*len(track.time))
    return shifted


def predict_fitted_ridge(track, observer, receive_times_s, diagnostics, c=343.0):
    """Render the frozen fitted source model; unsupported track times stay NaN."""
    factor, emitted, _ = track.acoustic(receive_times_s, observer, c)
    slope = diagnostics.get("source_drift_hz_s", 0.0)
    if slope and "source_reference_emission_time_s" not in diagnostics:
        raise ValueError("A drifting-source prediction needs its fitted emission-time reference")
    reference = diagnostics.get("source_reference_emission_time_s", 0.0)
    return factor*(diagnostics["f0_hz"]+slope*(emitted-reference))


def association_candidates(table, events, offset_tolerance_s=5.0, time_origin=None,
                           time_tolerance_s=5.0, silence=None, min_events=1,
                           max_events=None, max_candidates=20000):
    """Bounded subset hypotheses, retaining explicitly unmatched proposals.

    Default to every independent group. Intersect shared-clock intervals before
    extending a branch; do not materialize impossible Cartesian products. Index
    entries, branch visits and stored assignments share an explicit work budget.
    Exceeding it fails visibly so the outer driver reports incomplete coverage.
    """
    from .search import filter_event
    max_events = max(min_events, len(events)) if max_events is None else max_events
    if not 1 <= min_events <= max_events or max_candidates < 1:
        raise ValueError("Invalid association event/candidate budget")
    candidates, examined, work = [], 0, 0
    def reserve(units):
        nonlocal work
        work += units
        if work > max_candidates*20:
            raise ValueError("Association work/storage budget exceeded; search is incomplete")
    reserve(len(table))
    table = table.reset_index(drop=True)
    records = table.to_dict("records")
    grouped, survivors = [], []
    for event in events:
        frame = filter_event(table, event, time_origin, time_tolerance_s)
        reserve(len(frame))
        survivors.append(len(frame))
        groups = {}
        tolerance = event.get("quality", {}).get("cpa_tolerance_s", 0) + offset_tolerance_s/2
        for point, group in frame.groupby("point_id"):
            indices = list(group.index)
            reserve(len(indices) * max(1, len(indices).bit_length()))
            ordered = sorted((records[i]["receive_time"] - event["cpa_receive_s"], i) for i in indices)
            groups[point] = ([start - tolerance for start, _ in ordered],
                             [start + tolerance for start, _ in ordered],
                             [index for _, index in ordered])
        grouped.append(groups)
    by_point = {p: frame for p, frame in table.groupby("point_id")}

    def indexed_options(index, point_id, lower, upper):
        starts, ends, indices = grouped[index][point_id]
        # These endpoints use exactly the arithmetic of the intersection below,
        # including floating-point rounding at inclusive boundaries.
        left = bisect_left(ends, lower)
        right = bisect_right(starts, upper)
        # The returned original-order slice must itself fit the work budget;
        # reserve before allocating and sorting it at every branch.
        selected = max(0, right - left)
        reserve(selected * max(1, selected.bit_length()))
        return chain((records[i] for i in sorted(indices[left:right])), [None])

    for point_id in sorted(set().union(*(g.keys() for g in grouped))):
        available = [i for i, group in enumerate(grouped) if point_id in group]
        if len(available) < min_events:
            continue
        lower, upper = (-np.inf, np.inf) if time_origin is None else (time_origin-time_tolerance_s, time_origin+time_tolerance_s)
        path, used = [], set()
        frames = [(0, iter(indexed_options(available[0], point_id, lower, upper)), lower, upper, 0)]
        while frames:
            cursor, options, lower, upper, depth = frames[-1]
            while len(path) > depth:
                _, old = path.pop()
                used.remove((old["flight_id"], old["emission_time"]))
            try:
                row = next(options)
            except StopIteration:
                frames.pop()
                continue
            reserve(1)
            lo, hi = lower, upper
            index = available[cursor]
            if row is not None:
                identity = (row["flight_id"], row["emission_time"])
                if identity in used:
                    continue
                start = row["receive_time"]-events[index]["cpa_receive_s"]
                tolerance = events[index].get("quality", {}).get("cpa_tolerance_s", 0)+offset_tolerance_s/2
                lo, hi = max(lo, start-tolerance), min(hi, start+tolerance)
                if lo > hi:
                    continue
                path.append((index, row))
                used.add(identity)
            following = cursor+1
            if len(path)+len(available)-following < min_events:
                continue
            if following < len(available) and len(path) < max_events:
                frames.append((following, iter(indexed_options(available[following], point_id, lo, hi)), lo, hi, len(path)))
                continue
            if len(path) < min_events:
                continue
            examined += 1
            passes = tuple(row for _, row in path)
            if silence and len(path) > 1:
                frame = by_point[point_id]
                reserve(len(frame))
                margin = silence.get("edge_margin_s", 60)
                distance = max(p["distance_m"] for p in passes)*silence.get("distance_multiplier", 1)
                between = frame[(frame.receive_time > passes[0]["receive_time"]+margin) &
                                (frame.receive_time < passes[-1]["receive_time"]-margin) & (frame.distance_m <= distance)]
                if any((r.flight_id, r.emission_time) not in used for r in between.itertuples()):
                    continue
            if len(candidates) >= max_candidates:
                raise ValueError("Association candidate budget exceeded; search is incomplete")
            reserve(len(path))
            candidates.append({"point_id": point_id, "passes": passes, "event_indices": [i for i, _ in path],
                               "recording_start_bounds_s": [float(lo), float(hi)]})
    return candidates, {"per_event_survivors": survivors, "survivors": len(candidates),
                        "hypotheses_examined": examined, "work_units": work, "max_matched_events": max_events,
                        "event_cap_limited": max_events < len(events),
                        "unmatched_proposals_allowed": True}


def association_score(result, events):
    """Compare different matched subsets using bounded normalized support.

    One well-fitted independent event contributes up to one unit. A poor event
    invalidates that hypothesis; another subset can leave it unmatched. This is
    a ranking heuristic, not a likelihood or a calibrated confidence statistic.
    """
    limits = [3 * _frequency_scale(e) for e in events]
    losses = [-s for s in result["event_scores"]]
    supported = all(np.isfinite(v) and v <= limit for v, limit in zip(losses, limits))
    return dict(result, residual_score=result["score"],
                score=float(sum(1-v/limit for v, limit in zip(losses, limits))) if supported else -np.inf,
                score_kind="matched_group_support_minus_normalized_residual")


def prepare_events(detected_events, c=343.0, max_distance_m=20000.0):
    """Adapt contract ridge points to existing search inputs without truth hints.

    Keep every ridge in a harmonic group as evidence for one pass. Integer
    harmonics are normalized to its lowest observed band; no fundamental needs
    to be present. Groups with inconsistent ratios must be fixed by discovery.
    Timing uncertainty spans the observed window, because a curved track need
    not have its geometric CPA at a fitted straight-pass center.
    """
    groups = {}
    for event in detected_events:
        key = event.get("harmonic_group_id") or event["event_id"]
        groups.setdefault(key, []).append(event)
    settings, measurements = [], []
    for members in groups.values():
        reference = min(members, key=lambda e: np.median([p["frequency_hz"] for p in e["ridge"]]))
        reference_time = np.array([p["time_s"] for p in reference["ridge"]])
        reference_frequency = np.array([p["frequency_hz"] for p in reference["ridge"]])
        times, frequencies, weights = [], [], []
        for member in members:
            t = np.array([p["time_s"] for p in member["ridge"]], dtype=float)
            f = np.array([p["frequency_hz"] for p in member["ridge"]], dtype=float)
            w = np.array([p.get("weight", 1.0) for p in member["ridge"]], dtype=float)
            overlapping = (t >= reference_time[0]) & (t <= reference_time[-1])
            if not overlapping.any():
                raise ValueError("Harmonic-group ridges must overlap in recording time")
            ratio = np.median(f[overlapping] / np.interp(t[overlapping], reference_time, reference_frequency))
            harmonic = max(1, round(ratio))
            if abs(ratio / harmonic - 1) > 0.05:
                raise ValueError("Harmonic group does not have consistent integer frequency ratios")
            times.extend(t)
            frequencies.extend(f / harmonic)
            # Equal aggregate weight per ridge prevents duplicated harmonics
            # from manufacturing additional independent events.
            weights.extend(w / max(np.sum(w), 1e-12))
        order = np.argsort(times, kind="stable")
        t, f, w = (np.asarray(a)[order] for a in (times, frequencies, weights))
        if len(t) < 10 or not np.all(np.isfinite(np.column_stack((t, f, w)))) or np.any(w < 0):
            raise ValueError("Matching requires at least ten finite, nonnegative-weight ridge samples")
        start, end = min(e["start_s"] for e in members), max(e["end_s"] for e in members)
        center = float(reference.get("cpa_receive_s", (start + end) / 2))
        quality = dict(reference.get("quality", {}))
        quality.setdefault("frequency_loss_scale_hz", max(1.0, _frequency_scale(reference)))
        quality["cpa_tolerance_s"] = max(center - start, end - center)
        # A subsonic source gives f_source = f_received * (1 + v_radial/c).
        # These broad bounds are independent of an unreliable straight-pass fit.
        event = dict(reference, start_s=start, end_s=end, cpa_receive_s=center,
                     speed_range_mps=[1.0, 0.9 * c], slant_range_m=[1.0, max_distance_m],
                     f0_range_hz=[float(f.min() * 0.1), float(f.max() * 1.9)], quality=quality)
        event["event_ids"] = [e["event_id"] for e in members]
        settings.append(event)
        measurements.append((RidgeTimes(t), f, w, {}))
    order = np.argsort([e["cpa_receive_s"] for e in settings])
    return [settings[i] for i in order], [measurements[i] for i in order]


def _fit_ridge_uncached(track, observer, measurement, start_time, f0_bounds, c=343.0,
                        sigma_hz=1.0, drift_fraction=0.02):
    """Bounded linear source drift at emission time, with robust residual loss.

    Drift is bounded to a fraction of source frequency over the measured event.
    It cannot supply independent event time shifts or arbitrary curve warping.
    Zero-weight samples are missing evidence; negative/nonfinite weights fail.
    """
    spec, ridge, weight, _ = measurement
    times, ridge, weight = (np.asarray(a, dtype=float) for a in (spec.time, ridge, weight))
    if times.shape != ridge.shape or times.shape != weight.shape or times.ndim != 1:
        raise ValueError("Ridge time, frequency and weight must be matching one-dimensional arrays")
    if not np.isfinite(sigma_hz) or sigma_hz <= 0 or not 0 <= drift_fraction <= 0.1:
        raise ValueError("Need positive frequency uncertainty and drift fraction in [0, 0.1]")
    if not np.all(np.isfinite(weight)) or np.any(weight < 0):
        raise ValueError("Ridge weights must be finite and nonnegative")
    measured = np.isfinite(times) & np.isfinite(ridge) & (weight > 0)
    failed = {"score": -np.inf, "f0_hz": np.nan, "support_fraction": 0.0}
    if measured.sum() < 10:
        return failed
    factor, emission, _ = track.acoustic(start_time + times[measured], observer, c)
    if not np.all(np.isfinite(factor)) or not np.all(np.isfinite(emission)):
        return failed
    y, w = ridge[measured], weight[measured]
    independent_samples = len(np.unique(times[measured]))
    w = w * independent_samples / w.sum()
    span = max(float(np.ptp(emission)), 1e-9)
    u = (emission - (emission.min() + emission.max()) / 2) / span
    cap = float(np.clip(np.median(y / factor), *f0_bounds)) * drift_fraction
    effective = w.copy()
    for _ in range(6):
        fit = _source_fit(factor, u, y, effective, f0_bounds, cap, sigma_hz)
        residual = factor*(fit[0]+fit[1]*u)-y
        effective = w / np.sqrt(1 + (residual / sigma_hz) ** 2)
    loss = np.average(2 * sigma_hz**2 * (np.sqrt(1 + (residual / sigma_hz)**2) - 1), weights=w)
    drift = float(fit[1])
    penalty = (2 * sigma_hz * drift / cap)**2 / independent_samples if cap else 0.0
    return {"score": -float(np.sqrt(loss + penalty)), "f0_hz": float(fit[0]),
            "source_drift_hz": drift, "source_drift_hz_s": drift / span,
            "source_reference_emission_time_s": float((emission.min()+emission.max())/2),
            "source_span_s": span,
            "drift_bound_hz": float(cap), "drift_at_bound": bool(cap and abs(drift) > 0.99 * cap),
            "rmse_hz": float(np.sqrt(np.average(residual**2, weights=w))),
            "support_fraction": 1.0, "sample_count": int(len(y)),
            "independent_sample_count": independent_samples,
            "outlier_fraction": float(np.average(np.abs(residual) > 3 * sigma_hz, weights=w))}


def fit_ridge(track, observer, measurement, start_time, f0_bounds, c=343.0,
              sigma_hz=1.0, drift_fraction=0.02):
    """Fit bounded source drift, optionally reusing an identical batch input."""
    cache = _ridge_fit_cache.get()
    fit = _fit_ridge_uncached if cache is None else cache.fit
    return fit(track, observer, measurement, start_time, f0_bounds, c, sigma_hz, drift_fraction)


def score_ridges(tracks, events, measurements, observer, recording_start_s, c=343.0):
    """Score all events at exactly one recording clock; report nuisance fits."""
    if not events or len(tracks) != len(events) or len(measurements) != len(events):
        raise ValueError("Need exactly one track and measurement for each event")
    diagnostics = []
    for track, event, measurement in zip(tracks, events, measurements):
        quality = event.get("quality", {})
        diagnostics.append(fit_ridge(track, observer, measurement, recording_start_s,
            event["f0_range_hz"], c, _frequency_scale(event),
            quality.get("source_drift_fraction", 0.02)))
    return {"score": float(sum(d["score"] for d in diagnostics)),
            "event_scores": [d["score"] for d in diagnostics],
            "f0_hz": [d["f0_hz"] for d in diagnostics], "event_diagnostics": diagnostics,
            "score_kind": "negative_robust_ridge_loss_hz"}


def refine_candidate(candidate, tracks, events, measurements, terrain, radius_m=500.0,
                     clock_radius_s=5.0, altitude_offsets_m=(-150.0, 0.0, 150.0),
                     crs="EPSG:5070", c=343.0, recording_start_window_s=None):
    """Jointly refine position/shared clock and profile vertical-datum sensitivity.

    A vertical offset changes the observer-to-track relative height; it is a
    sensitivity scenario, not a new terrain measurement or calibrated interval.
    Returned radius describes the explored alternatives only. A boundary optimum
    warns callers that this local search has not enclosed the possible solution.
    """
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    x0, y0 = forward.transform(candidate["lon"], candidate["lat"])
    start = candidate["recording_start_time_s"]
    selected = [tracks[f] for f in candidate["flight_ids"]]
    if "event_indices" in candidate:
        events = [events[i] for i in candidate["event_indices"]]
        measurements = [measurements[i] for i in candidate["event_indices"]]
    if radius_m <= 0 or clock_radius_s < 0 or 0.0 not in altitude_offsets_m:
        raise ValueError("Need positive spatial/nonnegative clock bounds and a nominal zero-altitude scenario")
    lower, upper = -clock_radius_s, clock_radius_s
    if recording_start_window_s is not None:
        lo, hi = recording_start_window_s
        if not np.isfinite([lo, hi]).all() or lo > hi:
            raise ValueError("Recording-start window must be finite and ordered")
        lower, upper = max(lower, lo-start), min(upper, hi-start)
    if lower > upper:
        raise ValueError("Refinement clock bounds do not intersect the recording-start window")
    fixed_clock = lower == upper
    bounds = [(-radius_m, radius_m), (-radius_m, radius_m)]
    initial = np.zeros(2) if fixed_clock else np.array([0.0, 0.0, np.clip(0.0, lower, upper)])
    if not fixed_clock:
        bounds.append((lower, upper))
    profiles = []
    for offset in altitude_offsets_m:
        def evaluate(parameters):
            dt = lower if fixed_clock else parameters[2]
            latlon = inverse.transform(x0 + parameters[0], y0 + parameters[1])
            lon, lat = latlon
            elevation = float(np.asarray(terrain.sample(lat, lon)))
            score = score_ridges(selected, events, measurements, ecef(lat, lon, elevation + offset),
                                  start + dt, c)
            if "event_indices" in candidate:
                score = association_score(score, events)
            return score, lat, lon, elevation
        def objective(parameters):
            value = evaluate(parameters)[0]["score"]
            return -value if np.isfinite(value) else 1e6
        result = minimize(objective, initial, method="Powell", bounds=bounds,
                          options={"xtol": 0.01, "ftol": 1e-7, "maxiter": 60})
        parameters = result.x if objective(result.x) < objective(initial) else initial
        score, lat, lon, elevation = evaluate(parameters)
        if not np.isfinite(score["score"]):
            continue
        dt = lower if fixed_clock else parameters[2]
        spatial_boundary = bool(np.any(np.abs(parameters[:2]) >= radius_m * 0.98))
        clock_boundary = bool(not fixed_clock and min(dt-lower, upper-dt) <= (upper-lower)*0.02)
        profiles.append(dict(score, lat=lat, lon=lon, elev_m=elevation,
            recording_start_time_s=float(start + dt), altitude_offset_m=float(offset),
            boundary_limited=spatial_boundary or clock_boundary,
            position_boundary_limited=spatial_boundary, clock_boundary_limited=clock_boundary,
            optimizer_success=bool(result.success)))
    nominal = next((p for p in profiles if p["altitude_offset_m"] == 0), None)
    if nominal is None:
        raise ValueError("No complete trajectory support for local refinement")
    center = ecef(nominal["lat"], nominal["lon"], 0)
    radius = max(float(np.linalg.norm(ecef(p["lat"], p["lon"], 0) - center)) for p in profiles)
    return dict(candidate, **{k: v for k, v in nominal.items() if k != "altitude_offset_m"},
                time_adjustment_s=float(candidate.get("time_adjustment_s", 0) + nominal["recording_start_time_s"]-start),
                refinement_clock_bounds_s=[float(start+lower), float(start+upper)],
                x=float(forward.transform(nominal["lon"], nominal["lat"])[0]),
                y=float(forward.transform(nominal["lon"], nominal["lat"])[1]),
                sensitivity={"radius_m": radius, "kind": "sensitivity",
                    "method": "profiled_relative_altitude_offsets",
                    "profiles": profiles, "boundary_limited": any(p["boundary_limited"] for p in profiles),
                    "complete": len(profiles) == len(altitude_offsets_m) and all(p["optimizer_success"] for p in profiles)})


def profile_candidate(candidate, tracks, events, measurements, terrain, *,
                      recording_start_window_s=None, radius_m=500.0, clock_radius_s=5.0,
                      altitude_uncertainty_m=150.0, sound_speed_uncertainty_mps=5.0,
                      c=343.0, crs="EPSG:5070"):
    """Run declared perturbations, retaining failures and boundary limitations.

    These finite engineering scenarios are not a calibrated confidence region.
    Frequency offsets and tilts vary each matched ridge separately. Shared-clock
    endpoints, relative height, sound speed and constant-source alternatives are
    reoptimized; no scenario may leave the trusted recording-start window.
    """
    if altitude_uncertainty_m < 0 or not 0 <= sound_speed_uncertainty_mps < c:
        raise ValueError("Sensitivity ranges must be nonnegative and sound speed must remain positive")
    kwargs = dict(radius_m=radius_m, clock_radius_s=clock_radius_s,
                  altitude_offsets_m=(0.0,), crs=crs, c=c,
                  recording_start_window_s=recording_start_window_s)
    nominal = refine_candidate(candidate, tracks, events, measurements, terrain, **kwargs)
    scenarios = [("nominal", "nominal", events, measurements, {})]
    for sign in (-1, 1):
        scenarios.append(("altitude", f"height_{sign:+d}", events, measurements,
                          {"altitude_offsets_m": (0.0, sign*altitude_uncertainty_m)}))
        scenarios.append(("sound_speed", f"sound_speed_{sign:+d}", events, measurements,
                          {"c": c+sign*sound_speed_uncertainty_mps}))
    indices = candidate.get("event_indices", list(range(len(events))))
    altitude_provenance, provenance_failures = {}, []
    terrain_ellipsoidal = (getattr(terrain, "vertical_datum", None) == "ellipsoidal" or
                          getattr(terrain, "geoid", None) is not None or getattr(terrain, "geoid_path", None) is not None)
    if not terrain_ellipsoidal:
        provenance_failures.append({"source": "altitude", "scenario": "terrain",
            "reason": "Ellipsoidal terrain datum is not established"})
    for identity in sorted(set(candidate["flight_ids"])):
        track = tracks[identity]
        basis = getattr(track, "altitude_basis", ["unspecified"])
        basis = [basis] if isinstance(basis, str) else list(basis)
        basis = [str(value) for value in basis]
        altitude_provenance[identity] = sorted(set(basis))
        if not basis or not set(basis) <= {"ellipsoidal", "ellipsoidal_interpolated"}:
            provenance_failures.append({"source": "altitude", "scenario": identity,
                "reason": "Common-datum geometric flight altitude is not established"})
        for sign in (-1, 1):
            scenarios.append(("altitude", f"flight_{identity}_{sign:+d}", events, measurements,
                              {"track_altitude_bias": (identity, sign*altitude_uncertainty_m)}))
    for index in indices:
        spec, ridge, weight, fit = measurements[index]
        times = np.asarray(spec.time)
        tilt = 2*(times-(times.min()+times.max())/2)/max(float(np.ptp(times)), 1e-9)
        scale = _frequency_scale(events[index])
        for pattern, shape in (("offset", np.ones_like(times)), ("tilt", tilt)):
            for sign in (-1, 1):
                changed = list(measurements)
                changed[index] = (spec, np.asarray(ridge)+sign*scale*shape, weight, fit)
                scenarios.append(("frequency", f"event_{index}_{pattern}_{sign:+d}", events, changed, {}))
    constant = [dict(e, quality=dict(e.get("quality", {}), source_drift_fraction=0.0)) for e in events]
    scenarios.append(("source_frequency", "constant_source", constant, measurements, {}))
    lo, hi = nominal["refinement_clock_bounds_s"]
    # A trusted point window is tested exactly; it is never perturbed outward.
    for when in sorted(set((lo, hi))):
        scenarios.append(("clock", f"fixed_clock_{when:.6f}", events, measurements,
                          {"recording_start_window_s": (when, when)}))
    profiles, failures = [], list(provenance_failures)
    center = ecef(nominal["lat"], nominal["lon"], 0)
    radius = 0.0
    boundary = False
    for source, label, scenario_events, scenario_measurements, overrides in scenarios:
        try:
            options = dict(kwargs, **overrides)
            flight_bias = options.pop("track_altitude_bias", None)
            scenario_tracks = tracks
            if flight_bias is not None:
                identity, bias = flight_bias
                scenario_tracks = dict(tracks)
                if bias:
                    scenario_tracks[identity] = _altitude_bias(tracks[identity], bias)
            row = nominal if source == "nominal" else refine_candidate(
                candidate, scenario_tracks, scenario_events, scenario_measurements, terrain, **options)
            # Height scenarios return a nominal plus the perturbed-height fit;
            # retain the latter rather than silently measuring the nominal twice.
            variants = row["sensitivity"]["profiles"] if source == "altitude" else [row]
            for variant in variants:
                displacement = float(np.linalg.norm(ecef(variant["lat"], variant["lon"], 0)-center))
                radius = max(radius, displacement)
                boundary |= variant["boundary_limited"]
                profiles.append({"source": source, "scenario": label,
                    "lat": variant["lat"], "lon": variant["lon"], "score": variant["score"],
                    "recording_start_time_s": variant["recording_start_time_s"],
                    "displacement_m": displacement, "boundary_limited": variant["boundary_limited"],
                    "flight_altitude_bias": None if flight_bias is None else {"flight_id": flight_bias[0], "bias_m": flight_bias[1]},
                    "observer_altitude_offset_m": variant.get("altitude_offset_m", 0.0),
                    "optimizer_success": variant["optimizer_success"]})
            if not row["sensitivity"]["complete"]:
                failures.append({"source": source, "scenario": label, "reason": "Missing altitude scenario support"})
        except ValueError as exc:
            failures.append({"source": source, "scenario": label, "reason": str(exc)})
    sensitivity = {"radius_m": radius, "kind": "sensitivity", "method": "declared_perturbation_profiles",
        "sources": sorted({s[0] for s in scenarios if s[0] != "nominal"}),
        "complete": not failures and all(p["optimizer_success"] for p in profiles),
        "boundary_limited": bool(boundary), "profiles": profiles, "failures": failures,
        "altitude_basis": altitude_provenance,
        "terrain_vertical_datum": "ellipsoidal" if terrain_ellipsoidal else "unestablished",
        "settings": {"altitude_uncertainty_m": altitude_uncertainty_m,
                     "sound_speed_uncertainty_mps": sound_speed_uncertainty_mps,
                     "frequency_scale_hz": [_frequency_scale(events[i]) for i in indices],
                     "clock_bounds_s": [lo, hi]}}
    return dict(nominal, sensitivity=sensitivity)
