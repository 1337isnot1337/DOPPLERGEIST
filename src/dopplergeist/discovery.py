"""Blind whole-recording moving-tone proposals, with harmonic deduplication.

Only decoded audio is read. Proposals are acoustic evidence, not proof of an
aircraft identity. No straight-pass speed/slant fit is required for acceptance.
"""
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

import numpy as np
from scipy import ndimage, optimize, signal

from .audio import Spectrum
from .contracts import validate_event

_HARMONIC_RATIOS = sorted({a / b for a in range(2, 9) for b in range(1, a) if a / b >= 1.2})
_NORMALIZATION_FUNCTIONS = (np.median, np.abs, np.maximum, np.clip, np.isfinite)


@dataclass(frozen=True)
class DiscoverySettings:
    chunk_s: float = 120.0
    overlap_s: float = 60.0
    min_frequency_hz: float = 40.0
    max_frequency_hz: float = 1600.0
    window_s: float = 2.0
    hop_s: float = 0.5
    min_contrast: float = 2.5
    min_duration_s: float = 12.0
    min_support: float = 0.65
    min_drop_hz: float = 4.0
    min_fractional_drop: float = 0.03
    max_gap_s: float = 2.0
    max_fragment_gap_s: float = 20.0
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
    contiguous_columns = (
        type(whitened) is np.ndarray and whitened.dtype == np.float32
        and whitened.ndim == 2 and whitened.size > 0 and whitened.flags.c_contiguous
        and all(current is original for current, original in zip(
            (np.median, np.abs, np.maximum, np.clip, np.isfinite), _NORMALIZATION_FUNCTIONS))
        and np.isfinite(whitened).all()
    )
    axis = 0
    if contiguous_columns:
        # Keep each frequency column contiguous for both partition reductions.
        whitened = whitened.T.copy(order="C")
        axis = 1
    center = np.median(whitened, axis=axis, keepdims=True)
    scale = 1.4826 * np.median(np.abs(whitened - center), axis=axis, keepdims=True)
    contrast = np.clip((whitened - center) / np.maximum(scale, 1.0), -4, 12)
    if contiguous_columns:
        contrast = contrast.T.copy(order="C")
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
                tail = path[-8:]
                if len(tail) >= 3:
                    slopes.append(float(median(
                        (right[1] - left[1]) / (right[0] - left[0])
                        for left, right in zip(tail, tail[1:])
                    )))
                else:
                    slopes.append(0.0)
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
    supported = np.ones(len(t), dtype=bool)
    for path in (a, b):
        following = np.clip(np.searchsorted(path[:, 0], t), 0, len(path) - 1)
        previous = np.maximum(0, following - 1)
        supported &= np.minimum(np.abs(t - path[following, 0]), np.abs(t - path[previous, 0])) <= 1.0
    t = t[supported]
    if len(t) < 3:
        return None
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


def _stitch_fragments(paths, settings, diagnostics=None):
    """Join only reciprocal-unique, locally compatible tonal continuations.

    Missing samples remain missing. A stitch is an acoustic hypothesis, not a
    flight identity or an independent event. Competing continuations stay split.
    """
    paths = sorted(paths, key=lambda path: path[0, 0])
    incoming = [[] for _ in paths]
    outgoing = [[] for _ in paths]
    for i, left in enumerate(paths):
        tail = left[left[:, 0] >= left[-1, 0] - 6]
        rate_left = -np.polyfit(tail[:, 0] - tail[0, 0], tail[:, 1], 1)[0]
        for j in range(i + 1, len(paths)):
            right = paths[j]
            gap = right[0, 0] - left[-1, 0]
            if gap <= 0 or gap > settings.max_fragment_gap_s:
                continue
            if gap / (right[-1, 0] - left[0, 0]) > 0.35:
                continue
            head = right[right[:, 0] <= right[0, 0] + 6]
            rate_right = -np.polyfit(head[:, 0] - head[0, 0], head[:, 1], 1)[0]
            drop = left[-1, 1] - right[0, 1]
            rate = drop / gap
            tolerance = max(2 / settings.window_s, 0.015 * left[-1, 1])
            if min(rate_left, rate_right) <= 0.05 or drop < -tolerance or drop > left[-1, 1] * 0.3:
                continue
            if not 0.4 * min(rate_left, rate_right) - tolerance / gap <= rate <= 2.5 * max(rate_left, rate_right) + tolerance / gap:
                continue
            outgoing[i].append(j)
            incoming[j].append(i)
    following = {i: targets[0] for i, targets in enumerate(outgoing)
                 if len(targets) == 1 and len(incoming[targets[0]]) == 1}
    if diagnostics is not None:
        for i, targets in enumerate(outgoing):
            for j in targets:
                accepted = following.get(i) == j
                diagnostics.append({"from_start_s": float(paths[i][0, 0]), "from_end_s": float(paths[i][-1, 0]),
                    "to_start_s": float(paths[j][0, 0]), "to_end_s": float(paths[j][-1, 0]),
                    "gap_s": float(paths[j][0, 0] - paths[i][-1, 0]), "accepted": accepted,
                    "reason": "reciprocal_unique_continuation" if accepted else "ambiguous_continuation"})
    consumed, result = set(), []
    for first in range(len(paths)):
        if first in consumed:
            continue
        chain, current = [paths[first]], first
        while current in following:
            current = following[current]
            chain.append(paths[current])
            consumed.add(current)
        result.append(np.concatenate(chain))
    return result


