"""Measured ridge reuse, without inferring a shared physical source."""
import numpy as np


def aligned_ridge_observations(first, second):
    """Use the existing confidence guard's alignment and overlap requirements."""
    if first.get("harmonic_group_id", first["event_id"]) == second.get("harmonic_group_id", second["event_id"]):
        return None
    if (not first["ridge"] or not second["ridge"]
            or first["ridge"][-1]["time_s"] < second["ridge"][0]["time_s"]
            or second["ridge"][-1]["time_s"] < first["ridge"][0]["time_s"]):
        return None
    a = {point["time_s"]: point["frequency_hz"] for point in first["ridge"]}
    b = {point["time_s"]: point["frequency_hz"] for point in second["ridge"]}
    times = sorted(a.keys() & b.keys())
    if len(times) < 10:
        return None
    span = min(first["ridge"][-1]["time_s"] - first["ridge"][0]["time_s"],
               second["ridge"][-1]["time_s"] - second["ridge"][0]["time_s"])
    if span <= 0 or times[-1] - times[0] < 0.6 * span:
        return None
    x, y = (np.array([ridge[t] for t in times], dtype=float) for ridge in (a, b))
    return times, x, y


def reused_ridge_observations(first, second, *, aligned=None):
    """Identify five reused aligned peaks; retain both diverging path hypotheses."""
    aligned = aligned_ridge_observations(first, second) if aligned is None else aligned
    if aligned is None:
        return None
    times, x, y = aligned
    shared = x == y
    starts = np.flatnonzero(np.convolve(shared, np.ones(5, dtype=int), mode="valid") == 5)
    if not len(starts):
        return None
    start = int(starts[0])
    return {"event_ids": [first["event_id"], second["event_id"]],
            "ambiguity": "reused_ridge_observations", "harmonic_ratio": 1.0,
            "aligned_samples": len(times), "shared_ridge_samples": int(shared.sum()),
            "shared_run_start_s": times[start], "shared_run_end_s": times[start + 4]}


def selected_ridge_conflicts(events):
    """Return prepared conflicts only when both affected groups are selected."""
    selected = {event.get("harmonic_group_id") or event.get("event_id") for event in events}
    conflicts, seen = [], set()
    for event in events:
        for conflict in event.get("shared_ridge_observations", ()):
            groups = tuple(conflict["group_ids"])
            if groups not in seen and set(groups).issubset(selected):
                conflicts.append(conflict)
                seen.add(groups)
    return conflicts
