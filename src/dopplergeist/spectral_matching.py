"""Compare retained physical modes against actual recorded spectrograms.

This is a spectral ranking, separate from ridge-fit scores and their retention
bounds. It does not decide whether a location is accepted.
"""
from collections import Counter
import math

import numpy as np

from .audio import spectrogram
from .geometry import AcousticSupportError, ecef
from .spectral_grid import best_frequency


SCORE_KIND = "sum_of_event_mean_spectral_contrast"


def _event_spectrum(samples, sample_rate, duration, event, expansion_s,
                    max_window_s, window_s, hop_s):
    start, end = float(event["start_s"]), float(event["end_s"])
    band = np.asarray(event["band_hz"], dtype=float)
    if (not np.isfinite([start, end]).all() or not 0 <= start < end <= duration
            or band.shape != (2,) or not np.isfinite(band).all()
            or not 0 < band[0] < band[1]):
        raise ValueError("Event window and frequency band must be finite and supported")
    start, end = max(0.0, start-expansion_s), min(duration, end+expansion_s)
    if end-start > max_window_s:
        raise ValueError("Spectral event window exceeds the declared work limit")
    band = [max(40.0, band[0]*0.5), min(1600.0, sample_rate/2, band[1]*2)]
    if band[0] >= band[1]:
        raise ValueError("Event has no supported spectral analysis band")
    first, last = round(start*sample_rate), round(end*sample_rate)
    # Match the existing research decoder's floating-point representation.
    audio = np.asarray(samples[first:last], dtype=float)
    if not np.isfinite(audio).all():
        raise ValueError("Decoded recording contains nonfinite event samples")
    spectrum = spectrogram(audio, sample_rate, band, start=first/sample_rate,
                           window_s=window_s, hop_s=hop_s)
    if len(spectrum.time) < 2 or len(spectrum.frequency) < 2:
        raise ValueError("Event has too few spectral bins for interpolation")
    return spectrum


