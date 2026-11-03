"""Measured spectral-contrast scoring with one shared recording clock."""
import math

import numpy as np

from .audio import spectrogram
from .geometry import AcousticSupportError, ecef
from .search import event_score


def prepare_spectral_measurements(recording, events, *, padding_s=60.0):
    """Read bounded real-audio windows around every prepared independent group.

    The same windows/bands are used for every candidate. Harmonics remain one
    prepared group; neither the observer location nor flight IDs select audio.
    """
    if not math.isfinite(padding_s) or padding_s < 0:
        raise ValueError("Spectral padding must be finite and nonnegative")
    sr = recording.metadata["sample_rate_hz"]
    if recording.metadata["channels"] != 1:
        raise ValueError("Use the mono decoded intake cache")
    duration = recording.metadata["duration_s"]
    spectra = []
    with recording.samples_path.open("rb", buffering=0) as source:
        for event in events:
            first = max(0, int(math.floor((event["start_s"] - padding_s) * sr)))
            last = min(int(duration * sr), int(math.ceil((event["end_s"] + padding_s) * sr)))
            source.seek(first * 4)
            samples = np.fromfile(source, dtype="<f4", count=max(0, last - first))
            low, high = event["band_hz"]
            band = (max(1.0, low * 0.75), min(sr / 2, high * 1.25))
            spectra.append(spectrogram(samples, sr, band, start=first / sr))
    return spectra


def score_locked_spectra(candidate, tracks, events, spectra, *,
                         recording_start_window_s=None, time_sweep_s=5.0,
                         time_step_s=0.5, frequency_step_hz=0.2, c=343.0):
    """Optimize constant emitted frequencies and ONE shared timing correction.

    Each aircraft uses its full emission-time trajectory. Moving the common
    clock moves every event together; no event receives its own time shift or
    source-frequency drift. Scores are contrast units, not ridge losses or
    probabilities. Scoring a retained shortlist does not bound unvisited modes.

    A null score means no clock trial had complete spectral support. Unknown
    trials remain explicit even when another trial yields a finite best fit.
    """
    indices = candidate.get("event_indices", list(range(len(events))))
    if (not indices or indices != sorted(set(indices)) or
            any(i < 0 or i >= len(events) for i in indices) or
            len(indices) != len(candidate["flight_ids"]) or len(events) != len(spectra)):
        raise ValueError("Need one flight and spectrum per selected independent group")
    if (not all(math.isfinite(v) for v in (time_sweep_s, time_step_s, frequency_step_hz, c))
            or time_sweep_s < 0 or min(time_step_s, frequency_step_hz, c) <= 0):
        raise ValueError("Need a nonnegative sweep and positive finite steps/sound speed")
    anchor = candidate["recording_start_time_s"]
    lower, upper = anchor - time_sweep_s, anchor + time_sweep_s
    if recording_start_window_s is not None:
        lo, hi = recording_start_window_s
        if not np.isfinite([lo, hi]).all() or lo > hi:
            raise ValueError("Recording-start window must be finite and ordered")
        lower, upper = max(lower, lo), min(upper, hi)
    if lower > upper:
        raise ValueError("Spectral clock sweep does not intersect the stated recording time")
    clocks = np.linspace(lower, upper, int(math.ceil((upper - lower) / time_step_s)) + 1)
    observer = ecef(candidate["lat"], candidate["lon"], candidate["elev_m"])
    best = {"score": None}
    evaluated, unknown, reasons = 0, 0, set()
    for clock in clocks:
        scores, frequencies = [], []
        try:
            for index, flight in zip(indices, candidate["flight_ids"]):
                score, frequency = event_score(tracks[flight], observer, spectra[index], None, None,
                    float(clock), events[index]["f0_range_hz"], "brightness", c, frequency_step_hz)
                scores.append(score)
                frequencies.append(frequency)
        except AcousticSupportError as error:
            unknown += 1
            reasons.add(str(error))
            continue
        if not np.isfinite(scores).all():
            unknown += 1
            reasons.add("incomplete_spectral_or_trajectory_support")
            continue
        evaluated += 1
        total = float(sum(scores))
        if best["score"] is None or total > best["score"]:
            best = {"score": total, "event_scores": scores, "f0_hz": frequencies,
                    "recording_start_time_s": float(clock), "time_adjustment_s": float(clock - anchor)}
    return dict(best, score_kind="summed_spectral_contrast", event_indices=list(indices),
                spectral_assessment={"complete": unknown == 0, "evaluated_trials": evaluated,
                                     "unknown_trials": unknown, "reasons": sorted(reasons)})
