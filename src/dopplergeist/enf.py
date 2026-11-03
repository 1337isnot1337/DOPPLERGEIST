"""Screen audio for sustained tones near electrical-network harmonics.

These measurements are not an ENF identification or timestamp. A tone can come
from equipment, interference, or other sound; only a defensible reference match
can establish an ENF clock candidate.
"""
import math

import numpy as np
from scipy.signal.windows import hann


def scan_enf_tones(samples, sample_rate, *, nominals=(50.0, 60.0), harmonics=(1, 2, 3),
                   frame_s=4.0, hop_s=1.0):
    """Return per-frame peak frequency and local prominence near ENF harmonics.

    The output is deliberately a tone screen. It does not claim that a peak is
    caused by the grid or that it can recover a timestamp.
    """
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
        raise ValueError("ENF screening requires a finite, nonempty mono signal")
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if not math.isfinite(frame_s) or not math.isfinite(hop_s) or frame_s <= 0 or hop_s <= 0:
        raise ValueError("frame_s and hop_s must be positive and finite")
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in nominals):
        raise ValueError("nominal frequencies must be positive and finite")
    if any(type(value) is not int or value < 1 for value in harmonics):
        raise ValueError("harmonics must be positive integers")

    frame = int(round(frame_s * sample_rate))
    hop = int(round(hop_s * sample_rate))
    if frame < 8 or hop < 1:
        raise ValueError("Frame and hop durations are too short for this sample rate")
    if len(samples) < frame:
        return []
    nfft = 4 * frame
    frequency = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
    window = hann(frame, sym=False)
    specs = []
    for nominal in nominals:
        for harmonic in harmonics:
            center = float(nominal) * harmonic
            if center + 0.75 >= sample_rate / 2:
                continue
            search = np.flatnonzero(np.abs(frequency - center) <= 0.75)
            side = np.flatnonzero((np.abs(frequency - center) <= 0.75) &
                                  (np.abs(frequency - center) >= 0.18))
            if len(search) < 3 or len(side) < 3:
                continue
            specs.append((float(nominal), harmonic, center, search, side))

    if not specs:
        return []

    rows = []
    tiny = np.finfo(float).tiny
    for first in range(0, len(samples) - frame + 1, hop):
        segment = samples[first:first + frame]
        magnitude = np.abs(np.fft.rfft(segment * window, n=nfft))
        offset = (first + frame / 2) / sample_rate
        for nominal, harmonic, center, search, side in specs:
            peak = int(search[np.argmax(magnitude[search])])
            left, middle, right = np.log(np.maximum(magnitude[peak - 1:peak + 2], tiny))
            denominator = left - 2 * middle + right
            delta = (0.5 * (left - right) / denominator
                     if len((left, middle, right)) == 3 and abs(denominator) > 1e-12 else 0.0)
            delta = float(np.clip(delta, -0.5, 0.5))
            local_floor = float(np.median(magnitude[side]))
            prominence = 20 * math.log10(max(float(magnitude[peak]), tiny) /
                                         max(local_floor, tiny))
            rows.append({"offset_s": float(offset), "nominal_hz": nominal,
                         "harmonic": harmonic, "target_hz": center,
                         "frequency_hz": float((peak + delta) * (sample_rate / nfft)),
                         "local_prominence_db": float(prominence)})
    return rows


def summarize_enf_tones(rows, *, prominence_threshold_db=10.0):
    """Summarize tone candidates without labeling them as ENF."""
    if not math.isfinite(prominence_threshold_db):
        raise ValueError("prominence threshold must be finite")
    groups = {}
    for row in rows:
        groups.setdefault((row["nominal_hz"], row["harmonic"]), []).append(row)
    result = []
    for (nominal, harmonic), values in sorted(groups.items()):
        prominence = np.asarray([row["local_prominence_db"] for row in values])
        frequency = np.asarray([row["frequency_hz"] for row in values])
        present = prominence >= prominence_threshold_db
        estimates = frequency[present]
        result.append({
            "nominal_hz": float(nominal), "harmonic": int(harmonic),
            "target_hz": float(nominal * harmonic), "frames": int(len(values)),
            "prominence_threshold_db": float(prominence_threshold_db),
            "prominent_frame_fraction": float(np.mean(present)),
            "median_local_prominence_db": float(np.median(prominence)),
            "median_peak_frequency_hz": float(np.median(estimates)) if len(estimates) else None,
            "peak_frequency_std_hz": float(np.std(estimates)) if len(estimates) else None,
            "peak_frequency_p05_hz": float(np.percentile(estimates, 5)) if len(estimates) else None,
            "peak_frequency_p95_hz": float(np.percentile(estimates, 95)) if len(estimates) else None,
            "interpretation": "mains-band tone candidate; ENF/reference match unverified",
        })
    return result
