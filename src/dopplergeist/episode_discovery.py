"""Experimental acoustic episodes with bounded, reversible associations.

Only decoded audio is read. Proposals are acoustic evidence, not proof of an
aircraft identity. No straight-pass speed/slant fit is required for acceptance.
The standard production detector remains unchanged in discovery.py.
"""
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from statistics import median
import hashlib
from importlib.metadata import version
import subprocess
import time
from collections import Counter
from bisect import bisect_left, bisect_right

import numpy as np
from scipy import optimize, signal

from .audio import Spectrum
from .contracts import validate_event
from .episodes import (Associations, DiscoveryError, Ridge, deduplicate,
                       identifier, intervals, motion, reconcile, stitch, support, uncertainty, recurrent_context, prediction_model, predict)

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
    max_candidates: int = 32768
    max_measurements: int = 1000000
    max_associations: int = 1000000
    max_diagnostic_traces: int = 100
    max_spectral_cells: int = 8000000
    max_episode_components: int = 32
    max_stitch_fragments: int = 64
    max_joint_refits: int = 16384
    max_provisional_peaks_per_band: int = 12
    provisional_tonal_db: float = 10.
    provisional_contrast: float = 1.
    brief_tonal_db: float = 12.
    brief_independent_windows: float = 4.
    short_window_s: float = .5
    short_hop_s: float = .125

    def __post_init__(self):
        values = asdict(self)
        if any(not np.isfinite(value) or value <= 0 for value in values.values()):
            raise ValueError("Discovery settings must be finite and positive")
        for name in ("max_peaks_per_frame", "provisional_min_points", "max_candidates", "max_measurements",
                     "max_associations", "max_diagnostic_traces", "max_spectral_cells", "max_episode_components", "max_stitch_fragments", "max_joint_refits", "max_provisional_peaks_per_band"):
            if type(values[name]) is not int:
                raise ValueError(f"{name} must be an integer")
        if self.provisional_min_points < 4 or self.chunk_s > 180 or self.window_s > 8 or self.max_frequency_hz > 14400:
            raise ValueError("Require >=4 provisional points, chunk <=180 s, window <=8 s and upper frequency <=14400 Hz")
        if self.min_frequency_hz < 2 / self.window_s:
            raise ValueError("Lower frequency needs at least two cycles per spectral window")
        if self.overlap_s >= self.chunk_s or self.overlap_s < self.min_duration_s + self.window_s:
            raise ValueError("Overlap must cover an event acceptance window and be shorter than a chunk")
        if not (self.hop_s <= self.window_s < self.chunk_s and self.short_hop_s <= self.short_window_s <= self.window_s) or self.min_support > 1:
            raise ValueError("Invalid spectral window/hop/support")
        if self.min_frequency_hz >= self.max_frequency_hz or type(self.max_peaks_per_frame) is not int:
            raise ValueError("Invalid frequency range or peak limit")


