"""Blind whole-recording moving-tone proposals, with harmonic deduplication.

Only decoded audio is read. Proposals are acoustic evidence, not proof of an
aircraft identity. No straight-pass speed/slant fit is required for acceptance.
"""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
from scipy import ndimage, optimize, signal

from .audio import Spectrum
from .contracts import validate_event

_HARMONIC_RATIOS = sorted({a / b for a in range(2, 9) for b in range(1, a) if a / b >= 1.2})


@dataclass(frozen=True)
class DiscoverySettings:
    chunk_s: float = 120.0
    overlap_s: float = 60.0
    min_frequency_hz: float = 40.0
    max_frequency_hz: float = 1600.0
    window_s: float = 2.0
    hop_s: float = 0.5
    min_contrast: float = 3.0
    min_duration_s: float = 12.0
    min_support: float = 0.65
    min_drop_hz: float = 4.0
    min_fractional_drop: float = 0.03
    max_gap_s: float = 2.0
    max_peaks_per_frame: int = 60

    def __post_init__(self):
        values = asdict(self)
        if any(not np.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("Discovery settings must be finite and positive")
        if self.overlap_s >= self.chunk_s or self.overlap_s < self.min_duration_s + self.window_s:
            raise ValueError("Overlap must cover an event acceptance window and be shorter than a chunk")
        if not self.hop_s <= self.window_s < self.chunk_s or self.min_support > 1:
            raise ValueError("Invalid spectral window/hop/support")
        if self.min_frequency_hz >= self.max_frequency_hz or type(self.max_peaks_per_frame) is not int:
            raise ValueError("Invalid frequency range or peak limit")


def _spectrum(data, sr, start, settings):
    n, hop = round(sr * settings.window_s), round(sr * settings.hop_s)
    if len(data) < n:
        return None
    f, t, power = signal.spectrogram(data, fs=sr, window="hann", nperseg=n,
                                    noverlap=n - hop, nfft=n, scaling="density")
    keep = (f >= settings.min_frequency_hz) & (f <= min(settings.max_frequency_hz, sr * 0.48))
    f, power = f[keep], power[keep]
    db = 10 * np.log10(power + np.finfo(np.float32).tiny)
    whitened = db - np.median(db, axis=1, keepdims=True)
    center = np.median(whitened, axis=0, keepdims=True)
    scale = 1.4826 * np.median(np.abs(whitened - center), axis=0, keepdims=True)
    contrast = np.clip((whitened - center) / np.maximum(scale, 1.0), -4, 12)
    return Spectrum(t + start, f, db, contrast)


def _paths(spec, settings):
    """Link local spectral maxima with bounded motion and short missing spans."""
    active, completed = [], []
    for column, time in enumerate(spec.time):
        peaks, info = signal.find_peaks(spec.contrast[:, column], height=settings.min_contrast,
                                       prominence=1.5, distance=2)
        order = np.argsort(info["peak_heights"])[-settings.max_peaks_per_frame:]
        peaks = peaks[order]
        frequencies = spec.frequency[peaks]
        weights = spec.contrast[peaks, column]
        # Sub-bin interpolation measures a local maximum without zero-padding.
        if len(peaks):
            a, b, c = (spec.db[peaks + offset, column] for offset in (-1, 0, 1))
            denominator = a - 2 * b + c
            offset = np.divide(0.5 * (a - c), denominator, out=np.zeros_like(a), where=np.abs(denominator) > 1e-9)
            frequencies = frequencies + np.clip(offset, -0.5, 0.5) * np.diff(spec.frequency[:2])[0]
        live = []
        for path in active:
            if time - path[-1][0] <= settings.max_gap_s:
                live.append(path)
            else:
                completed.append(path)
        active = live
        used = set()
        if active and len(peaks):
            last = np.array([path[-1] for path in active])
            dt = time - last[:, 0]
            delta = frequencies[None, :] - last[:, 1, None]
            speed = delta / dt[:, None]
            slopes = []
            for path in active:
                tail = np.asarray(path[-8:])
                slopes.append(float(np.median(np.diff(tail[:, 1]) / np.diff(tail[:, 0]))) if len(tail) >= 3 else 0.0)
            allowed = (speed >= -np.maximum(8, last[:, 1, None] * 0.08)) & (speed <= np.maximum(1.0, last[:, 1, None] * 0.008))
            predicted_delta = np.asarray(slopes)[:, None] * dt[:, None]
            costs = np.abs(delta - predicted_delta) / np.maximum(1.0, last[:, 1, None] * 0.01)
            costs = np.where(allowed, costs, 1e6)
            rows, cols = optimize.linear_sum_assignment(costs)
            for row, col in zip(rows, cols):
                if costs[row, col] < 1e6:
                    active[row].append((float(time), float(frequencies[col]), float(weights[col])))
                    used.add(col)
        active.extend([(float(time), float(frequency), float(weight))]
                      for j, (frequency, weight) in enumerate(zip(frequencies, weights)) if j not in used)
    return completed + active


def _usable(path, settings):
    points = np.asarray(path)
    t, f, weight = points.T
    duration = t[-1] - t[0]
    if duration < settings.min_duration_s:
        return False
    support = len(t) / (duration / settings.hop_s + 1)
    edge = max(3, len(t) // 6)
    drop = np.median(f[:edge]) - np.median(f[-edge:])
    if support < settings.min_support:
        return False
    if drop < max(settings.min_drop_hz, np.median(f) * settings.min_fractional_drop):
        return False
    # Reject stationary tracks and random wandering. Local frequency jitter is
    # permitted; no compulsory straight-flight geometry or speed bound is used.
    smooth = ndimage.median_filter(f, size=5, mode="nearest")
    monotone = np.mean(np.diff(smooth) <= 0.5)
    slopes = -np.diff(smooth) / np.diff(t)
    moving_fraction = np.mean(slopes > max(0.05, drop / duration * 0.2))
    # A path can otherwise jump between two stationary tones and manufacture
    # an apparent Doppler drop. Require distributed, resolved frequency motion.
    jump = np.max(np.abs(np.diff(smooth)))
    return bool(monotone >= 0.75 and moving_fraction >= 0.35
                and jump <= max(2 / settings.window_s, drop * 0.25)
                and np.median(np.abs(f - smooth)) <= max(1, np.median(f) * 0.01))


def _overlap(a, b):
    first, last = max(a[0, 0], b[0, 0]), min(a[-1, 0], b[-1, 0])
    if last <= first:
        return None
    t = np.arange(first, last + 0.001, 0.5)
    return t, np.interp(t, a[:, 0], a[:, 1]), np.interp(t, b[:, 0], b[:, 1])


def _merge_duplicates(paths):
    merged = []
    for path in sorted(paths, key=lambda p: p[0][0]):
        current = np.asarray(path)
        for i, previous in enumerate(merged):
            shared = _overlap(current, previous)
            if shared is None:
                continue
            t, f, g = shared
            if len(t) >= 8 and np.mean(np.abs(f - g) <= max(1.0, np.median(f) * 0.006)) >= 0.85:
                points = np.concatenate((current, previous))
                # A time bin observed in both chunks retains its strongest peak.
                points = points[np.lexsort((-points[:, 2], points[:, 0]))]
                _, unique = np.unique(points[:, 0], return_index=True)
                merged[i] = points[np.sort(unique)]
                break
        else:
            merged.append(current)
    return merged


def _harmonic_groups(paths):
    groups = []
    for path in sorted(paths, key=lambda p: np.median(p[:, 1])):
        for group in groups:
            base = group[0]
            shared = _overlap(base, path)
            if shared is None:
                continue
            t, f, g = shared
            if len(t) * 0.5 < 0.6 * min(np.ptp(base[:, 0]), np.ptp(path[:, 0])):
                continue
            ratio = g / f
            # Rational ratios also cover a missing fundamental (e.g. 2f, 3f).
            harmonic = min(_HARMONIC_RATIOS, key=lambda value: abs(value - np.median(ratio)))
            if np.quantile(np.abs(ratio - harmonic) / harmonic, 0.9) < 0.008:
                group.append(path)
                break
        else:
            groups.append([path])
    return sorted(groups, key=lambda group: group[0][0, 0])


def discover_events(recording, *, output_dir=None, settings=None):
    """Return shared DetectedEvent dictionaries from a disk-backed recording.

    Fixed defaults scan 40–1600 Hz in overlapping chunks; no event hints, flight
    data or truth paths are accepted. Harmonics become one independent event.
    Optional diagnostics retain all measured harmonic ridges and chunk counts.
    """
    settings = settings or DiscoverySettings()
    sr = recording.metadata["sample_rate_hz"]
    if settings.min_frequency_hz >= min(settings.max_frequency_hz, sr * 0.48):
        raise ValueError("Frequency range is above the decoded Nyquist limit")
    paths, chunks = [], []
    output = Path(output_dir) if output_dir is not None else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
        if (output / "discovery.json").exists():
            raise FileExistsError("Discovery output exists; use a new output directory")
    for start, data in recording.iter_chunks(settings.chunk_s, settings.overlap_s):
        spec = _spectrum(data, sr, start, settings)
        if spec is None:
            chunks.append({"start_s": start, "duration_s": len(data) / sr, "usable_paths": 0})
            continue
        found = [path for path in _paths(spec, settings) if _usable(path, settings)]
        paths.extend(found)
        chunks.append({"start_s": start, "duration_s": len(data) / sr, "usable_paths": len(found)})
    paths = _merge_duplicates(paths)
    groups = _harmonic_groups(paths)
    events = []
    for index, group in enumerate(groups):
        points = group[0]
        t, f, weight = points.T
        orders = {1.0}
        for harmonic in group[1:]:
            _, base_f, harmonic_f = _overlap(points, harmonic)
            ratio = np.median(harmonic_f / base_f)
            orders.add(min(_HARMONIC_RATIOS, key=lambda value: abs(value - ratio)))
        margin = 2 / settings.window_s
        smooth = ndimage.median_filter(f, size=5, mode="nearest")
        event = {"event_id": f"event-{index + 1:04d}", "harmonic_group_id": f"harmonics-{index + 1:04d}",
                 "start_s": max(0.0, float(t[0] - settings.window_s / 2)),
                 "end_s": min(recording.metadata["duration_s"], float(t[-1] + settings.window_s / 2)),
                 "band_hz": [max(0.01, float(f.min() - margin)), float(f.max() + margin)],
                 "ridge": [{"time_s": float(a), "frequency_hz": float(b), "weight": float(c)} for a, b, c in points],
                 "quality": {"median_contrast": float(np.median(weight)), "harmonic_count": float(len(orders)),
                             "support_fraction": min(1.0, len(t) / (np.ptp(t) / settings.hop_s + 1)),
                             "frequency_resolution_hz": 1 / settings.window_s,
                             "time_uncertainty_s": settings.window_s / 2,
                             "frequency_uncertainty_hz": float(max(1 / settings.window_s, 1.4826 * np.median(np.abs(f - smooth)))),
                             "frequency_drop_hz": float(np.median(f[:max(3, len(f) // 6)]) - np.median(f[-max(3, len(f) // 6):]))}}
        events.append(validate_event(event))
    if output:
        diagnostics = {"source_sha256": recording.metadata["source_sha256"], "settings": asdict(settings),
                       "events": events, "chunks": chunks, "ridge_count": len(paths),
                       "harmonic_ridges": [[points.tolist() for points in group] for group in groups],
                       "scope": "automatic acoustic moving-tone proposals; aircraft identity unconfirmed"}
        (output / "discovery.json").write_text(json.dumps(diagnostics, indent=2, allow_nan=False) + "\n")
        _plot_groups(groups, output / "discovery.png", recording.metadata["duration_s"])
        for event, group in zip(events, groups):
            np.savetxt(output / f"{event['event_id']}.csv", group[0], delimiter=",",
                       header="time_s,frequency_hz,weight", comments="")
            _plot_event(recording, group, event, settings, output / f"{event['event_id']}.png")
    return events


def _plot_groups(groups, path, duration):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
    for index, group in enumerate(groups):
        for harmonic, points in enumerate(group):
            ax.plot(points[:, 0], points[:, 1], lw=0.8, alpha=0.8,
                    label=f"Event {index + 1}" if harmonic == 0 else None)
    ax.set(xlim=(0, duration), xlabel="Recording-relative time (s)", ylabel="Measured frequency (Hz)",
           title="Automatic whole-recording moving-tone proposals (harmonics grouped)")
    if groups:
        ax.legend(loc="upper right", fontsize="small", ncols=2)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _plot_event(recording, group, event, settings, path):
    from matplotlib import pyplot as plt
    # Long merged ridges remain complete in JSON/CSV; image memory is bounded.
    center = (event["start_s"] + event["end_s"]) / 2
    first = max(event["start_s"] - 3, center - settings.chunk_s / 2, 0)
    last = min(event["end_s"] + 3, first + settings.chunk_s, recording.metadata["duration_s"])
    sr = recording.metadata["sample_rate_hz"]
    data = np.memmap(recording.samples_path, dtype="<f4", mode="r")
    spec = _spectrum(np.array(data[round(first * sr):round(last * sr)]), sr, first, settings)
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    ax.pcolormesh(spec.time, spec.frequency, spec.contrast, shading="auto", cmap="magma", vmin=0, vmax=6,
                  rasterized=True)
    for points in group:
        ax.plot(points[:, 0], points[:, 1], color="cyan", lw=0.9)
    low = min(points[:, 1].min() for points in group)
    high = max(points[:, 1].max() for points in group)
    ax.set(xlim=(first, last), ylim=(max(settings.min_frequency_hz, low * 0.9), high * 1.1),
           xlabel="Recording-relative time (s)", ylabel="Frequency (Hz)",
           title=f"{event['event_id']}: measured ridges; acoustic proposal, identity unconfirmed")
    fig.savefig(path, dpi=130)
    plt.close(fig)