def _discover_baseline_events(recording, *, output_dir=None, settings=None, plot_summary=True, plot_event_details=False):
    """Return shared DetectedEvent dictionaries from a disk-backed recording.

    Fixed defaults scan 40–1600 Hz in overlapping chunks; no event hints, flight
    data or truth paths are accepted. Each measured ridge gets a record; a
    shared harmonic_group_id makes those records one independent proposal.
    Optional diagnostics retain all measured harmonic ridges and chunk counts.
    Per-event spectrograms are expensive and are rendered only when requested.
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
    fragment_links = []
    paths = _stitch_fragments(paths, settings, fragment_links)
    groups = _harmonic_groups(paths)
    events, event_groups = [], []
    for index, group in enumerate(groups):
        orders = {1.0}
        for harmonic in group[1:]:
            _, base_f, harmonic_f = _overlap(group[0], harmonic)
            ratio = np.median(harmonic_f / base_f)
            orders.add(min(_HARMONIC_RATIOS, key=lambda value: abs(value - ratio)))
        for harmonic_index, points in enumerate(group):
            t, f, weight = points.T
            margin = 2 / settings.window_s
            smooth = ndimage.median_filter(f, size=5, mode="nearest")
            frequency_scale = float(max(1 / settings.window_s, 1.4826 * np.median(np.abs(f - smooth))))
            event_id = f"event-{index + 1:04d}"
            if harmonic_index:
                event_id += f"-harmonic-{harmonic_index + 1}"
            event = {"event_id": event_id, "harmonic_group_id": f"harmonics-{index + 1:04d}",
                 "start_s": max(0.0, float(t[0] - settings.window_s / 2)),
                 "end_s": min(recording.metadata["duration_s"], float(t[-1] + settings.window_s / 2)),
                 "band_hz": [max(0.01, float(f.min() - margin)), float(f.max() + margin)],
                 "ridge": [{"time_s": float(a), "frequency_hz": float(b), "weight": float(c)} for a, b, c in points],
                 "quality": {"median_contrast": float(np.median(weight)), "harmonic_count": float(len(orders)),
                             "support_fraction": min(1.0, len(t) / (np.ptp(t) / settings.hop_s + 1)),
                             "frequency_resolution_hz": 1 / settings.window_s,
                             "time_uncertainty_s": settings.window_s / 2,
                             "frequency_uncertainty_hz": frequency_scale,
                             "frequency_sigma_hz": frequency_scale,
                             "fragment_count": float(1 + np.sum(np.diff(t) > settings.max_gap_s)),
                             "max_observed_gap_s": float(np.max(np.diff(t))),
                             "frequency_drop_hz": float(np.median(f[:max(3, len(f) // 6)]) - np.median(f[-max(3, len(f) // 6):]))}}
            events.append(validate_event(event))
            event_groups.append(group)
    if output:
        diagnostics = {"source_sha256": recording.metadata["source_sha256"], "settings": asdict(settings),
                       "events": events, "chunks": chunks, "ridge_count": len(paths),
                       "fragment_links": fragment_links,
                       "harmonic_ridges": [[points.tolist() for points in group] for group in groups],
                       "scope": "automatic acoustic moving-tone proposals; aircraft identity unconfirmed"}
        (output / "discovery.json").write_text(json.dumps(diagnostics, indent=2, allow_nan=False) + "\n")
        if plot_summary:
            _plot_groups(groups, output / "discovery.png", recording.metadata["duration_s"], settings.max_gap_s)
        for event, group in zip(events, event_groups):
            points = np.array([[p["time_s"], p["frequency_hz"], p["weight"]] for p in event["ridge"]])
            np.savetxt(output / f"{event['event_id']}.csv", points, delimiter=",",
                       header="time_s,frequency_hz,weight", comments="")
            if plot_event_details:
                _plot_event(recording, group, event, settings, output / f"{event['event_id']}.png")
    return events


def discover_events(recording, *, output_dir=None, settings=None, plot_summary=True, plot_event_details=False,
                    event_audio=False, progress_callback=None):
    """Discover acoustic proposals; ``progress_callback(phase=..., **counts)`` reports activity only."""
    from .advanced_discovery import discover
    from .intake import intake_recording

    settings = settings or DiscoverySettings()
    if settings != DiscoverySettings():
        raise ValueError("Custom discovery settings are not supported")
    if recording.metadata["sample_rate_hz"] != 4000 or recording.source_path is None:
        raise ValueError("Discovery requires a 4000 Hz intake recording with its original audio source")

    def run(output):
        output.mkdir(parents=True, exist_ok=True)
        if (output / "discovery.json").exists():
            raise FileExistsError("Discovery output exists; use a new output directory")
        def report(phase, **fields):
            if progress_callback:
                progress_callback(phase=phase, **fields)

        auxiliary = intake_recording(
            recording.source_path, output / "intake_high", sample_rate_hz=24000,
            progress_callback=(lambda **fields: report("decoding_high_rate", **fields)) if progress_callback else None)
        if auxiliary.metadata["source_sha256"] != recording.metadata["source_sha256"]:
            raise ValueError("Audio source changed between intake and discovery")
        report("tracking_ridges")
        result = discover(recording, output, "ridge_dp_accel_broad_final_v25", aux_recording=auxiliary)
        report("grouping_proposals")
        tracks = {event["event_id"]: event for event in result["raw_events"]}
        tracks.update({event["event_id"]: event for event in result["verified_tracks"]})
        events, groups = [], []
        for proposal in result["events"]:
            group = []
            for event_id in proposal["raw_event_ids"]:
                track = tracks[event_id]
                event = {key: track[key] for key in ("event_id", "start_s", "end_s", "band_hz", "ridge", "quality") if key in track}
                event["harmonic_group_id"] = proposal["event_id"]
                frequencies = [point["frequency_hz"] for point in event["ridge"]]
                event["band_hz"] = [min(event["band_hz"][0], min(frequencies)), max(event["band_hz"][1], max(frequencies))]
                events.append(validate_event(event))
                group.append(np.array([[p["time_s"], p["frequency_hz"], p["weight"]] for p in event["ridge"]]))
            groups.append(group)
        if output_dir is not None:
            baseline_diagnostics = json.loads((output / "baseline-tracks/discovery.json").read_text())
            (output / "discovery.json").write_text(json.dumps({"source_sha256": recording.metadata["source_sha256"],
                "settings": asdict(settings), "sequence_settings": result["sequence_settings"],
                "events": events, "proposals": result["events"], "chunks": baseline_diagnostics["chunks"],
                "fragment_links": baseline_diagnostics["fragment_links"],
                "harmonic_ridges": [[points.tolist() for points in group] for group in groups],
                "scope": "automatic acoustic proposals; aircraft identity unconfirmed"}, indent=2, allow_nan=False) + "\n")
            report("writing_plots")
            if plot_summary:
                _plot_groups(groups, output / "discovery.png", recording.metadata["duration_s"], settings.max_gap_s)
            _write_event_media(auxiliary, events, output, settings,
                               plot_event_details=plot_event_details, event_audio=event_audio)
        return events

    if output_dir is not None:
        return run(Path(output_dir))
    with TemporaryDirectory(prefix="doppler-discovery-") as temporary:
        return run(Path(temporary))


_EVENT_AUDIO_PADDING_S = 1.5
_EVENT_AUDIO_MAX_S = 60.0


def _event_clip_bounds(event, duration_s):
    """Return an audio-relative interval for a bounded playback excerpt."""
    duration_s = float(duration_s)
    wanted_start = max(0.0, event["start_s"] - _EVENT_AUDIO_PADDING_S)
    wanted_end = min(duration_s, event["end_s"] + _EVENT_AUDIO_PADDING_S)
    wanted_length = wanted_end - wanted_start
    length = min(_EVENT_AUDIO_MAX_S, duration_s, wanted_length)
    center = (wanted_start + wanted_end) / 2
    start = max(0.0, min(center - length / 2, duration_s - length))
    end = start + length
    truncated = wanted_length > length + 1e-9
    return start, end, truncated


def _band_limited(data, sample_rate_hz, band_hz):
    """Isolate an event's measured band for listening only, not for analysis."""
    if len(data) < 64:
        return None
    nyquist = sample_rate_hz / 2
    low, high = float(band_hz[0]), float(band_hz[1])
    center = max(1.0, math.sqrt(max(low, 1.0) * max(high, 1.0)))
    width = max(high - low, 0.25 * center, 20.0)
    low = max(20.0, low - 0.1 * width)
    high = min(nyquist * 0.98, high + 0.1 * width)
    if not 0 < low < high < nyquist or high - low < 10.0:
        return None
    sos = signal.butter(3, [low, high], btype="bandpass", fs=sample_rate_hz, output="sos")
    return np.asarray(signal.sosfiltfilt(sos, data), dtype=np.float32)


