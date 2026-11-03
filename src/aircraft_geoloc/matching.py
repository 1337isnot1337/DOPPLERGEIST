"""Conservative detected-event adapters and robust emission-time ridge matching.

Scores are penalized residuals, never probabilities. Geometry from a straight-pass
audio fit is a proposal diagnostic, not a reliable exclusion bound for real tracks.
"""
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from scipy.optimize import lsq_linear, minimize

from .geometry import ecef


@dataclass
class RidgeTimes:
    time: np.ndarray


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


def fit_ridge(track, observer, measurement, start_time, f0_bounds, c=343.0,
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
    design = np.column_stack((factor, factor * u)) if cap else factor[:, None]
    bounds = ([f0_bounds[0], -cap], [f0_bounds[1], cap]) if cap else ([f0_bounds[0]], [f0_bounds[1]])
    effective = w.copy()
    for _ in range(6):
        matrix, target = design * np.sqrt(effective[:, None]), y * np.sqrt(effective)
        if cap:
            matrix = np.vstack((matrix, [0, 2 * sigma_hz / cap]))
            target = np.r_[target, 0.0]
        fit = lsq_linear(matrix, target, bounds=bounds, tol=1e-8)
        residual = design @ fit.x - y
        effective = w / np.sqrt(1 + (residual / sigma_hz) ** 2)
    loss = np.average(2 * sigma_hz**2 * (np.sqrt(1 + (residual / sigma_hz)**2) - 1), weights=w)
    drift = float(fit.x[1]) if cap else 0.0
    penalty = (2 * sigma_hz * drift / cap)**2 / independent_samples if cap else 0.0
    return {"score": -float(np.sqrt(loss + penalty)), "f0_hz": float(fit.x[0]),
            "source_drift_hz": drift, "source_drift_hz_s": drift / span,
            "drift_bound_hz": float(cap), "drift_at_bound": bool(cap and abs(drift) > 0.99 * cap),
            "rmse_hz": float(np.sqrt(np.average(residual**2, weights=w))),
            "support_fraction": 1.0, "sample_count": int(len(y)),
            "independent_sample_count": independent_samples,
            "outlier_fraction": float(np.average(np.abs(residual) > 3 * sigma_hz, weights=w))}


def score_ridges(tracks, events, measurements, observer, recording_start_s, c=343.0):
    """Score all events at exactly one recording clock; report nuisance fits."""
    if not events or len(tracks) != len(events) or len(measurements) != len(events):
        raise ValueError("Need exactly one track and measurement for each event")
    diagnostics = []
    for track, event, measurement in zip(tracks, events, measurements):
        quality = event.get("quality", {})
        diagnostics.append(fit_ridge(track, observer, measurement, recording_start_s,
            event["f0_range_hz"], c, quality.get("frequency_sigma_hz", 1.0),
            quality.get("source_drift_fraction", 0.02)))
    return {"score": float(sum(d["score"] for d in diagnostics)),
            "event_scores": [d["score"] for d in diagnostics],
            "f0_hz": [d["f0_hz"] for d in diagnostics], "event_diagnostics": diagnostics,
            "score_kind": "negative_robust_ridge_loss_hz"}


def refine_candidate(candidate, tracks, events, measurements, terrain, radius_m=500.0,
                     clock_radius_s=5.0, altitude_offsets_m=(-150.0, 0.0, 150.0),
                     crs="EPSG:5070", c=343.0):
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
    if radius_m <= 0 or clock_radius_s <= 0 or 0.0 not in altitude_offsets_m:
        raise ValueError("Need positive refinement bounds and a nominal zero-altitude scenario")
    bounds = [(-radius_m, radius_m), (-radius_m, radius_m), (-clock_radius_s, clock_radius_s)]
    profiles = []
    for offset in altitude_offsets_m:
        def evaluate(parameters):
            latlon = inverse.transform(x0 + parameters[0], y0 + parameters[1])
            lon, lat = latlon
            elevation = float(np.asarray(terrain.sample(lat, lon)))
            score = score_ridges(selected, events, measurements, ecef(lat, lon, elevation + offset),
                                  start + parameters[2], c)
            return score, lat, lon, elevation
        def objective(parameters):
            value = evaluate(parameters)[0]["score"]
            return -value if np.isfinite(value) else 1e6
        result = minimize(objective, np.zeros(3), method="Powell", bounds=bounds,
                          options={"xtol": 0.01, "ftol": 1e-7, "maxiter": 60})
        parameters = result.x if objective(result.x) < objective(np.zeros(3)) else np.zeros(3)
        score, lat, lon, elevation = evaluate(parameters)
        if not np.isfinite(score["score"]):
            continue
        profiles.append(dict(score, lat=lat, lon=lon, elev_m=elevation,
            recording_start_time_s=float(start + parameters[2]), altitude_offset_m=float(offset),
            boundary_limited=bool(np.any(np.abs(parameters) >= np.array([radius_m, radius_m, clock_radius_s]) * 0.98)),
            optimizer_success=bool(result.success)))
    nominal = next((p for p in profiles if p["altitude_offset_m"] == 0), None)
    if nominal is None:
        raise ValueError("No complete trajectory support for local refinement")
    center = ecef(nominal["lat"], nominal["lon"], 0)
    radius = max(float(np.linalg.norm(ecef(p["lat"], p["lon"], 0) - center)) for p in profiles)
    return dict(candidate, **{k: v for k, v in nominal.items() if k != "altitude_offset_m"},
                x=float(forward.transform(nominal["lon"], nominal["lat"])[0]),
                y=float(forward.transform(nominal["lon"], nominal["lat"])[1]),
                sensitivity={"radius_m": radius, "kind": "sensitivity",
                    "method": "profiled_relative_altitude_offsets",
                    "profiles": profiles, "boundary_limited": any(p["boundary_limited"] for p in profiles),
                    "complete": len(profiles) == len(altitude_offsets_m)})