def _spectrum(data, sr, start, settings, *, fixed_bands=False):
    n, hop = round(sr * settings.window_s), round(sr * settings.hop_s)
    if len(data) < n:
        return None
    cells = (n // 2 + 1) * (1 + (len(data) - n) // hop)
    if cells > settings.max_spectral_cells:
        raise DiscoveryError("spectral_budget_exceeded", f"Spectrum needs {cells} cells; limit {settings.max_spectral_cells}")
    f, t, power = signal.spectrogram(data, fs=sr, window="hann", nperseg=n,
                                    noverlap=n - hop, nfft=n, scaling="density")
    if fixed_bands:
        edges = (0.,40.,1600.,6400.,25600.)
        upper = next(edge for edge in edges[1:] if edge>=settings.max_frequency_hz)
        keep = f<=min(upper,sr*.48)
    else:
        keep = (f >= settings.min_frequency_hz) & (f <= min(settings.max_frequency_hz, sr * 0.48))
    f, power = f[keep], power[keep]
    db = 10 * np.log10(power + np.finfo(np.float32).tiny)
    whitened = db - np.median(db, axis=1, keepdims=True)
    if fixed_bands:
        contrast=np.empty_like(whitened)
        for low,high in zip(edges,edges[1:]):
            band=(f>=low)&(f<high)
            if not np.any(band):continue
            values=whitened[band]
            center=np.median(values,axis=0,keepdims=True)
            scale=1.4826*np.median(np.abs(values-center),axis=0,keepdims=True)
            contrast[band]=np.clip((values-center)/np.maximum(scale,1.),-4,12)
        requested=(f>=settings.min_frequency_hz)&(f<=min(settings.max_frequency_hz,sr*.48))
        return Spectrum(t+start,f[requested],db[requested],contrast[requested])
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
    prediction_cache = {}
    for column, time in enumerate(spec.time):
        peaks, info = signal.find_peaks(spec.contrast[:, column], height=settings.min_contrast,
                                       prominence=1.5, distance=2)
        # A new frequency band receives its own bounded allocation; it cannot
        # consume the previously scanned band's peak budget.
        selected=[]
        for low,high in zip((0.,40.,1600.,6400.),(40.,1600.,6400.,25600.)):
            candidates=np.flatnonzero((spec.frequency[peaks]>=low)&(spec.frequency[peaks]<high))
            order=candidates[np.argsort(info["peak_heights"][candidates],kind='stable')[-settings.max_peaks_per_frame:]]
            selected.extend(order.tolist())
        peaks=peaks[np.asarray(selected,dtype=int)]
        df = float(spec.frequency[1]-spec.frequency[0])
        prominence_cache={}
        def local_prominence(peak):
            peak=int(peak)
            if peak not in prominence_cache:
                radius=max(4,round(max(20.,min(80.,.04*spec.frequency[peak]))/df))
                neighbours=np.r_[max(0,peak-radius):max(0,peak-3),min(len(spec.frequency),peak+4):min(len(spec.frequency),peak+radius+1)]
                prominence_cache[peak]=float(spec.db[peak,column]-np.median(spec.db[neighbours,column])) if len(neighbours) else 0.
            return prominence_cache[peak]
        raw,raw_info=signal.find_peaks(spec.db[:,column],prominence=settings.provisional_tonal_db,distance=2)
        if settings.window_s>settings.short_window_s:
            raw=np.array([],dtype=int);raw_info={'prominences':np.array([])}
        extras=[]
        for low,high in zip((0.,40.,1600.,6400.),(40.,1600.,6400.,25600.)):
            candidates=np.flatnonzero((spec.frequency[raw]>=low)&(spec.frequency[raw]<high)&(spec.contrast[raw,column]>=settings.provisional_contrast))
            order=candidates[np.argsort(raw_info['prominences'][candidates],kind='stable')[-3*settings.max_provisional_peaks_per_band:]]
            eligible=[int(raw[i]) for i in order if local_prominence(raw[i])>=settings.provisional_tonal_db and raw[i] not in peaks]
            extras.extend(sorted(eligible,key=lambda i:(-local_prominence(i),i))[:settings.max_provisional_peaks_per_band])
        peaks=np.unique(np.r_[peaks,np.asarray(extras,dtype=int)])
        frequencies = spec.frequency[peaks]
        weights = spec.contrast[peaks, column]
        # Width is measured on the actual dB peak when available; otherwise the
        # contrast-peak width supplies an explicitly uncalibrated resolution cue.
        raw_max=(spec.db[peaks,column]>=spec.db[peaks-1,column])&(spec.db[peaks,column]>=spec.db[peaks+1,column])
        widths=np.zeros(len(peaks))
        if np.any(raw_max):widths[raw_max]=signal.peak_widths(spec.db[:,column],peaks[raw_max],rel_height=.5)[0]*df
        if np.any(~raw_max):widths[~raw_max]=signal.peak_widths(spec.contrast[:,column],peaks[~raw_max],rel_height=.5)[0]*df
        sigma=np.maximum(df,widths/(2.355*np.sqrt(np.maximum(weights,1.))))
        tonal=[local_prominence(peak) for peak in peaks]
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
        # Histories only append observations. A missing frame cannot change the
        # sufficient prediction model; retain entries only for live paths.
        prediction_cache={id(path):prediction_cache[id(path)] for path in active if id(path) in prediction_cache}
        used = set()
        if active and len(peaks):
            last = np.array([path[-1] for path in active])
            dt = time - last[:, 0]
            delta = frequencies[None, :] - last[:, 1, None]
            predictions=[]
            for path in active:
                token=id(path)
                if token not in prediction_cache or prediction_cache[token][0]!=path[-1][0]:
                    prediction_cache[token]=(path[-1][0],prediction_model(path,settings))
                predictions.append(predict(prediction_cache[token][1],time,next_sigma=0.))
            means = np.array([p[0] for p in predictions])
            tolerance = np.sqrt(np.array([p[1] for p in predictions])[:,None]**2+9*sigma[None,:]**2)
            allowed = np.abs(delta) <= np.maximum(np.maximum(8,last[:,1,None]*.08)*dt[:,None],3/settings.window_s)
            costs = np.abs(frequencies[None, :] - means[:, None]) / tolerance
            costs += .5*np.maximum(0.,dt[:,None]-settings.hop_s)/settings.window_s
            allowed &= costs <= 1
            costs = np.where(allowed, costs, 1e6)
            rows, cols = optimize.linear_sum_assignment(costs)
            for row, col in zip(rows, cols):
                if costs[row, col] < 1e6:
                    active[row].append((float(time), float(frequencies[col]), float(weights[col]), float(spec.db[peaks[col], column]), float(sigma[col]), float(tonal[col]),settings.hop_s,settings.window_s))
                    used.add(col)
        active.extend([(float(time), float(frequency), float(weight), float(spec.db[peaks[j], column]), float(sigma[j]), float(tonal[j]),settings.hop_s,settings.window_s)]
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
    if any(abs(value * sr - round(value * sr)) > 1e-7 for value in (settings.window_s, settings.hop_s, settings.short_window_s, settings.short_hop_s)):
        raise DiscoveryError("unsupported_time_grid", "Window and hop must be integer sample counts")
    step = settings.chunk_s - settings.overlap_s
    if any(abs(step / hop - round(step / hop)) > 1e-7 for hop in (settings.hop_s,settings.short_hop_s)):
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
                method="chunked fixed-band normalization with bounded short-window analysis", nyquist_guard_fraction=.45,
                normalization_bands_hz=[[0.,40.],[40.,1600.],[1600.,6400.],[6400.,25600.]],
                peak_budget_per_band=settings.max_peaks_per_frame,
                additional_short_tonal_peak_budget_per_band=settings.max_provisional_peaks_per_band,
                short_profile=dict(window_s=settings.short_window_s,hop_s=settings.short_hop_s,
                                           frequency_resolution_hz=1/settings.short_window_s,
                                           minimum_frequency_hz=max(settings.min_frequency_hz,2/settings.short_window_s)),
                profile_selection="two resolutions; short primary peak rate matched per second; effective profiles listed per chunk")


def _code_identity():
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    digest = hashlib.sha256()
    for name in ("episode_discovery.py", "episodes.py", "intake.py"):
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
    cpu_began = time.process_time()
    output = Path(output_dir) if output_dir is not None else None
    if output:
        output.mkdir(parents=True, exist_ok=True)
        if (output / "discovery.json").exists():
            raise FileExistsError("Discovery output exists; use a new output directory")
    report = dict(schema_version=2, status="running", source_sha256=recording.metadata["source_sha256"],
                  settings=asdict(settings), code=_code_identity(), algorithm_revision="reversible-episodes-2", boundary_semantics="observed_hop_cells", events=[], episodes=[], chunks=[],
                  scope="acoustic episodes; physical motion, aircraft identity and single-source interpretation unconfirmed",
                  counts_semantics=dict(spectral_measurements="Peak measurement instances per chunk/profile, counted once before directional linking; overlapping chunks reuse audio",
                      raw_observations="Directional path observation instances; includes both association sweeps and chunk/profile reuse",
                      canonical_proposals="Acoustic episode hypotheses; not a physical emitter or aircraft count"))
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
        report["cpu_time_s"] = time.process_time() - cpu_began
        if output:
            (output / "discovery.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if output:
        if plot_summary:
            _plot_groups(groups, output / "discovery.png", recording.metadata["duration_s"], settings.max_gap_s)
        for episode, group in zip(report["episodes"], groups):
            if plot_event_details:
                _plot_event(recording, group, episode, settings, output / f"{episode['proposal_id']}.png")
    return events


def _episode_evidence(members,scales,settings,metrics):
    model_points=[]
    for ridge,scale in zip(members,scales):
        p=ridge.points.copy();p[:,1]/=scale
        if p.shape[1]>4:p[:,4]/=scale
        model_points.append(p)
    pooled=np.concatenate(model_points)
    priority=pooled[:,4] if pooled.shape[1]>4 else -pooled[:,2]
    pooled=pooled[np.lexsort((pooled[:,1],priority,pooled[:,0]))]
    _,unique=np.unique(pooled[:,0],return_index=True)
    pooled=pooled[np.sort(unique)]
    episode_motion,episode_motion_rejections=motion(pooled,settings)
    if len(members)>1:
        # Interleaving estimates of common motion adds cross-component
        # measurement jitter to naive total variation. Count this evidence
        # once: every child already passed its own variation safeguard.
        episode_motion['pooled_variation_ratio']=episode_motion['variation_ratio']
        episode_motion['variation_ratio']=max(m['variation_ratio'] for m in metrics)
        episode_motion['variation_evidence']='maximum child variation; shared evolution checked jointly'
        episode_motion_rejections=[r for r in episode_motion_rejections if r['reason']!='wandering_or_modulation']
    cells, observed, independent = support(np.concatenate([r.points for r in members]),settings)
    span = cells[-1][1] - cells[0][0]
    support_fraction = observed / span
    long = span >= settings.min_duration_s and observed >= settings.min_duration_s * settings.min_support and support_fraction >= settings.min_support
    # Brief observations need stronger contrast, resolution and continuity;
    # harmonic richness alone cannot manufacture a moving event.
    # Independent component support can fill missing observations, while
    # repeated profiles of the same scale do not become extra harmonics.
    distinct=[]
    for ridge,scale in zip(members,scales):
        fractional=2*uncertainty(ridge.points,settings)/np.median(ridge.points[:,1])
        if not any(abs(scale/other-1)<=fractional for other in distinct):distinct.append(scale)
    brief_support=.75 if len(distinct)>=2 else .85
    brief = (observed >= settings.brief_min_observed_s and support_fraction >= brief_support and
             independent >= settings.brief_independent_windows and
             (max(m['median_contrast'] for m in metrics)>=settings.brief_min_contrast or
              max(m.get('median_spectral_prominence_db',0.) for m in metrics)>=settings.brief_tonal_db) and
             episode_motion['frequency_excursion_hz']>=6*episode_motion['frequency_uncertainty_hz'] and
             episode_motion['moving_fraction']>=.6 and episode_motion['prediction_error_q95']<=.75)
    return dict(points=pooled,motion=episode_motion,rejections=episode_motion_rejections,
                cells=cells,observed=observed,independent=independent,span=span,
                support_fraction=support_fraction,long=long,brief=brief,
                distinct=distinct,brief_support=brief_support)


def _discover(recording, settings, report, detailed):
    report["coverage"] = _coverage(recording, settings)
    sr = recording.metadata["sample_rate_hz"]
    ridges, traces, counts = [], [], Counter(raw_paths=0,raw_observations=0,spectral_measurements=0)
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
    work = Associations(settings)
    for chunk_index, (start, data) in enumerate(recording.iter_chunks(settings.chunk_s, settings.overlap_s)):
        local=[];raw_count=0;profiles=[]
        passes=[settings]
        if settings.window_s>settings.short_window_s:
            # Keep the primary candidate rate per second bounded as hops shrink.
            short_peaks=min(settings.max_peaks_per_frame,max(4,round(settings.max_peaks_per_frame*settings.short_hop_s/settings.hop_s)))
            passes.append(replace(settings,window_s=settings.short_window_s,hop_s=settings.short_hop_s,
                                  max_peaks_per_frame=short_peaks,
                                  min_frequency_hz=max(settings.min_frequency_hz,2/settings.short_window_s)))
        for profile_index,profile in enumerate(passes):
            spec=_spectrum(data,sr,start,profile,fixed_bands=True)
            found=[]
            if spec is not None:
                reflected=float(spec.time[0]+spec.time[-1])
                reverse=Spectrum(reflected-spec.time[::-1],spec.frequency,spec.db[:,::-1],spec.contrast[:,::-1])
                for direction,spectrum in [('forward',spec),('backward',reverse)]:
                    for path in _paths(spectrum,profile):
                        counts['raw_paths']+=1;counts['raw_observations']+=len(path);raw_count+=1
                        if direction=='forward':counts['spectral_measurements']+=len(path)
                        if len(path)<profile.provisional_min_points:
                            reject([dict(reason='provisional_points',measured=len(path),threshold=profile.provisional_min_points,comparison='>=')])
                            continue
                        points=np.asarray(path)
                        if direction=='backward':points[:,0]=reflected-points[:,0];points=points[::-1].copy()
                        origin=f'chunk-{chunk_index:06d}:profile-{profile_index}:{direction}:'+identifier('ridge-',points,recording.metadata['source_sha256'])
                        found.append(Ridge(points,(origin,)))
                found=deduplicate(found,profile,work)
                found=stitch(found,profile,work)
            profiles.append(dict(window_s=profile.window_s,hop_s=profile.hop_s,frequency_range_hz=[profile.min_frequency_hz,profile.max_frequency_hz],primary_peaks_per_band=profile.max_peaks_per_frame,additional_tonal_peaks_per_band=profile.max_provisional_peaks_per_band if profile.window_s<=profile.short_window_s else 0,provisional_tracks=len(found)))
            for ridge in found:
                p=ridge.points;_,_,independent=support(p,profile)
                interior=p[0,0]>start+settings.max_fragment_gap_s and p[-1,0]<start+len(data)/sr-settings.max_fragment_gap_s
                if np.median(p[:,2])<settings.min_contrast and independent<2 and interior:
                    reject([dict(reason='provisional_tonal_windows',measured=independent,threshold=2.,comparison='>=')])
                else:local.append(ridge)
        local=deduplicate(local,settings,work)
        ridges.extend(local)
        points_retained+=sum(len(r.points) for r in local)
        if len(ridges)>settings.max_candidates or points_retained>settings.max_measurements:
            raise DiscoveryError('candidate_budget_exceeded',f'Retained {len(ridges)} candidates/{points_retained} observations; limits {settings.max_candidates}/{settings.max_measurements}')
        report['chunks'].append(dict(start_s=start,duration_s=len(data)/sr,raw_paths=raw_count,provisional_paths=len(local),association_sweeps=2,profiles=profiles,association_work=work.count))
    counts["provisional_paths"] = len(ridges)
    counts["provisional_observations"] = points_retained
    ridges = deduplicate(ridges, settings, work)
    counts["deduplicated_tracks"] = len(ridges)
    report["association_work_after_deduplication"]=work.count
    ridges = stitch(ridges, settings, work)
    counts["stitched_tracks"] = len(ridges)
    report["association_work_after_stitching"]=work.count
    # Motion before grouping prevents stationary/noisy tracks from licensing
    # group acceptance, but duration rejection only occurs after reconciliation.
    moving = []
    metrics_by_id = {}
    for ridge in ridges:
        if len(ridge.points)<8:
            # Both continuation sweeps have finished. Fewer than eight samples
            # cannot enter the shared-motion model or either acceptance path.
            reject([dict(reason='post_association_support',measured=len(ridge.points),threshold=8.,comparison='>=')],origins=ridge.origins)
            continue
        metrics, reasons = motion(ridge.points, settings)
        metrics_by_id[identifier("", ridge.points)] = metrics
        if reasons and not (all(r['reason'] in ('unresolved_frequency_motion','insufficient_distributed_motion','motion_concentrated_or_unresolved') for r in reasons)
                            and len(ridge.points)>=8 and metrics['frequency_excursion_hz']>=3*metrics['frequency_uncertainty_hz'] and metrics['moving_fraction']>=.1):
            reject(reasons, metrics, ridge.origins)
        else:
            moving.append(ridge)
    validity={}
    protected_extensions=[];protected_keys=set()
    def valid_group(members,model):
        ids=tuple(identifier('',r.points) for r in members)
        if ids not in validity:
            work.charge();work.refit()
            measurements=[metrics_by_id[identifier('',r.points)] for r in members]
            evidence=_episode_evidence(members,model['scales'],settings,measurements)
            validity[ids]=dict(valid=not evidence['rejections'] and (evidence['long'] or evidence['brief']),
                motion_rejections=evidence['rejections'],span_s=evidence['span'],observed_duration_s=evidence['observed'],
                support_fraction=evidence['support_fraction'],independent_windows=evidence['independent'],
                sustained=evidence['long'],brief=evidence['brief'],brief_support_threshold=evidence['brief_support'])
            work.decision_counts['episode_validity_checks']+=1
        return validity[ids]['valid']
    def preserve_supported_parent(left,left_model,right,right_model,members,model):
        # Provisional groups may accumulate evidence. Once a measured subgroup
        # qualifies, a later union must not erase it through failed acceptance.
        if valid_group(members,model) or not (valid_group(left,left_model) or valid_group(right,right_model)):return True
        ids=tuple(identifier('',r.points) for r in members)
        if ids not in protected_keys and len(protected_extensions)<min(20,settings.max_diagnostic_traces):
            protected_keys.add(ids)
            protected_extensions.append(dict(child_ridge_ids=[identifier('ridge-',r.points,recording.metadata['source_sha256']) for r in members],
                joint_evidence=validity[ids],sustained_thresholds=dict(extent_s=settings.min_duration_s,
                    observed_s=settings.min_duration_s*settings.min_support,support_fraction=settings.min_support),
                brief_thresholds=dict(observed_s=settings.brief_min_observed_s,independent_windows=settings.brief_independent_windows)))
        return False
    reconciled = reconcile(moving, settings, work, accept_merge=preserve_supported_parent)
    events, accepted_groups, episodes = [], [], []
    context_ridges=sorted(ridges,key=lambda r:r.points[0,0])
    context_starts=[float(r.points[0,0]) for r in context_ridges]
    context_rejections=[]
    pending=list(reconciled)
    alternative_members={}
    while pending:
        members,scales,orders,group_model=pending.pop(0)
        metrics = [metrics_by_id[identifier("", r.points)] for r in members]
        evaluation=_episode_evidence(members,scales,settings,metrics)
        pooled=evaluation['points'];episode_motion=evaluation['motion'];episode_motion_rejections=evaluation['rejections']
        if episode_motion_rejections:
            if len(members)>1:
                work.decision_counts['episode_group_retracted']+=1
                member_ids=[identifier('ridge-',r.points,recording.metadata['source_sha256']) for r in members]
                for ridge,rid in zip(members,member_ids):
                    alternative_members[rid]=[i for i in member_ids if i!=rid]
                    pending.append(([ridge],[1.],[1],dict(scales=[1.],checked_overlap_pairs=0,worst_residual_fraction_of_limit=None,min_resolved_motion_witnesses=0)))
            else:reject(episode_motion_rejections,episode_motion,tuple(x for r in members for x in r.origins))
            continue
        cells=evaluation['cells'];observed=evaluation['observed'];independent=evaluation['independent']
        span=evaluation['span'];support_fraction=evaluation['support_fraction']
        long=evaluation['long'];brief=evaluation['brief'];distinct=evaluation['distinct'];brief_support=evaluation['brief_support']
        if not long and not brief:
            if len(members)>1:
                work.decision_counts['episode_group_retracted_for_support']+=1
                member_ids=[identifier('ridge-',r.points,recording.metadata['source_sha256']) for r in members]
                for ridge,rid in zip(members,member_ids):
                    alternative_members[rid]=[i for i in member_ids if i!=rid]
                    pending.append(([ridge],[1.],[1],dict(scales=[1.],checked_overlap_pairs=0,worst_residual_fraction_of_limit=None,min_resolved_motion_witnesses=0)))
                continue
            # Report each failed gate on both alternative paths. A single
            # duration number would obscure support/contrast failures.
            salience=max(max(m['median_contrast'] for m in metrics)/settings.brief_min_contrast,
                         max(m.get('median_spectral_prominence_db',0.) for m in metrics)/settings.brief_tonal_db)
            gates = [("sustained_extent_s", span, settings.min_duration_s, ">="),
                     ("sustained_observed_duration_s", observed, settings.min_duration_s * settings.min_support, ">="),
                     ("sustained_support_fraction", support_fraction, settings.min_support, ">="),
                     ("brief_observed_duration_s", observed, settings.brief_min_observed_s, ">="),
                     ("brief_support_fraction", support_fraction, brief_support, ">="),
                     ("brief_independent_windows", independent, settings.brief_independent_windows, ">="),
                     ("brief_salience_ratio", salience, 1., ">="),
                     ("brief_excursion_sigma", episode_motion["frequency_excursion_hz"] / episode_motion["frequency_uncertainty_hz"], 6., ">="),
                     ("brief_moving_fraction", episode_motion["moving_fraction"], .6, ">="),
                     ("brief_prediction_error_q95", episode_motion["prediction_error_q95"], .75, "<=")]
            reject([dict(reason=name, measured=float(value), threshold=float(limit), comparison=op)
                    for name,value,limit,op in gates if (value < limit if op == ">=" else value > limit)],
                   dict(observed_duration_s=observed, support_fraction=support_fraction, child_metrics=metrics,
                        episode_motion=episode_motion,brief_salience_ratio=salience),
                   tuple(x for r in members for x in r.origins))
            continue
        if not long:
            radius=max(30.,3*span)
            first=bisect_left(context_starts,float(pooled[0,0]-radius))
            last=bisect_right(context_starts,float(pooled[-1,0]+radius))
            periodic=recurrent_context(pooled,context_ridges[first:last],settings,work)
            if periodic is not None:
                reject([dict(reason='recurrent_modulation_context',measured=float(periodic['occurrences']),threshold=3.,comparison='<')],periodic,tuple(x for r in members for x in r.origins))
                if len(context_rejections)<settings.max_diagnostic_traces:context_rejections.append(periodic)
                continue
        matching_eligible = sum(len(r.points) for r in members) >= 10
        child_ids = [identifier("ridge-", r.points, recording.metadata["source_sha256"]) for r in members]
        proposal_id = "episode-" + hashlib.sha256((recording.metadata["source_sha256"] + "|".join(sorted(child_ids))).encode()).hexdigest()[:20]
        children = []
        for ridge, scale, child_id, m in zip(members, scales, child_ids, metrics):
            points = ridge.points
            t, f, w = points[:, :3].T
            windows=points[:,7] if points.shape[1]>7 else np.full(len(points),settings.window_s)
            resolution=float(np.max(1/windows))
            margin = 2*resolution
            quality = {k: float(v) for k, v in m.items() if isinstance(v, (int, float))}
            quality.update(harmonic_count=float(len(set(orders))) if orders else 0.0,
                           frequency_resolution_hz=resolution, frequency_resolution_min_hz=float(np.min(1/windows)), time_uncertainty_s=float(np.max(windows)/2),
                           frequency_sigma_hz=m["frequency_uncertainty_hz"],
                           fragment_count=float(1 + np.sum(np.diff(t) > settings.max_gap_s)),
                           max_observed_gap_s=float(np.max(np.diff(t))),
                           frequency_drop_hz=float(np.median(f[:max(3, len(f)//6)]) - np.median(f[-max(3, len(f)//6):])),
                           episode_frequency_scale=float(scale), episode_model_version=2.0, matching_eligible=float(matching_eligible))
            event = validate_event(dict(event_id=child_id, harmonic_group_id=proposal_id,
                start_s=float(support(points,settings)[0][0][0]),
                end_s=min(recording.metadata["duration_s"],float(support(points,settings)[0][-1][1])),
                band_hz=[max(.01, float(f.min() - margin)), float(f.max() + margin)],
                ridge=[dict(time_s=float(a), frequency_hz=float(b), weight=float(c)) for a,b,c in points[:, :3]], quality=quality))
            events.append(event)
            children.append(dict(ridge_id=child_id, raw_track_ids=list(ridge.origins), frequency_scale=float(scale),
                                 amplitude_db=points[:, 3].tolist() if points.shape[1] > 3 else None,
                                 frequency_uncertainties_hz=points[:,4].tolist() if points.shape[1]>4 else None,
                                 spectral_prominence_db=points[:,5].tolist() if points.shape[1]>5 else None,
                                 observation_hops_s=points[:,6].tolist() if points.shape[1]>6 else None,
                                 observation_windows_s=points[:,7].tolist() if points.shape[1]>7 else None,
                                 observed_intervals_s=support(points,settings)[0], measurements=m))
        episode = dict(proposal_id=proposal_id, event_id=proposal_id, child_ridge_ids=child_ids, children=children,
                       start_s=min(e["start_s"] for e in events[-len(members):]), end_s=max(e["end_s"] for e in events[-len(members):]),
                       observed_intervals_s=cells, gaps_s=[[cells[i][1], cells[i+1][0]] for i in range(len(cells)-1)],
                       observed_duration_s=observed, support_fraction=support_fraction, independent_windows=independent, brief_support_components=len(distinct),
                       band_hz=[float(min(r.points[:,1].min() for r in members)), float(max(r.points[:,1].max() for r in members))],
                       matching_eligible=matching_eligible,
                       matching_limitation=None if matching_eligible else "Fewer than ten observed samples; retained for acoustic review only",
                       acceptance_path="sustained" if long else "brief_strong_evidence",
                       confidence="uncalibrated_supported" if long else "uncalibrated_brief_limited",
                       physical_source_multiplicity="unresolved", physical_motion_confirmed=False,
                       unresolved_grouping_alternatives=sorted({other for rid in child_ids for other in alternative_members.get(rid,[])}),
                       model="constant frequency scales assessed against joint observed motion", group_evidence=group_model, episode_motion=episode_motion, integer_orders=orders,
                       limitations=["Common frequency evolution does not establish one physical source or aircraft identity"])
        episodes.append(episode)
        accepted_groups.append([r.points[:, :3] for r in members])
    counts["canonical_proposals"] = len(episodes)
    counts["measured_child_tracks"] = len(events)
    report.update(events=events, episodes=episodes, counts=dict(counts), ridge_count=len(events),
                  rejections=dict(measured_ranges=rejection_ranges, counts={k:v for k,v in counts.items() if k not in ("raw_paths", "raw_observations", "spectral_measurements", "provisional_paths", "provisional_observations", "deduplicated_tracks", "stitched_tracks", "canonical_proposals", "measured_child_tracks")},
                                  traces=traces, traces_enabled=detailed, trace_limit=settings.max_diagnostic_traces),
                  association_pairs=work.count, joint_refits=work.refits, recurrent_context_rejections=context_rejections, protected_group_extensions=protected_extensions, reconciliation_counts=dict(work.decision_counts), reconciliation_decisions=work.decisions,
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
           title=f"Canonical acoustic episodes (n={len(groups)}; physical source identity unresolved)")
    if 0<len(groups)<=12:
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
