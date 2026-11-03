# Worker 3 matching evidence

These are manually configured **regional development** replays. They preserve
the original source-informed event windows, bands, speed/slant constraints and
geographic bounds. The faint case uses a clock derived from the two-event fit.
The public coordinate is rounded and its physical accuracy is unestablished.
None of these outcomes establishes automatic nationwide real-audio accuracy.

| Case | Original point error | Robust point error | Winning association before/after |
| --- | ---: | ---: | --- |
| Two events | 43.8585 m | 116.1647 m | `a1dfeb:1` + `ace391:3`, rank 1 in both |
| Faint | 357.4687 m | 537.5662 m | `a38237`, rank 1 in both |

**Both point estimates regress.** Robust residual improvement is not evidence
of more accurate localization. No truth-informed parameter retuning was applied.
Raw brightness, RMSE and robust losses have different scales and are not
probabilities. Full flight-combination rankings, exact errors and source/run
hashes are in [summary.json](summary.json); each complete report is retained.
Evaluation coordinates were joined after the searches completed.

Original-mode code: `b66411e`. Optimized robust-mode code: `41992be`. The exact
box-constrained source solver reproduces the earlier robust two-event location,
clock and score exactly; diagnostic differences are about 1e-16. This makes the
solver optimization separate from the observed model/scoring regression.

The actual declared two-event perturbations span **606.954 m** and reach a local
refinement boundary. See [the profile receipt](common-height-profile-41992be.json).
That older receipt tests common height, frequency/tilt, clock, sound speed and a
constant-source alternative. It predates PR #41's independent flight-height and
datum gates and must not be treated as full altitude-datum acceptance. Even this
older envelope fails the 100 m precision requirement. Failed optimization or
missing provenance must keep the current envelope incomplete.

Commands actually run, using the shared existing environment with this
worktree's source selected by `PYTHONPATH=src`:

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  /home/cinna/aircraft-audio-geolocation/.venv/bin/python \
  scripts/benchmark_matching.py \
  --source-root /home/cinna/aircraft-audio-geolocation/data/source \
  --output results/matching-development-20261102-b

PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  /home/cinna/aircraft-audio-geolocation/.venv/bin/python \
  scripts/benchmark_matching.py --robust-only \
  --source-root /home/cinna/aircraft-audio-geolocation/data/source \
  --output results/matching-development-41992be-20261102-c

PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  /home/cinna/aircraft-audio-geolocation/.venv/bin/python \
  scripts/profile_matching_development.py \
  --run /home/cinna/dopplergeist-w3-matching/results/matching-development-20261102-b/two-events-robust_ridge/search \
  --output results/matching-profile-two-events-20261102-b
```

The first command completed both baselines and the first robust case; its slow
last robust case was interrupted and preserved. The second completed both
robust cases with the exact faster solver; it writes its own post-search
evaluation summary. The regional profile helper caches the declared raster
grids unchanged: cached versus original sampling agreed exactly at 100 fixed
random regional points. It does not replace the bounded national terrain path.
The full local output paths and interrupted attempts remain in summary.json.

[Hermes comparison](hermes-comparison.json) pins public MIT reference
`mojomast/hermes-aircraft-doppler-geolocation` at
`2c3ed20577bcce29058d73422dd4f85392d04c24`. No source was copied. Its constant-pass
interpolation agrees with the closed form to <=0.003013 Hz for the four tested
70/150 m/s cases; the tested 250 m/s cases show larger finite-grid/clamping
differences. A 5-of-100-supported-samples control scores zero RMS there, while
our complete-support scorer rejects it. The upstream scripts remain a physics
reference, not automatic real/national validation.

Current implementation/verification is documented in `docs/MATCHING.md` and
PRs #16, #21, #30, #34 and #41. The frozen historical results remain unchanged.

The older replay PNGs drew a constant-source approximation when the robust fit
included drift. The separately rendered [corrected overlay](corrected-overlay-event-2.png)
uses the actual frozen emission-time model. Commit `18ff60a` adds its fitted
emission reference/span and prediction helper. Its [receipt](corrected-overlay-receipt.json)
confirms the point/ranking is unchanged and the recomputed fit score agrees to
numerical precision; [source hashes](corrected-overlay-source.json) identify the
exact renderer/model. The historical images have not been replaced.
Independent real holdouts, full uncertainty/alternative assessment and the
end-to-end 100 m real national acceptance check remain unmet.
