# Frozen spectral context diagnostics

`context_validation.validate_context` implements the physical verifier's fixed
development protocol from `evidence/verification/physical-20261103/` at physical
verifier revision `6783984eff2c834e923c8d046bec8fb47fae4190`. The earlier experiment showed that weak audio
outside automatically detected ridge cores can discriminate otherwise competitive
distant synthetic associations. This consumer does not establish a new location
success or change the job decision.

The public diagnostic boundary is:

```python
validate_context(recording, candidates, tracks, events, measurements,
                 detected_events=None, output_dir=None, settings=None)
```

`recording` supplies the existing disk-backed `samples_path` and validated decoded
metadata. `candidates` are frozen internal search/refinement rows; `tracks` maps
their flight IDs to original whole trajectories. `events` and `measurements` are
the complete supported independent groups and original prepared measurements.
Pass unconfirmed raw acoustic proposals too through `detected_events`, so their
fitted cores are excluded. There is no default two/three-event cap.

Each mode must explain every supplied supported group. Missing explanations,
trajectories or frozen source parameters remain explicit unsupported competitors;
they cannot disappear from a claimed complete comparison. Harmonics/fragments
must already count once through `matching.prepare_events`. Every retained spatial
and clock row is preserved, even when several rows use the same aircraft pair.

The default protocol is fixed before scoring:

- Expand every detected event by 120 s on each side, clipped to the recording.
- Analyze `[0.5 * low, 2 * high]`, clipped to 40–1600 Hz and the Nyquist limit,
  with a 2 s spectral window and 0.25 s hop.
- Exclude the union of all fitted cores plus a 2 s guard.
- Predict the physical curve using each mode's frozen location, shared recording
  clock, fitted source frequency and linear emission-time drift. No context refit
  is performed. The source anchor comes from the candidate diagnostic when supplied,
  otherwise from the exact min/max midpoint of its original supported core
  emission times, matching the published core fitter. Curves use W3's public
  `matching.predict_fitted_ridge` helper rather than a separate source model.
- Use identical bins where every evaluable mode has trajectory and spectral
  support, including offsets of −10, −5, +5 and +10 Hz. Never extrapolate a track or
  clamp unsupported frequencies into the analysis band. Report lost support.
- Subtract mean sideband contrast from predicted-curve contrast, then average
  equally over every supplied supported independent event.
- Retain 2,000 paired 10 s block resamples with seed 7231 as descriptive margin
  intervals. These are not calibrated location confidence or coverage probability.

`ContextSettings` makes these settings explicit. A 600 s maximum context window
and 1,000-mode budget bound work; exhaustion is reported instead of silently
truncating modes or events. Bootstrap gathering uses batches of 64. Spectra are
processed one event at a time. The 40-common-sample floor matches the development
protocol; common support remains conditional on the retained candidate set.

The returned contrast statistic is `frozen_context_contrast_excess`. It remains
separate from Hz residuals and dimensionless association support. `status=compared`
means a diagnostic comparison was possible; `location_decision=not_evaluated`
always remains. Missing competitors make `all_modes_compared=false`. W4 owns
decision threshold/calibration semantics; W3/W5 own any final orchestration hook.

For a completed automatic job with local index paths still available:

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_job_context.py \
  --job results/JOB --output results/context-new
```

The command never rewrites the job. It loads all retained rows, bounds local
trajectory acquisition, preserves missing modes, and accepts no truth coordinates,
true IDs, event windows or frequency bands. It deliberately supplies all prepared
groups; an automatic producer must distinguish supported independent events from
unconfirmed proposals before any context result participates in a decision.

With an output directory, per-event NPZ/CSV evidence and an input/code-hashed report
are saved. Use a new directory. Large spectra stay out of Git; commit the readable
summary and hashes with the exact development scope. Benchmark location errors,
when separately evaluated, should now be reported at 100/500/1000 m per AGENTS.md,
while preserving historical receipts at their original thresholds.

## Frozen development replay

At consumer `0dbfceb`, a wheel installed in a separate filesystem/pid namespace
compared all 106 retained modes and both prepared groups from the prior automatic
browser job. Only the completed job, runtime, opaque index and fresh context-output
directory were mounted. The parent directory containing post-search evaluation,
source checkouts, labels and identifier map were absent. Candidate parameters were
never refitted; ground truth was joined only after the context process exited.

The context leader was the 6.505 m candidate, formerly rank 4 under core scoring.
All 106 modes were compared. The first three context rows were 6.505, 6.511 and
21.886 m from truth, with scores 1.593565, 1.593410 and 1.450892. The strongest
distant competitor was the original 1,046 km leader: it scored 1.247464 and ranked
fourth. Its descriptive paired-block margin was [0.179233, 0.511281], with a mean
gap of 0.346101 contrast units. The nearby 21.886 m mode slightly exceeded the
leader in one event's pre-core portion; there is no uniform dominance across
every partition or calibrated location-confidence claim.

Common context retained 759/936 bins for event 1 and 475/728 for event 2, with both
pre/post portions present. Those symmetric restrictions remain conditional on the
retained modes. Computation took 2.63 s with 571.93 MiB peak RSS measured inside
the scientific process. The initial external namespace-launcher timer did not
measure scientific memory; an instrumented replay reproduced the ranking exactly.

The diagnostic leader is within 100/500/1000 m, but the original automatic job
remains `inconclusive / unsupported_score_kind`. No accepted location or
independent real/national accuracy is established. The case was already inspected
during development; it is not a held-out success. Full readable results, all-mode
evaluation, input/code/array hashes and the namespace probe are under
`evidence/context-validation-20261103/`; larger NPZ/CSV files remain local with
their exact hashes. The implementation's full base-plus-consumer suite passed
132 tests; all 11 focused context tests passed after adding memory instrumentation.
After refreshing main and adopting W3's canonical predictor, all 210 tests and
six subtests passed. The installed namespace replay at calculation source
`1f986c5` reproduced the complete ranking exactly in 2.98 s / 532.44 MiB. Its
source/namespace receipt is `canonical-predictor-replay.json`.
