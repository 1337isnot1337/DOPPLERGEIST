"""Frozen-prediction spectral context diagnostics, separate from core-fit loss.

Implements the fixed development protocol in the physical verifier's
spectral-context-diagnostic/validate_expanded_support.py. Every supplied supported
group and every retained spatial/clock mode is considered. This module does not
refit candidates, decide a location, or calibrate a probability/uncertainty.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .audio import spectrogram
from .geometry import ecef
from .matching import predict_fitted_ridge


@dataclass(frozen=True)
class ContextSettings:
    expansion_s: float = 120.0
    core_guard_s: float = 2.0
    low_band_multiplier: float = 0.5
    high_band_multiplier: float = 2.0
    min_frequency_hz: float = 40.0
    max_frequency_hz: float = 1600.0
    window_s: float = 2.0
    hop_s: float = 0.25
    sideband_offsets_hz: tuple = (-10.0, -5.0, 5.0, 10.0)
    min_common_samples: int = 40
    block_s: float = 10.0
    bootstrap_samples: int = 2000
    bootstrap_seed: int = 7231
    max_window_s: float = 600.0
    max_modes: int = 1000
    sound_speed_mps: float = 343.0

    def __post_init__(self):
        for key in ("expansion_s", "low_band_multiplier", "high_band_multiplier",
                    "min_frequency_hz", "max_frequency_hz", "window_s", "hop_s",
                    "block_s", "max_window_s", "sound_speed_mps"):
            if not np.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError(f"{key} must be positive and finite")
        if not np.isfinite(self.core_guard_s) or self.core_guard_s < self.window_s / 2:
            raise ValueError("Core guard must cover at least half the spectral window")
        if self.hop_s >= self.window_s or self.min_frequency_hz >= self.max_frequency_hz:
            raise ValueError("Need hop below window and increasing frequency bounds")
        for key in ("min_common_samples", "bootstrap_samples", "max_modes"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise ValueError(f"{key} must be a positive integer")
        if type(self.bootstrap_seed) is not int or self.bootstrap_seed < 0:
            raise ValueError("bootstrap_seed must be a nonnegative integer")
        offsets = np.asarray(self.sideband_offsets_hz, dtype=float)
        if offsets.ndim != 1 or len(offsets) < 2 or not np.isfinite(offsets).all() or (offsets == 0).any():
            raise ValueError("Need finite nonzero sideband offsets")
        if not (offsets < 0).any() or not (offsets > 0).any():
            raise ValueError("Sidebands must sample both sides of the prediction")
        object.__setattr__(self, "sideband_offsets_hz", tuple(float(x) for x in offsets))


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return {"nonfinite": str(value)}
    if isinstance(value, Path):
        return str(value)
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True,
                                    allow_nan=False).encode()).hexdigest()


def _file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _dump(path, value):
    path.write_text(json.dumps(_jsonable(value), indent=2, allow_nan=False) + "\n")


def _track_receipt(track):
    arrays = {name: getattr(track, name) for name in ("time", "xyz") if hasattr(track, name)}
    if hasattr(getattr(track, "spline", None), "c"):
        arrays["spline_coefficients"] = track.spline.c
    return {"provider_type": f"{type(track).__module__}.{type(track).__qualname__}",
            "arrays_sha256": {key: hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()
                              for key, value in arrays.items()},
            "full_trajectory_fingerprint": all(k in arrays for k in ("time", "xyz", "spline_coefficients"))}


def _prepare_mode(row, events, measurements, tracks, c):
    indices = list(row.get("event_indices", range(len(events))))
    if any(type(i) is not int or not 0 <= i < len(events) for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("Invalid or duplicate event_indices")
    if not set(range(len(events))).issubset(indices):
        raise ValueError("Mode does not explain every supplied supported event")
    if len(indices) != len(row["flight_ids"]) or len(indices) != len(row["event_diagnostics"]):
        raise ValueError("Flight/diagnostic/event mapping lengths differ")
    clock = float(row["recording_start_time_s"])
    observer = ecef(float(row["lat"]), float(row["lon"]), float(row["elev_m"]))
    if not np.isfinite(clock) or not np.isfinite(observer).all():
        raise ValueError("Nonfinite location or shared recording clock")
    prepared = {}
    for local_index, event_index in enumerate(indices):
        track_id = row["flight_ids"][local_index]
        track = tracks[track_id]
        spec, ridge, weight, _ = measurements[event_index]
        t, ridge, weight = (np.asarray(a, dtype=float) for a in (spec.time, ridge, weight))
        if t.ndim != 1 or t.shape != ridge.shape or t.shape != weight.shape:
            raise ValueError("Malformed frozen core measurement")
        if not np.isfinite(weight).all() or (weight < 0).any():
            raise ValueError("Invalid frozen core weights")
        measured = np.isfinite(t) & np.isfinite(ridge) & (weight > 0)
        if measured.sum() < 10:
            raise ValueError("Frozen core has fewer than ten supported samples")
        factor, emission, _ = track.acoustic(clock + t[measured], observer, c)
        if not np.isfinite(factor).all() or not np.isfinite(emission).all():
            raise ValueError("Mode lacks complete support for its fitted core")
        diagnostic = row["event_diagnostics"][local_index]
        f0, slope = float(diagnostic["f0_hz"]), float(diagnostic["source_drift_hz_s"])
        anchor = float(diagnostic.get("source_reference_emission_time_s",
                                     (emission.min() + emission.max()) / 2))
        if f0 <= 0 or not np.isfinite([f0, slope, anchor]).all():
            raise ValueError("Invalid frozen source-frequency parameters")
        prepared[event_index] = {
            "track": track, "track_id": track_id, "f0_hz": f0,
            "source_drift_hz_s": slope, "reference_emission_time_s": anchor,
            "anchor_source": ("candidate_diagnostic" if "source_reference_emission_time_s" in diagnostic
                              else "reconstructed_from_frozen_core"),
        }
    return {"clock": clock, "observer": observer, "events": prepared}


def _bootstrap(delta, times, settings, rng):
    """Paired blocks; batch gathering bounds memory for many retained modes."""
    blocks = np.floor(times / settings.block_s).astype(np.int64)
    unique = np.unique(blocks)
    sums = np.array([delta[:, blocks == b].sum(axis=1) for b in unique])
    counts = np.array([(blocks == b).sum() for b in unique])
    selections = rng.integers(0, len(unique), size=(settings.bootstrap_samples, len(unique)))
    result = np.empty((settings.bootstrap_samples, len(delta)))
    for first in range(0, settings.bootstrap_samples, 64):
        selected = selections[first:first + 64]
        result[first:first + 64] = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)[:, None]
    return result


def validate_context(recording, candidates, tracks, events, measurements, *,
                     detected_events=None, output_dir=None, settings=None):
    """Compare frozen modes on common, unscored spectral context.

    Supply *all* supported prepared independent groups. A candidate omitting any
    group stays unsupported, rather than being silently scored on fewer events.
    ``detected_events`` should additionally include unconfirmed raw proposals so
    no fitted core is reused as context. Every retained spatial/clock row stays
    separate, including different modes of the same flight association.

    Result ``compared`` means a diagnostic comparison was possible. It is not a
    supported-location decision. Contrast and descriptive block intervals must
    not be converted to core Hz loss, probability, or location coverage.
    """
    began = time.monotonic()
    settings = settings or ContextSettings()
    if not isinstance(settings, ContextSettings):
        raise TypeError("settings must be ContextSettings")
    if not candidates or not events or len(events) != len(measurements):
        raise ValueError("Need retained candidates and matching complete event/measurement lists")
    output = Path(output_dir) if output_dir is not None else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
    sr, duration = recording.metadata["sample_rate_hz"], recording.metadata["duration_s"]
    samples = np.memmap(recording.samples_path, dtype="<f4", mode="r")
    if type(sr) is not int or sr <= 0 or not np.isfinite(duration) or abs(len(samples) / sr - duration) > 1 / sr:
        raise ValueError("Decoded sample cache differs from recording metadata")
    original = list(detected_events if detected_events is not None else events)
    exclusions = [(float(e["start_s"]), float(e["end_s"])) for e in original]
    if any(not np.isfinite([a, b]).all() or not 0 <= a < b <= duration for a, b in exclusions):
        raise ValueError("Detected core bounds must lie within the recording")
    groups, ids = set(), set()
    for e in events:
        identifier = e["event_id"]
        group = e.get("harmonic_group_id") or identifier
        if identifier in ids or group in groups:
            raise ValueError("Supply independent prepared groups; harmonics/fragments count once")
        ids.add(identifier)
        groups.add(group)
        if not 0 <= e["start_s"] < e["end_s"] <= duration:
            raise ValueError("Supported core lies outside recording")
        band = np.asarray(e["band_hz"], dtype=float)
        if band.shape != (2,) or not np.isfinite(band).all() or not 0 < band[0] < band[1]:
            raise ValueError("Supported events need increasing finite frequency bands")
    modes = [{"mode_id": f"mode-{i+1:04d}", "input_index": i,
              "input_candidate_sha256": _digest(row), "flight_ids": list(row.get("flight_ids", [])),
              "event_indices": list(row.get("event_indices", range(len(events)))),
              "core_score": row.get("score"), "core_score_kind": row.get("score_kind"),
              "status": "pending", "limitations": []} for i, row in enumerate(candidates)]
    report = {
        "context_schema_version": 1, "status": "inconclusive",
        "score_kind": "frozen_context_contrast_excess", "location_decision": "not_evaluated",
        "settings": asdict(settings), "candidate_mode_count": len(candidates),
        "supported_event_count": len(events), "supported_event_ids": [e["event_id"] for e in events],
        "modes": modes, "events": [], "ranking": [], "all_modes_compared": False,
        "inputs": {"recording_source_sha256": recording.metadata.get("source_sha256"),
                   "decoded_samples_sha256": _file_hash(recording.samples_path),
                   "candidates_sha256": _digest(candidates), "events_sha256": _digest(events),
                   "excluded_detected_cores_sha256": _digest(original),
                   "measurements_sha256": _digest([(m[0].time, m[1], m[2]) for m in measurements]),
                   "trajectory_receipts": {str(k): _track_receipt(v) for k, v in tracks.items()}},
        "implementation_sha256": _file_hash(__file__),
        "implementation_dependencies_sha256": {name: _file_hash(Path(__file__).with_name(name))
                                                for name in ("audio.py", "geometry.py", "matching.py")},
        "numpy_version": np.__version__,
        "limits": [
            "Development protocol, not independent location-accuracy evidence.",
            "Core location, clock, f0 and emission-time source drift are frozen; no context refit.",
            "Linear source drift is extrapolated beyond its fitted core.",
            "Common-support selection is symmetric and conditional on every evaluable retained mode.",
            "Spectrogram preprocessing uses the fixed expanded window; only outside-core bins are scored.",
            "Paired block intervals are descriptive, not calibrated localization confidence.",
            "Contrast units remain separate from robust Hz loss and association scores.",
        ],
    }

    def finish():
        report["elapsed_s"] = time.monotonic() - began
        # Measure inside this process: an external timer around a pid namespace
        # can otherwise report only the small namespace launcher.
        try:
            import resource
            import sys
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report["process_peak_rss_mib"] = peak / (1024**2 if sys.platform == "darwin" else 1024)
        except ImportError:
            report["process_peak_rss_mib"] = None
        if output is not None:
            _dump(output / "report.json", report)
        return report

    if len(candidates) > settings.max_modes:
        for mode in modes:
            mode.update(status="not_evaluated", limitations=["mode_budget_exceeded"])
        report["limits"].append("Mode budget exceeded; no input mode was silently truncated.")
        return finish()
    prepared = {}
    for i, (row, mode) in enumerate(zip(candidates, modes)):
        try:
            prepared[i] = _prepare_mode(row, events, measurements, tracks, settings.sound_speed_mps)
            mode["frozen_parameters"] = [{k: v for k, v in prepared[i]["events"][j].items() if k != "track"}
                                         for j in range(len(events))]
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            mode.update(status="unsupported", limitations=[f"frozen_model_unavailable: {exc}"])
    active = list(prepared)
    if not active:
        return finish()
    means = np.full((len(events), len(active)), np.nan)
    bootstraps = []
    rng = np.random.default_rng(settings.bootstrap_seed)
    for event_index, event in enumerate(events):
        start, end = max(0.0, event["start_s"] - settings.expansion_s), min(duration, event["end_s"] + settings.expansion_s)
        band = [max(settings.min_frequency_hz, event["band_hz"][0] * settings.low_band_multiplier),
                min(settings.max_frequency_hz, sr / 2, event["band_hz"][1] * settings.high_band_multiplier)]
        evidence = {"event_id": event["event_id"], "event_index": event_index,
                    "expanded_window_s": [start, end], "expanded_band_hz": band,
                    "status": "unavailable", "scores": []}
        report["events"].append(evidence)
        if end - start > settings.max_window_s or end - start < settings.window_s or band[0] >= band[1]:
            evidence["reason"] = "context_window_or_band_budget"
            continue
        first, last = round(start * sr), round(end * sr)
        audio = np.asarray(samples[first:last])
        if not np.isfinite(audio).all():
            evidence["reason"] = "nonfinite_context_samples"
            continue
        spec = spectrogram(audio, sr, band, start=first / sr,
                           window_s=settings.window_s, hop_s=settings.hop_s)
        on, off, predictions, support = [], [], [], []
        evidence["prediction_failures"] = {}
        for index in active:
            mode, frozen = prepared[index], prepared[index]["events"][event_index]
            try:
                frequency = predict_fitted_ridge(frozen["track"], mode["observer"],
                    mode["clock"] + spec.time, {"f0_hz": frozen["f0_hz"],
                    "source_drift_hz_s": frozen["source_drift_hz_s"],
                    "source_reference_emission_time_s": frozen["reference_emission_time_s"]},
                    settings.sound_speed_mps)
                observed = spec.sample(spec.time, frequency)
                sidebands = np.mean([spec.sample(spec.time, frequency + shift)
                                     for shift in settings.sideband_offsets_hz], axis=0)
            except (ValueError, FloatingPointError) as exc:
                evidence["prediction_failures"][modes[index]["mode_id"]] = str(exc)
                frequency = observed = sidebands = np.full(len(spec.time), np.nan)
            valid = np.isfinite(frequency) & (frequency > 0) & np.isfinite(observed) & np.isfinite(sidebands)
            on.append(observed)
            off.append(sidebands)
            predictions.append(frequency)
            support.append(valid)
        on, off, predictions, support = map(np.asarray, (on, off, predictions, support))
        outside = np.ones(len(spec.time), dtype=bool)
        for core_start, core_end in exclusions:
            outside &= (spec.time < core_start - settings.core_guard_s) | (spec.time > core_end + settings.core_guard_s)
        common = outside & np.logical_and.reduce(support)
        evidence.update(fixed_context_samples=int(outside.sum()), common_samples=int(common.sum()),
                        common_seconds=float(common.sum() * settings.hop_s),
                        common_fraction=float(common.sum() / outside.sum()) if outside.any() else 0.0,
                        own_supported_samples={modes[i]["mode_id"]: int((support[k] & outside).sum())
                                               for k, i in enumerate(active)})
        if output is not None:
            array_path = output / f"event-{event_index+1:04d}.npz"
            np.savez_compressed(array_path, time_s=spec.time, frequency_hz=spec.frequency,
                                contrast=spec.contrast, predictions_hz=predictions,
                                on_curve=on, sidebands=off, excluded_core_mask=~outside,
                                common_validation_mask=common, mode_ids=[modes[i]["mode_id"] for i in active])
            evidence["array_artifact"] = {"path": array_path.name, "sha256": _file_hash(array_path)}
        if common.sum() < settings.min_common_samples:
            evidence["reason"] = "insufficient_common_context"
            continue
        times = spec.time[common]
        delta = on[:, common] - off[:, common]
        means[event_index] = delta.mean(axis=1)
        pre, post = times < event["start_s"], times > event["end_s"]
        evidence.update(status="compared", common_extent_s=[float(times[0]), float(times[-1])],
                        pre_samples=int(pre.sum()), post_samples=int(post.sum()))
        for k, index in enumerate(active):
            evidence["scores"].append({"mode_id": modes[index]["mode_id"],
                "on_curve_mean": float(on[k, common].mean()), "sideband_mean": float(off[k, common].mean()),
                "contrast_excess_mean": float(means[event_index, k]),
                "pre_core_excess": float(delta[k, pre].mean()) if pre.any() else None,
                "post_core_excess": float(delta[k, post].mean()) if post.any() else None})
        bootstraps.append(_bootstrap(delta, times, settings, rng))
        if output is not None:
            np.savetxt(output / f"event-{event_index+1:04d}-validation.csv",
                       np.column_stack((times, delta.T)), delimiter=",", comments="",
                       header="time_s," + ",".join(modes[i]["mode_id"] for i in active))
    complete_columns = np.isfinite(means).all(axis=0)
    if not complete_columns.all():
        for index in active:
            modes[index]["status"] = "unsupported"
            modes[index]["limitations"].append("not_every_supported_event_had_comparable_context")
        return finish()
    scores = means.mean(axis=0)
    resampled = np.mean(bootstraps, axis=0)
    order = np.argsort(-scores, kind="stable")
    winner = int(order[0])
    for rank, k in enumerate(order, 1):
        index = active[k]
        difference = resampled[:, winner] - resampled[:, k]
        modes[index].update(status="compared", context_contrast_excess=float(scores[k]))
        report["ranking"].append({"rank": rank, "mode_id": modes[index]["mode_id"],
            "input_index": index, "context_contrast_excess": float(scores[k]),
            "winner_minus_mode": float(scores[winner] - scores[k]),
            "descriptive_paired_block_interval_95": np.quantile(difference, [0.025, 0.975]).tolist()})
    report["all_modes_compared"] = len(active) == len(candidates)
    report["status"] = "compared" if report["all_modes_compared"] else "inconclusive"
    return finish()
