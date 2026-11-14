# Curved-path recurrence on public recorded spectra

This changes computation, not the detector or scientific acceptance rules.
The existing recurrence is retained as `_curved_forward_reference` for direct
comparison. The optimized implementation uses contiguous frequency scans,
reuses two float32 state buffers, and separates each frame's maximum reduction
from its independent frequency updates. It preserves predecessor comparison
order (-1, 0, +1), subtraction order, restart semantics and the original t/j/v
order for strict-maximum ties. The returned backpointer axes retain their
original meaning.

Invalid predecessor states are negative infinity internally rather than -1000.
Both are below the zero restart and cannot win any transition. Invalid states
are excluded from the frame maximum; their backpointer remains 127. No fastmath,
parallel reduction, detector threshold or harmonic-grouping change is used.

## Measured outcomes

The fixed public population is the first 120 seconds of each of the six original
one-hour AeroSonicDB environment recordings, plus the complete lexicographically
first publisher-confirmed non-jet file, `7C019D_2023-05-03_12-49-25_0_1.wav`
(60 seconds). No source was dropped based on results. Source: Blake Downward and
Jon Nordby, [AeroSonicDB YPAD-0523 v1.1.2](https://zenodo.org/records/10215080),
CC BY-NC 4.0. Original audio remains outside Git; the small recorded-spectrum
fixture has its own attribution.

All three production spectral profiles are used: low band at 0.5/0.125-second
window/hop with 144 bins/octave, high band at 0.5/0.125 with 576 bins/octave,
and low band at 2.0/0.5 with 144 bins/octave. Input decoding is float32, matching
production intake. Each case applies up to 32 unchanged iterative extraction
masks, stopping below the existing score 25. JIT compilation is warmed on an
actual recorded submatrix. Reference/optimized execution order alternates.

All **186 paired extractions across 21 real-spectrum cases** preserved scores,
maximizing indices, every backpointer and complete backtracked paths exactly.
Aggregate measured kernel time changed **12.9953 -> 11.4602 seconds**, a
**1.134x speedup (11.8% less kernel time)**. Individual case ratios ranged from
1.006x to 1.221x. These are single alternating-order measurements, not confidence
bounds or whole-pipeline throughput estimates. An earlier implementation of the
same recurrence gained only 1.058x aggregate on these inputs; separating the
maximum reduction improved it. Complete per-case results are in
`real-spectrum-results.json`.

A complete production discovery replay on the same original 60-second non-jet
recording also matched exactly: **30 events in one group**, including all saved
ridges, settings, grouping and other discovery content. Only the private kernel
was replaced between arms. The one-shot elapsed times (8.03 and 7.61 seconds)
are retained in `complete-discovery-result.json`; they are a parity control,
not a reliable pipeline speed estimate.

The 63 focused checks use actual source-derived low/high spectra, including
one-bin/one-frame edges, narrow bands, float32/float64 inputs, production and
larger velocity ranges, and the public backtracking wrapper. They do not
synthesize recordings or tracks. No detection-recall, low-SNR or localization
improvement is claimed. Issue #341's scientific gates remain open.

## Replay

In the recorded environment: Python 3.14.6, NumPy 2.5.4, SciPy 1.18.1,
Numba 0.68.1; CPU median backend, one OpenBLAS/OMP thread. Compiler/JIT setup
and host load affect timings. Download the public archive as described in the
category experiment; do not supply private or request-only data.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src python scripts/benchmark_real_curved_dp.py prepare --data /path/to/public-data --output /path/to/new-inputs
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src python scripts/benchmark_real_curved_dp.py benchmark --inputs /path/to/new-inputs --output /path/to/new-results
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg PYTHONPATH=src python scripts/benchmark_real_curved_dp.py pipeline --source /path/to/public-data/audio/7C019D_2023-05-03_12-49-25_0_1.wav --output /path/to/new-discovery-comparison
PYTHONPATH=src python -m pytest -q tests/test_real_curved_dp.py
```