def _write_event_audio(recording, event, path, *, band_limited=False):
    """Write one bounded recording excerpt, optionally band-limited."""
    sample_rate_hz = int(recording.metadata["sample_rate_hz"])
    start, end, truncated = _event_clip_bounds(event, recording.metadata["duration_s"])
    samples = np.memmap(recording.samples_path, dtype="<f4", mode="r")
    first = max(0, int(round(start * sample_rate_hz)))
    last = min(len(samples), int(round(end * sample_rate_hz)))
    data = np.asarray(samples[first:last], dtype=np.float32).copy()
    if len(data) == 0:
        raise ValueError("Event excerpt is empty")
    if band_limited:
        filtered = _band_limited(data, sample_rate_hz, event["band_hz"])
        if filtered is None:
            return None
        data = filtered
    fade = min(len(data), max(1, int(round(0.01 * sample_rate_hz))))
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    data[:fade] *= ramp
    data[-fade:] *= ramp[::-1]
    peak = float(np.max(np.abs(data)))
    if not math.isfinite(peak):
        raise ValueError("Event excerpt contains a non-finite sample")
    if band_limited and peak > 0:
        data = data * (0.95 / peak)
    elif peak > 1.0:
        data = data / peak
    from soundfile import write
    write(path, data, sample_rate_hz, subtype="PCM_16")
    return {"path": path.name, "start_s": first / sample_rate_hz,
            "end_s": last / sample_rate_hz, "truncated": truncated}


