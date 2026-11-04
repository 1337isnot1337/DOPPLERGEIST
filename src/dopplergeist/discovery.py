"""Blind whole-recording moving-tone proposals, with harmonic deduplication.

Only decoded audio is read. Proposals are acoustic evidence, not proof of an
aircraft identity. No straight-pass speed/slant fit is required for acceptance.
"""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from statistics import median
import hashlib
from importlib.metadata import version
import subprocess
import time
from collections import Counter

import numpy as np
from scipy import optimize, signal

from .audio import Spectrum
from .contracts import validate_event
from .episodes import (Associations, DiscoveryError, Ridge, aligned, deduplicate,
                       identifier, intervals, motion, reconcile, stitch)

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
    provisional_min_points: int = 4
    brief_min_observed_s: float = 3.0
    brief_min_contrast: float = 4.5
    max_candidates: int = 4096
    max_measurements: int = 500000
    max_associations: int = 200000
    max_diagnostic_traces: int = 100
    max_spectral_cells: int = 8000000
    max_episode_components: int = 32

    def __post_init__(self):
        values = asdict(self)
        if any(not np.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("Discovery settings must be finite and positive")
        for name in ("max_peaks_per_frame", "provisional_min_points", "max_candidates", "max_measurements",
                     "max_associations", "max_diagnostic_traces", "max_spectral_cells", "max_episode_components"):
            if type(values[name]) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.provisional_min_points < 4 or self.chunk_s > 180 or self.window_s > 8 or self.max_frequency_hz > 14400:
            raise ValueError("Require >=4 provisional points, chunk <=180 s, window <=8 s and upper frequency <=14400 Hz")
        if self.min_frequency_hz < 2 / self.window_s:
            raise ValueError("Lower frequency needs at least two cycles per spectral window")
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
    cells = (n // 2 + 1) * (1 + (len(data) - n) // hop)
    if cells > settings.max_spectral_cells:
        raise DiscoveryError("spectral_budget_exceeded", f"Spectrum needs {cells} cells; limit {settings.max_spectral_cells}")
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
                if len(tail) >= 2:
                    slopes.append(float(median(
                        (right[1] - left[1]) / (right[0] - left[0])
                        for left, right in zip(tail, tail[1:])
                    )))
                else:
                    slopes.append(0.0)
            allowed = np.abs(speed) <= np.maximum(8, last[:, 1, None] * 0.08)
            predicted_delta = np.asarray(slopes)[:, None] * dt[:, None]
            tolerance = 3 / settings.window_s + np.maximum(.5, np.abs(slopes)[:, None] * .5) * dt[:, None]
            newborn = np.array([len(path) == 1 for path in active])
            tolerance[newborn] = np.maximum(8, last[newborn, 1, None] * .08) * dt[newborn, None]
            costs = np.abs(delta - predicted_delta) / tolerance
            allowed &= costs <= 1
            costs = np.where(allowed, costs, 1e6)
            rows, cols = optimize.linear_sum_assignment(costs)
            for row, col in zip(rows, cols):
                if costs[row, col] < 1e6:
                    active[row].append((float(time), float(frequencies[col]), float(weights[col]), float(spec.db[peaks[col], column])))
                    used.add(col)
        active.extend([(float(time), float(frequency), float(weight), float(spec.db[peaks[j], column]))]
                      for j, (frequency, weight) in enumerate(zip(frequencies, weights)) if j not in used)
    return completed + active


def _usable(path, settings):
    metrics, rejected = motion(np.asarray(path), settings)
    return not rejected and metrics["observed_duration_s"] >= settings.min_duration_s and metrics["support_fraction"] >= settings.min_support


def _overlap(a, b):
    """Legacy fixed-grid alignment, retained for existing optional adapters."""
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
    """Legacy adapter compatibility; canonical discovery uses deduplicate()."""
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



def _stitch_fragments(paths, settings, diagnostics=None):
    work = Associations(settings)
    ridges = [Ridge(np.asarray(p), (identifier("raw:", np.asarray(p)),)) for p in paths]
    result = stitch(ridges, settings, work)
    if diagnostics is not None:
        diagnostics.extend(work.decisions)
    return [r.points for r in result]


def required_sample_rate(settings):
    """Bound decode cost while keeping a 10% Nyquist transition guard."""
    for rate in (4000, 8000, 16000, 32000):
        if settings.max_frequency_hz <= .45 * rate:
            return rate
    raise DiscoveryError("unsupported_frequency_coverage", "Requested upper frequency exceeds bounded decoder coverage")


def _coverage(recording, settings):
    sr = recording.metadata["sample_rate_hz"]
    decode = recording.diagnostics.get("decode", {})
    source_sr = decode.get("source_sample_rate_hz", sr)
    upper = .45 * min(sr, source_sr)
    if settings.max_frequency_hz > upper:
        raise DiscoveryError("unsupported_frequency_coverage",
                             f"Requested {settings.max_frequency_hz:g} Hz exceeds usable decoded/source coverage {upper:g} Hz; decode at >= {required_sample_rate(settings)} Hz and check source rate")
    if np.floor(settings.max_frequency_hz * settings.window_s) - np.ceil(settings.min_frequency_hz * settings.window_s) < 2:
        raise DiscoveryError("unsupported_frequency_coverage", "Frequency range requires at least three spectral bins for a measured peak")
    # Align frames and chunk boundaries to exactly representable sample hops.
    if any(abs(value * sr - round(value * sr)) > 1e-7 for value in (settings.window_s, settings.hop_s)):
        raise DiscoveryError("unsupported_time_grid", "Window and hop must be integer sample counts")
    step = settings.chunk_s - settings.overlap_s
    if abs(step / settings.hop_s - round(step / settings.hop_s)) > 1e-7:
        raise DiscoveryError("unsupported_time_grid", "Chunk step must be an integer number of spectral hops")
    if round(settings.hop_s * sr) < 1:
        raise DiscoveryError("unsupported_time_grid", "Hop must span at least one sample")
    return dict(requested_hz=[settings.min_frequency_hz, settings.max_frequency_hz],
                analyzed_hz=[float(np.ceil(settings.min_frequency_hz * settings.window_s) / settings.window_s),
                             float(np.floor(settings.max_frequency_hz * settings.window_s) / settings.window_s)],
                decoded_sample_rate_hz=sr, source_sample_rate_hz=source_sr, usable_upper_hz=upper,
                frequency_resolution_hz=1 / settings.window_s, time_hop_s=settings.hop_s,
                window_s=settings.window_s, exhaustive_outside_analyzed_range=False,
                ridge_peak_centers_hz=[float((np.ceil(settings.min_frequency_hz * settings.window_s)+1) / settings.window_s),
                                       float((np.floor(settings.max_frequency_hz * settings.window_s)-1) / settings.window_s)],
                edge_policy="outermost retained bins support interpolation but cannot be peak centers",
                minimum_complete_window_s=settings.window_s,
                method="single higher-rate chunked spectrum; no band boundary", nyquist_guard_fraction=.45)


def _code_identity():
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    digest = hashlib.sha256()
    for name in ("discovery.py", "episodes.py", "intake.py"):
        digest.update((Path(__file__).parent / name).read_bytes())
    return dict(git_commit=commit, implementation_sha256=digest.hexdigest(),
                numpy=version("numpy"), scipy=version("scipy"))


def discover_events(recording, *, output_dir=None, settings=None, plot_summary=True, plot_event_details=False,
                    detailed_candidates=False):
    """Return compatible measured child events; discovery.json v2 owns episodes.

    Grouping is an acoustic hypothesis with unresolved physical multiplicity.
    Budgets/coverage failures raise DiscoveryError and write status=failed;
    status=complete with zero episodes is a valid in-band negative result.
    """
    settings = settings or DiscoverySettings()
    began = time.monotonic()
    output = Path(output_dir) if output_dir is not None else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
        if (output / "discovery.json").exists():
            raise FileExistsError("Discovery output exists; use a new output directory")
    report = dict(schema_version=2, status="running", source_sha256=recording.metadata["source_sha256"],
                  settings=asdict(settings), code=_code_identity(), events=[], episodes=[], chunks=[],
                  scope="acoustic episodes; physical motion, aircraft identity and single-source interpretation unconfirmed")
    try:
        events, groups = _discover(recording, settings, report, detailed_candidates)
        report["status"] = "complete"
    except DiscoveryError as exc:
        report.update(status="failed", failure=dict(code=exc.code, message=str(exc)))
        raise
    except Exception as exc:
        report.update(status="failed", failure=dict(code="discovery_execution_error", exception_type=type(exc).__name__, message=str(exc)))
        raise
    finally:
        report["runtime_s"] = time.monotonic() - began
        if output:
            (output / "discovery.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if output:
        if plot_summary:
            _plot_groups(groups, output / "discovery.png", recording.metadata["duration_s"], settings.max_gap_s)
        for episode, group in zip(report["episodes"], groups):
            if plot_event_details:
                _plot_event(recording, group, episode, settings, output / f"{episode['proposal_id']}.png")
    return events


def _discover(recording, settings, report, detailed):
    report["coverage"] = _coverage(recording, settings)
    sr = recording.metadata["sample_rate_hz"]
    ridges, traces, counts = [], [], Counter()
    report["counts"] = counts
    points_retained = 0
    rejection_ranges = {}
    def reject(reasons, metrics=None, origins=()):
        for reason in reasons:
            counts[reason["reason"]] += 1
            name, value = reason["reason"], float(reason["measured"])
            entry = rejection_ranges.setdefault(name, dict(count=0, measured_min=value, measured_max=value,
                threshold_min=float(reason["threshold"]), threshold_max=float(reason["threshold"]), comparison=reason["comparison"]))
            entry["count"] += 1
            entry["measured_min"] = min(entry["measured_min"], value)
            entry["measured_max"] = max(entry["measured_max"], value)
            entry["threshold_min"] = min(entry["threshold_min"], float(reason["threshold"]))
            entry["threshold_max"] = max(entry["threshold_max"], float(reason["threshold"]))
        if detailed and len(traces) < settings.max_diagnostic_traces:
            traces.append(dict(origins=list(origins), measurements=metrics, rejections=reasons))
    for chunk_index, (start, data) in enumerate(recording.iter_chunks(settings.chunk_s, settings.overlap_s)):
        spec = _spectrum(data, sr, start, settings)
        raw = _paths(spec, settings) if spec is not None else []
        found = 0
        for path in raw:
            counts["raw_paths"] += 1
            counts["raw_observations"] += len(path)
            if len(path) < settings.provisional_min_points:
                reject([dict(reason="provisional_points", measured=len(path), threshold=settings.provisional_min_points, comparison=">=")])
                continue
            points = np.asarray(path)
            origin = f"chunk-{chunk_index:06d}:" + identifier("ridge-", points, recording.metadata["source_sha256"])
            ridges.append(Ridge(points, (origin,)))
            found += 1
            points_retained += len(points)
            if len(ridges) > settings.max_candidates or points_retained > settings.max_measurements:
                raise DiscoveryError("candidate_budget_exceeded", f"Retained {len(ridges)} candidates/{points_retained} observations; limits {settings.max_candidates}/{settings.max_measurements}")
        report["chunks"].append(dict(start_s=start, duration_s=len(data) / sr, raw_paths=len(raw), provisional_paths=found))
    counts["provisional_paths"] = len(ridges)
    counts["provisional_observations"] = points_retained
    work = Associations(settings)
    ridges = deduplicate(ridges, settings, work)
    counts["deduplicated_tracks"] = len(ridges)
    ridges = stitch(ridges, settings, work)
    counts["stitched_tracks"] = len(ridges)
    # Motion before grouping prevents stationary/noisy tracks from licensing
    # group acceptance, but duration rejection only occurs after reconciliation.
    moving = []
    metrics_by_id = {}
    for ridge in ridges:
        metrics, reasons = motion(ridge.points, settings)
        metrics_by_id[identifier("", ridge.points)] = metrics
        if reasons:
            reject(reasons, metrics, ridge.origins)
        else:
            moving.append(ridge)
    reconciled = reconcile(moving, settings, work)
    events, accepted_groups, episodes = [], [], []
    for members, scales, orders, group_model in reconciled:
        metrics = [metrics_by_id[identifier("", r.points)] for r in members]
        cells = intervals(np.concatenate([r.points[:, 0] for r in members]), settings.hop_s)
        observed = sum(b - a for a, b in cells)
        span = cells[-1][1] - cells[0][0]
        support = observed / span
        long = observed >= settings.min_duration_s and support >= settings.min_support
        # Brief observations need stronger contrast, resolution and continuity;
        # harmonic richness alone cannot manufacture a moving event.
        brief = (observed >= settings.brief_min_observed_s and support >= .85 and
                 any(m["median_contrast"] >= settings.brief_min_contrast and
                     m["frequency_excursion_hz"] >= 6 * m["frequency_uncertainty_hz"] and
                     m["moving_fraction"] >= .6 and m["prediction_error_q95"] <= .75 for m in metrics))
        if not long and not brief:
            reject([dict(reason="episode_support_or_brief_evidence", measured=observed,
                         threshold=settings.min_duration_s, comparison=">= long observed seconds; or strict brief gate")],
                   dict(observed_duration_s=observed, support_fraction=support, brief_min_observed_s=settings.brief_min_observed_s,
                        brief_min_support=.85, brief_min_contrast=settings.brief_min_contrast, child_metrics=metrics),
                   tuple(x for r in members for x in r.origins))
            continue
        matching_eligible = sum(len(r.points) for r in members) >= 10
        child_ids = [identifier("ridge-", r.points, recording.metadata["source_sha256"]) for r in members]
        proposal_id = "episode-" + hashlib.sha256((recording.metadata["source_sha256"] + "|".join(sorted(child_ids))).encode()).hexdigest()[:20]
        children = []
        for ridge, scale, child_id, m in zip(members, scales, child_ids, metrics):
            points = ridge.points
            t, f, w = points[:, :3].T
            margin = 2 / settings.window_s
            quality = {k: float(v) for k, v in m.items() if isinstance(v, (int, float))}
            quality.update(harmonic_count=float(len(set(orders))) if orders else 0.0,
                           frequency_resolution_hz=1 / settings.window_s, time_uncertainty_s=settings.window_s / 2,
                           frequency_sigma_hz=m["frequency_uncertainty_hz"],
                           fragment_count=float(1 + np.sum(np.diff(t) > settings.max_gap_s)),
                           max_observed_gap_s=float(np.max(np.diff(t))),
                           frequency_drop_hz=float(np.median(f[:max(3, len(f)//6)]) - np.median(f[-max(3, len(f)//6):])),
                           episode_frequency_scale=float(scale), episode_model_version=2.0, matching_eligible=float(matching_eligible))
            event = validate_event(dict(event_id=child_id, harmonic_group_id=proposal_id,
                start_s=max(0., float(t[0] - settings.window_s / 2)),
                end_s=min(recording.metadata["duration_s"], float(t[-1] + settings.window_s / 2)),
                band_hz=[max(.01, float(f.min() - margin)), float(f.max() + margin)],
                ridge=[dict(time_s=float(a), frequency_hz=float(b), weight=float(c)) for a,b,c in points[:, :3]], quality=quality))
            events.append(event)
            children.append(dict(ridge_id=child_id, raw_track_ids=list(ridge.origins), frequency_scale=float(scale),
                                 amplitude_db=points[:, 3].tolist() if points.shape[1] > 3 else None,
                                 observed_intervals_s=intervals(t, settings.hop_s), measurements=m))
        episode = dict(proposal_id=proposal_id, event_id=proposal_id, child_ridge_ids=child_ids, children=children,
                       start_s=min(e["start_s"] for e in events[-len(members):]), end_s=max(e["end_s"] for e in events[-len(members):]),
                       observed_intervals_s=cells, gaps_s=[[cells[i][1], cells[i+1][0]] for i in range(len(cells)-1)],
                       observed_duration_s=observed, support_fraction=support,
                       band_hz=[float(min(r.points[:,1].min() for r in members)), float(max(r.points[:,1].max() for r in members))],
                       matching_eligible=matching_eligible,
                       matching_limitation=None if matching_eligible else "Fewer than ten observed samples; retained for acoustic review only",
                       acceptance_path="sustained" if long else "brief_strong_evidence",
                       confidence="uncalibrated_supported" if long else "uncalibrated_brief_limited",
                       physical_source_multiplicity="unresolved", physical_motion_confirmed=False,
                       model="constant frequency scales with pairwise supported common motion", group_evidence=group_model, integer_orders=orders,
                       limitations=["Common frequency evolution does not establish one physical source or aircraft identity"])
        episodes.append(episode)
        accepted_groups.append([r.points[:, :3] for r in members])
    counts["canonical_proposals"] = len(episodes)
    counts["measured_child_tracks"] = len(events)
    report.update(events=events, episodes=episodes, counts=dict(counts), ridge_count=len(events),
                  rejections=dict(measured_ranges=rejection_ranges, counts={k:v for k,v in counts.items() if k not in ("raw_paths", "raw_observations", "provisional_paths", "provisional_observations", "deduplicated_tracks", "stitched_tracks", "canonical_proposals", "measured_child_tracks")},
                                  traces=traces, traces_enabled=detailed, trace_limit=settings.max_diagnostic_traces),
                  association_pairs=work.count, reconciliation_counts=dict(work.decision_counts), reconciliation_decisions=work.decisions,
                  decisions_truncated=len(work.decisions) == work.trace_limit)
    return events, accepted_groups


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
                        label=f"Episode {index + 1}" if harmonic == 0 and segment_index == 0 else None)
    ax.set(xlim=(0, duration), xlabel="Recording-relative time (s)", ylabel="Measured frequency (Hz)",
           title="Canonical acoustic episodes (physical source identity unresolved)")
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
    low = min(points[:, 1].min() for points in group)
    high = max(points[:, 1].max() for points in group)
    limits = (max(settings.min_frequency_hz, low * 0.9), high * 1.1)
    # Only visible cells can affect the image. Keep an extra frequency bin on
    # each side so pcolormesh reconstructs the same boundary-cell coordinates.
    # Whitening still uses the full spectrum and all measured ridges are kept.
    lower = max(0, np.searchsorted(spec.frequency, limits[0]) - 1)
    upper = min(len(spec.frequency), np.searchsorted(spec.frequency, limits[1], side="right") + 1)
    visible = slice(lower, upper)
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    ax.pcolormesh(spec.time, spec.frequency[visible], spec.contrast[visible], shading="auto", cmap="magma", vmin=0, vmax=6,
                  rasterized=True)
    for points in group:
        for segment in np.split(points, np.flatnonzero(np.diff(points[:, 0]) > settings.max_gap_s) + 1):
            ax.plot(segment[:, 0], segment[:, 1], color="cyan", lw=0.9)
    ax.set(xlim=(first, last), ylim=limits,
           xlabel="Recording-relative time (s)", ylabel="Frequency (Hz)",
           title=f"{event['event_id']}: measured ridges; acoustic proposal, identity unconfirmed")
    fig.savefig(path, dpi=130)
    plt.close(fig)
