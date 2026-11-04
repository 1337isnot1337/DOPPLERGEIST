"""Adapt measured coherent traces without aircraft-type or geometry rejection.

Experimental audio proposals only. Straight-pass fit quality does not identify
an aircraft; the historical-track matcher and decision stage remain necessary.
"""
import numpy as np

from .contracts import validate_event
from .discovery import _HARMONIC_RATIOS, _merge_duplicates, _overlap


def events_from_coherent_traces(traces):
    """Use the reference detector's 40-point/1% quality gate, excluding kind.

    Rows contain ``proposal`` and its actual inlier ``ridge_points``. No fitted
    curve samples, speed/range priors, coordinates or flight IDs are consumed.
    """
    paths = []
    for row in traces:
        proposal, ridge = row["proposal"], row["ridge_points"]
        if not proposal["refined"] or len(ridge) < 40:
            continue
        rms, frequency = float(proposal["rms"]), float(proposal["f_main"])
        if not np.isfinite([rms, frequency]).all() or rms < 0 or frequency <= 0:
            raise ValueError("Coherent fit residual/frequency must be finite and physical")
        if rms / frequency > 0.010:
            continue
        points = np.array([[p["time_s"], p["frequency_hz"], p.get("weight", 1.)] for p in ridge])
        if (not np.isfinite(points).all() or np.any(np.diff(points[:, 0]) <= 0)
                or np.any(points[:, 1] <= 0) or np.any(points[:, 2] < 0)):
            raise ValueError("Coherent traces require ordered finite measured ridge samples")
        paths.append(points)

    # Reference traces have a 0.25 s hop. Use elapsed overlap rather than a
    # frame count tied to the ordinary discovery backend's 0.5 s hop.
    groups = []
    for path in sorted(_merge_duplicates(paths), key=lambda p: np.median(p[:, 1])):
        for group in groups:
            shared = _overlap(group[0], path)
            if shared is None:
                continue
            t, base, frequency = shared
            if np.ptp(t) < .6 * min(np.ptp(group[0][:, 0]), np.ptp(path[:, 0])):
                continue
            ratio = frequency / base
            harmonic = min(_HARMONIC_RATIOS, key=lambda h: abs(h - np.median(ratio)))
            if np.quantile(np.abs(ratio - harmonic) / harmonic, .9) < .008:
                group.append(path)
                break
        else:
            groups.append([path])

    events = []
    for i, group in enumerate(sorted(groups, key=lambda g: g[0][0, 0]), 1):
        for j, points in enumerate(group, 1):
            t, f, weight = points.T
            events.append(validate_event({
                "event_id": f"coherent-{i:04d}-{j:02d}",
                "harmonic_group_id": f"coherent-group-{i:04d}",
                "start_s": float(t[0]), "end_s": float(t[-1]),
                "band_hz": [float(max(f.min() - 1., 1e-6)), float(f.max() + 1.)],
                "ridge": [{"time_s": float(a), "frequency_hz": float(b), "weight": float(c)}
                          for a, b, c in points],
                "quality": {"frequency_resolution_hz": 1., "frequency_uncertainty_hz": 1.},
            }))
    return events