def _write_event_media(recording, events, output, settings, *, plot_event_details, event_audio):
    """Write per-event plot, ridge and audio evidence without failing discovery."""
    media = {"schema_version": 1, "version": 2,
             "clip": {"padding_s": _EVENT_AUDIO_PADDING_S, "max_duration_s": _EVENT_AUDIO_MAX_S},
             "scope": "illustrative excerpts from the preserved recording; band-limited audio is not used for detection or scoring",
             "events": {}}
    for event in events:
        event_id = event["event_id"]
        entry = {}
        errors = []
        points = np.array([[point["time_s"], point["frequency_hz"], point.get("weight", 1.0)]
                           for point in event["ridge"]])
        try:
            np.savetxt(output / f"{event_id}.csv", points, delimiter=",",
                       header="time_s,frequency_hz,weight", comments="")
            entry["ridge_csv"] = f"{event_id}.csv"
        except (OSError, ValueError) as exc:
            errors.append(f"ridge_csv: {type(exc).__name__}: {exc}")
        if plot_event_details:
            try:
                entry["plot"] = _plot_event(recording, [points], event, settings,
                                            output / f"{event_id}.png")
                entry["image"] = f"{event_id}.png"
            except Exception as exc:  # A diagnostic render must not fail analysis.
                errors.append(f"image: {type(exc).__name__}: {exc}")
        if event_audio:
            try:
                raw = _write_event_audio(recording, event, output / f"{event_id}-audio.wav")
                audio = {"raw": raw["path"], "start_s": raw["start_s"],
                         "end_s": raw["end_s"], "truncated": raw["truncated"],
                         "sample_rate_hz": recording.metadata["sample_rate_hz"]}
                band = _write_event_audio(recording, event, output / f"{event_id}-band.wav",
                                          band_limited=True)
                if band:
                    audio["band_limited"] = band["path"]
                entry["audio"] = audio
            except Exception as exc:
                errors.append(f"audio: {type(exc).__name__}: {exc}")
        if errors:
            entry["errors"] = errors
        media["events"][event_id] = entry
    (output / "event-media.json").write_text(
        json.dumps(media, indent=2, allow_nan=False) + "\n")
    return media