def compare_spectral_modes(recording, candidates, tracks, events, *,
                           recording_start_window_s=None, time_sweep_s=5.0,
                           time_step_s=0.5, frequency_step_hz=0.2,
                           expansion_s=120.0, window_s=2.0, hop_s=0.25,
                           max_window_s=600.0, max_modes=1000,
                           max_event_clock_trials=50000,
                           max_curve_samples=1000000000, c=343.0):
    """Score every supplied mode's matched independent groups at one clock.

    ``recording`` is the existing IntakeRecording; ``events`` are the independent
    groups from prepare_events. Candidate event_indices map each flight to its
    group. Unmatched proposals stay unmatched. No event count is capped here.

    Each trial uses one shared recording clock and a constant emitted frequency
    per group, swept over that group's declared f0_range_hz. Spectra come from
    the real decoded cache, with fixed expanded windows/bands for all modes.
    Process one event's spectrum at a time to bound retained spectral storage.
    Callers must provide full tracks supporting those expanded time windows.
    This first comparison scores the reference-band curve of each group.

    The statistic adds per-event mean contrast, preserving event_score's current
    normalization. It is not the unnormalized sum of all time bins, a likelihood,
    or a ridge loss. It cannot reuse ridge-score pruning/confidence bounds.
    Location and event associations are conditional on the supplied modes.
    Reason counts describe event-clock failures; mode setup errors count once.
    """
    for name, value in (("time_step_s", time_step_s), ("frequency_step_hz", frequency_step_hz),
                        ("window_s", window_s), ("hop_s", hop_s),
                        ("max_window_s", max_window_s), ("c", c)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    if (not math.isfinite(time_sweep_s) or time_sweep_s < 0
            or not math.isfinite(expansion_s) or expansion_s < 0 or hop_s >= window_s):
        raise ValueError("Need nonnegative sweeps/expansion and hop below window")
    for value in (max_modes, max_event_clock_trials, max_curve_samples):
        if type(value) is not int or value <= 0:
            raise ValueError("Spectral work limits must be positive integers")
    clock_window = None
    if recording_start_window_s is not None:
        clock_window = np.asarray(recording_start_window_s, dtype=float)
        if (clock_window.shape != (2,) or not np.isfinite(clock_window).all()
                or clock_window[0] > clock_window[1]):
            raise ValueError("Recording clock window must be finite and increasing")
    groups = [event.get("harmonic_group_id") or event.get("event_id", str(i))
              for i, event in enumerate(events)]
    if not events or len(set(groups)) != len(groups):
        raise ValueError("Supply nonempty independent groups; harmonics count once")
    report = {"status": "inconclusive", "score_kind": SCORE_KIND,
        "location_decision": "not_evaluated", "candidate_mode_count": len(candidates),
        "prepared_group_count": len(events), "all_modes_compared": False,
        "settings": {"source_model": "constant_emitted_frequency",
            "shared_clock": True, "time_sweep_s": time_sweep_s,
            "time_step_s": time_step_s, "frequency_step_hz": frequency_step_hz,
            "recording_start_window_s": None if clock_window is None else clock_window.tolist(),
            "expansion_s": expansion_s, "window_s": window_s, "hop_s": hop_s,
            "band_rule": "half_to_twice_group_band_clipped_to_40_1600_hz_and_Nyquist",
            "max_window_s": max_window_s, "max_modes": max_modes,
            "max_event_clock_trials": max_event_clock_trials,
            "max_curve_samples": max_curve_samples, "sound_speed_mps": c,
            "required_trajectory_support_fraction": 1.0,
            "minimum_spectral_support_fraction": 0.95, "missing_bin_contrast": -4.0},
        "work": {"event_clock_trials": 0, "curve_samples": 0, "budget_exhausted": False},
        "events": [], "modes": [], "ranked": [],
        "limitations": [
            "Ranks are conditional on retained locations, associations, clock grids and spectral windows.",
            "Unmatched proposals are not established absent flights.",
            "One reference-band curve is scored per group; additional harmonic curves are not jointly scored here.",
            "The fixed spectral band and 95 percent time-bin support rule define scorable frequency curves.",
            "Ridge retention bounds do not bound this spectral statistic; location acceptance is not evaluated."]}
    if len(candidates) > max_modes:
        report["reason"] = "mode_budget_exceeded"
        report["work"]["budget_exhausted"] = True
        return report

    sr, duration = recording.metadata["sample_rate_hz"], recording.metadata["duration_s"]
    if type(sr) is not int or sr <= 0 or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid decoded recording metadata")
    samples = np.memmap(recording.samples_path, dtype="<f4", mode="r")
    if abs(len(samples)/sr-duration) > 1/sr:
        raise ValueError("Decoded sample cache differs from recording duration")
    work = report["work"]
    states, allocated_trials = [], 0
    for index, row in enumerate(candidates):
        mode = {"input_index": index, "input_mode_id": row.get("mode_id"),
                "status": "unsupported", "reason_counts": {}}
        report["modes"].append(mode)
        try:
            indices = list(row.get("event_indices", range(len(events))))
            if (not indices or indices != sorted(set(indices))
                    or any(type(i) is not int or not 0 <= i < len(events) for i in indices)
                    or len(row["flight_ids"]) != len(indices)):
                raise ValueError("Invalid event-to-flight mapping")
            selected = [tracks[identifier] for identifier in row["flight_ids"]]
            observer = ecef(row["lat"], row["lon"], row["elev_m"])
            clock = float(row["recording_start_time_s"])
            if observer.shape != (3,) or not np.isfinite(observer).all() or not math.isfinite(clock):
                raise ValueError("Nonfinite physical candidate")
            lo, hi = clock-time_sweep_s, clock+time_sweep_s
            if clock_window is not None:
                lo, hi = max(lo, clock_window[0]), min(hi, clock_window[1])
            if not np.isfinite([lo, hi]).all() or lo > hi:
                raise ValueError("Candidate clock is outside the declared window")
            intervals = (hi-lo)/time_step_s
            if (not math.isfinite(intervals) or intervals > max_event_clock_trials
                    or allocated_trials+len(indices)*(1 if lo == hi else math.ceil(intervals)+1)
                    > max_event_clock_trials):
                mode.update(status="not_evaluated", complete=False,
                            reason_counts={"event_clock_budget_exceeded": 1})
                work["budget_exhausted"] = True
                continue
            clocks = (np.array([lo]) if lo == hi else
                      np.linspace(lo, hi, math.ceil(intervals)+1))
            allocated_trials += len(indices)*len(clocks)
            state = {"mode": mode, "row": row, "indices": indices,
                "slots": {group: slot for slot, group in enumerate(indices)},
                "tracks": selected, "observer": observer, "clocks": clocks,
                "scores": np.full((len(indices), len(clocks)), np.nan),
                "frequencies": np.full((len(indices), len(clocks)), np.nan),
                "attempted": np.zeros((len(indices), len(clocks)), dtype=bool),
                "reasons": Counter()}
            states.append(state)
            mode.update(event_indices=indices, flight_ids=list(row["flight_ids"]),
                        unmatched_event_indices=[i for i in range(len(events)) if i not in indices],
                        scheduled_clock_trials=len(clocks))
        except (ValueError, TypeError, KeyError) as error:
            mode["reason_counts"] = {f"invalid_or_unavailable_mode: {error}": 1}

    for event_index, event in enumerate(events):
        active = [state for state in states if event_index in state["slots"]]
        if not active:
            continue
        if work["budget_exhausted"]:
            break
        detail = {"event_index": event_index, "group_id": groups[event_index], "status": "unsupported"}
        report["events"].append(detail)
        try:
            bounds = event["f0_range_hz"]
            if (len(bounds) != 2 or not np.isfinite(bounds).all()
                    or not 0 < bounds[0] <= bounds[1]):
                raise ValueError("Invalid source-frequency bounds")
            frequency_intervals = (bounds[1]-bounds[0])/frequency_step_hz
            if (not math.isfinite(frequency_intervals)
                    or max(3, math.ceil(frequency_intervals)+1) > max_curve_samples):
                detail["reason"] = "frequency_grid_budget_exceeded"
                work["budget_exhausted"] = True
                break
            frequency_count = max(3, math.ceil(frequency_intervals)+1)
            spectrum = _event_spectrum(samples, sr, duration, event, expansion_s,
                                       max_window_s, window_s, hop_s)
        except (ValueError, TypeError, KeyError) as error:
            detail["reason"] = str(error)
            for state in active:
                slot = state["slots"][event_index]
                state["attempted"][slot] = True
                state["reasons"][f"spectral_support_unavailable: {error}"] += len(state["clocks"])
            continue
        cells = frequency_count*len(spectrum.time)
        detail.update(status="prepared", time_bins=len(spectrum.time),
            time_extent_s=[float(spectrum.time[0]), float(spectrum.time[-1])],
            band_hz=[float(spectrum.frequency[0]), float(spectrum.frequency[-1])],
            f0_range_hz=list(bounds), frequency_trials=frequency_count)
        for state in active:
            slot = state["slots"][event_index]
            for trial, clock in enumerate(state["clocks"]):
                if (work["event_clock_trials"] >= max_event_clock_trials
                        or work["curve_samples"]+cells > max_curve_samples):
                    work["budget_exhausted"] = True
                    break
                work["event_clock_trials"] += 1
                state["attempted"][slot, trial] = True
                try:
                    factor, _, _ = state["tracks"][slot].acoustic(clock+spectrum.time,
                                                                  state["observer"], c)
                except AcousticSupportError as error:
                    state["reasons"][error.reason] += 1
                    continue
                if not np.isfinite(factor).all() or (factor <= 0).any():
                    state["reasons"]["incomplete_trajectory_support"] += 1
                    continue
                work["curve_samples"] += cells
                score, frequency = best_frequency(spectrum, spectrum.time, factor, bounds,
                                                  frequency_step_hz)
                if not np.isfinite([score, frequency]).all():
                    state["reasons"]["no_supported_spectral_curve"] += 1
                    continue
                state["scores"][slot, trial] = score
                state["frequencies"][slot, trial] = frequency
            if work["budget_exhausted"]:
                break
        del spectrum

    for state in states:
        mode = state["mode"]
        unattempted = int((~state["attempted"]).sum())
        if unattempted:
            state["reasons"]["work_budget_exhausted"] += unattempted
        valid = np.isfinite(state["scores"]).all(axis=0)
        mode.update(evaluated_clock_trials=int(valid.sum()),
                    unknown_clock_trials=int((~valid).sum()),
                    complete=bool(valid.all()), reason_counts=dict(state["reasons"]))
        if not valid.any():
            continue
        trials = np.flatnonzero(valid)
        scores = state["scores"][:, valid].sum(axis=0)
        best = int(np.argmax(scores))
        trial = int(trials[best])
        mode["status"] = "compared" if mode["complete"] else "partial"
        row = state["row"]
        ranked = {key: row[key] for key in ("lat", "lon", "elev_m")}
        ranked.update(input_index=mode["input_index"], input_mode_id=mode["input_mode_id"],
            event_indices=state["indices"], flight_ids=mode["flight_ids"],
            score_kind=SCORE_KIND, score=float(scores[best]),
            event_scores=state["scores"][:, trial].tolist(),
            f0_hz=state["frequencies"][:, trial].tolist(),
            recording_start_time_s=float(state["clocks"][trial]),
            complete=mode["complete"], unknown_clock_trials=mode["unknown_clock_trials"])
        report["ranked"].append(ranked)
    report["ranked"].sort(key=lambda row: (-row["score"], row["input_index"]))
    report["all_modes_compared"] = bool(candidates and
        all(mode.get("complete") is True for mode in report["modes"]))
    if report["all_modes_compared"]:
        report["status"] = "compared"
    return report
