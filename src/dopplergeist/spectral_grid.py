"""Bounded frequency batches for the existing spectrogram-contrast score."""

import numpy as np


def best_frequency(spectrum, times, factor, f0_bounds, frequency_step=0.2,
                   *, batch_size=64):
    """Sweep constant emitted frequencies without a full grid-by-time matrix.

    ``factor`` is the physical Doppler factor at each receiver time. The caller
    supplies it from the same emission-time model and shared recording clock as
    the other events. This function does not fit a clock or source drift.

    Keep the original frequency grid, interpolation, 95 percent support rule,
    missing-bin penalty, per-curve reduction and first-maximum tie rule. At most
    ``batch_size`` curves are sampled together; temporary matrix storage scales
    with that batch and the existing number of observed time bins.
    """
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("Frequency batch size must be a positive integer")
    times, factor = np.asarray(times), np.asarray(factor)
    if times.ndim != 1 or factor.shape != times.shape or not len(times):
        raise ValueError("Need matching nonempty time and Doppler-factor vectors")
    if (len(f0_bounds) != 2 or not np.isfinite(f0_bounds).all()
            or not 0 < f0_bounds[0] <= f0_bounds[1]
            or not np.isfinite(frequency_step) or frequency_step <= 0):
        raise ValueError("Need positive finite source frequencies and frequency step")
    frequencies = np.linspace(*f0_bounds,
        max(3, int(np.ceil((f0_bounds[1] - f0_bounds[0]) / frequency_step)) + 1))
    best_score, best_source_frequency = -np.inf, frequencies[0]
    for first in range(0, len(frequencies), batch_size):
        trial = frequencies[first:first + batch_size]
        predicted = trial[:, None] * factor[None, :]
        contrast = spectrum.sample(times[None, :], predicted)
        scores = np.where(np.mean(np.isfinite(contrast), axis=1) >= 0.95,
            np.mean(np.nan_to_num(contrast, nan=-4.0), axis=1), -np.inf)
        winner = np.argmax(scores)
        # Strict improvement preserves the earliest frequency across batch ties.
        if scores[winner] > best_score:
            best_score, best_source_frequency = scores[winner], trial[winner]
    return float(best_score), float(best_source_frequency)