def _plot_groups(groups, path, duration, max_gap_s=2.0):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
    for index, group in enumerate(groups):
        for harmonic, points in enumerate(group):
            segments = np.split(points, np.flatnonzero(np.diff(points[:, 0]) > max_gap_s) + 1)
            for segment_index, segment in enumerate(segments):
                ax.plot(segment[:, 0], segment[:, 1], color=f"C{index % 10}", lw=0.8, alpha=0.8,
                        label=f"Event {index + 1}" if harmonic == 0 and segment_index == 0 else None)
    ax.set(xlim=(0, duration), xlabel="Recording-relative time (s)", ylabel="Measured frequency (Hz)",
           title="Automatic whole-recording moving-tone proposals (harmonics grouped)")
    if groups:
        ax.legend(loc="upper right", fontsize="small", ncols=2)
    fig.savefig(path, dpi=130)
    plt.close(fig)


_EVENT_PLOT_MAX_S = 80.0


def _plot_event(recording, group, event, settings, path):
    from matplotlib import pyplot as plt
    # Long merged ridges remain complete in JSON/CSV; the image is bounded.
    span = max(0.0, event["end_s"] - event["start_s"])
    margin = max(3.0, min(10.0, span * 0.25))
    first = max(0.0, event["start_s"] - margin)
    last = min(recording.metadata["duration_s"], event["end_s"] + margin)
    if last - first > _EVENT_PLOT_MAX_S:
        center = (first + last) / 2
        first = max(0.0, center - _EVENT_PLOT_MAX_S / 2)
        last = min(recording.metadata["duration_s"], first + _EVENT_PLOT_MAX_S)
    if last - first < 1.0:
        last = min(recording.metadata["duration_s"], first + 1.0)
    quality = event.get("quality", {})
    window_s = settings.window_s
    hop_s = min(settings.hop_s, 0.25)
    try:
        candidate_window = float(quality.get("window_s", window_s))
        candidate_hop = float(quality.get("hop_s", settings.hop_s))
        if 0 < candidate_window < settings.chunk_s and 0 < candidate_hop <= candidate_window:
            window_s = candidate_window
            hop_s = min(candidate_hop, 0.25)
    except (TypeError, ValueError):
        pass
    plot_settings = replace(settings, max_frequency_hz=8000., window_s=window_s, hop_s=hop_s)
    sr = recording.metadata["sample_rate_hz"]
    data = np.memmap(recording.samples_path, dtype="<f4", mode="r")
    spec = _spectrum(np.array(data[round(first * sr):round(last * sr)]), sr, first, plot_settings)
    if spec is None:
        raise ValueError("The event crop is shorter than one display window")
    low = min(points[:, 1].min() for points in group)
    high = max(points[:, 1].max() for points in group)
    limits = (max(plot_settings.min_frequency_hz, low * 0.9), high * 1.1)
    # Only visible cells can affect the image. Keep an extra frequency bin on
    # each side so pcolormesh reconstructs the same boundary-cell coordinates.
    # Whitening still uses the full spectrum and all measured ridges are kept.
    lower = max(0, np.searchsorted(spec.frequency, limits[0]) - 1)
    upper = min(len(spec.frequency), np.searchsorted(spec.frequency, limits[1], side="right") + 1)
    visible = slice(lower, upper)
    fig, ax = plt.subplots(figsize=(12, 4.5), layout="constrained")
    ax.pcolormesh(spec.time, spec.frequency[visible], spec.contrast[visible], shading="auto", cmap="magma", vmin=0, vmax=6,
                  rasterized=True)
    for points in group:
        for segment in np.split(points, np.flatnonzero(np.diff(points[:, 0]) > plot_settings.max_gap_s) + 1):
            ax.plot(segment[:, 0], segment[:, 1], color="cyan", lw=1.0)
    ax.set(xlim=(first, last), ylim=limits,
           xlabel="Recording-relative time (s)", ylabel="Frequency (Hz)",
           title=f"{event['event_id']}: measured ridges; acoustic proposal, identity unconfirmed")
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return {"start_s": first, "end_s": last, "window_s": window_s, "hop_s": hop_s,
            "sample_rate_hz": sr}
