"""Measured spectral scoring for a single, explicitly scoped association.

Scores compare hypotheses explaining the same event groups; this module does
not rank different subsets, account for omitted candidates, or decide location.
"""
import math

import numpy as np

from .audio import spectrogram
from .geometry import AcousticSupportError
from .search import event_score


def measure_spectral_event(recording, event, *, expansion_s=120.0, max_stft_bins=24_000_000):
    """Compute one expanded real-audio spectrum with an explicit work bound.

    The expansion and band follow the existing context protocol. Process one
    event at a time: callers must bound storage if retaining multiple spectra.
    Times remain relative to decoded sample zero. No event or flight is chosen
    from ground truth.
    """
    sr = recording.metadata["sample_rate_hz"]
    duration = recording.metadata["duration_s"]
    if type(sr) is not int or sr <= 0 or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid decoded recording metadata")
    if not math.isfinite(expansion_s) or expansion_s < 0 or type(max_stft_bins) is not int or max_stft_bins < 1:
        raise ValueError("Invalid spectral expansion or work limit")
    start = max(0.0, event["start_s"] - expansion_s)
    end = min(duration, event["end_s"] + expansion_s)
    band = (max(40.0, event["band_hz"][0] * 0.5), min(1600.0, sr / 2, event["band_hz"][1] * 2))
    first, last = round(start * sr), round(end * sr)
    n, hop = 2 * sr, sr // 4
    if hop < 1 or last - first < n or band[0] >= band[1]:
        raise ValueError("Insufficient recording or frequency support for spectrum")
    frames = 1 + (last - first - n) // hop
    if (2 * n + 1) * frames > max_stft_bins:
        raise ValueError("Spectrogram work limit exceeded")
    samples = np.memmap(recording.samples_path, dtype="<f4", mode="r")
    if abs(len(samples) / sr - duration) > 1 / sr or last > len(samples):
        raise ValueError("Decoded audio length differs from metadata")
    audio = np.asarray(samples[first:last])
    if not np.isfinite(audio).all():
        raise ValueError("Decoded audio contains nonfinite samples")
    return spectrogram(audio, sr, band, start=first / sr, window_s=2.0, hop_s=0.25)


def score_spectral_association(event_indices, flight_ids, events, spectra, tracks, observer,
                               recording_start_bounds_s, *, time_step_s=0.5,
                               max_clock_trials=2000, max_spectral_samples=100_000_000, c=343.0):
    """Score one association across a shared recording-start grid.

    Each selected group receives one flight, one frequency sweep and exactly the
    same start time. Unsupported clock trials remain unknown; scores from other
    group subsets are not comparable without an independently defined policy.
    """
    indices = list(event_indices)
    if (not indices or indices != sorted(set(indices)) or len(indices) != len(flight_ids)
            or any(type(i) is not int or i < 0 or i >= len(events) or i >= len(spectra) for i in indices)):
        raise ValueError("Need ordered unique event indices and one flight per group")
    if len(recording_start_bounds_s) != 2:
        raise ValueError("Need two recording-start bounds")
    lo, hi = recording_start_bounds_s
    if (not all(math.isfinite(v) for v in (lo, hi, time_step_s, c)) or lo > hi
            or time_step_s <= 0 or c <= 0 or type(max_clock_trials) is not int or max_clock_trials < 1
            or type(max_spectral_samples) is not int or max_spectral_samples < 1):
        raise ValueError("Invalid recording-start grid or work limit")
    count = 1 if lo == hi else math.ceil((hi - lo) / time_step_s) + 1
    result = {"score_kind": "spectral_contrast_sum", "event_indices": indices,
              "flight_ids": list(flight_ids), "recording_start_bounds_s": [lo, hi],
              "evaluated_trials": 0, "unknown_trials": 0, "clock_grid_complete": False,
              "status": "work_limit" if count > max_clock_trials else "unavailable"}
    if count > max_clock_trials:
        return result
    per_clock = 0
    for index in indices:
        spectrum = spectra[index]
        if spectrum is None:
            continue
        bounds = events[index]["f0_range_hz"]
        step = events[index].get("frequency_step_hz", 0.2)
        if (len(bounds) != 2 or not all(math.isfinite(v) for v in (*bounds, step))
                or not 0 < bounds[0] <= bounds[1] or step <= 0):
            raise ValueError("Invalid spectral frequency grid")
        bins = max(3, math.ceil((bounds[1] - bounds[0]) / step) + 1)
        per_clock += bins * len(spectrum.time)
    result["planned_spectral_samples"] = count * per_clock
    if result["planned_spectral_samples"] > max_spectral_samples:
        result["status"] = "work_limit"
        return result
    for start in np.linspace(lo, hi, count):
        scores, frequencies = [], []
        for index, flight_id in zip(indices, flight_ids):
            track = tracks.get(flight_id)
            if track is None or spectra[index] is None:
                break
            event = events[index]
            try:
                score, frequency = event_score(track, observer, spectra[index], None, None, float(start),
                                               event["f0_range_hz"], "brightness", c,
                                               event.get("frequency_step_hz", 0.2))
            except AcousticSupportError:
                break
            if not math.isfinite(score) or not math.isfinite(frequency):
                break
            scores.append(score)
            frequencies.append(frequency)
        if len(scores) != len(indices):
            result["unknown_trials"] += 1
            continue
        result["evaluated_trials"] += 1
        total = float(sum(scores))
        if "score" not in result or total > result["score"]:
            result.update(score=total, event_scores=scores, f0_hz=frequencies,
                          recording_start_time_s=float(start), status="scored")
    result["clock_grid_complete"] = result["unknown_trials"] == 0
    return result
