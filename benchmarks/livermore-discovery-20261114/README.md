# Forty public smartphone passages: automatic-discovery development control

Protocol registered before waveform inspection or detector output in
[issue341](https://github.com/1337isnot1337/DOPPLERGEIST/issues/341#issuecomment-6874158023).
Source: Praveen Pathak, [Aeroplane data full analysis and raw files,v2](https://zenodo.org/records/24075029),
CC BY4.0, November9,2026. All40 WAVs in the archive match all40 publisher result
rows. Publisher-derived reference fields retain the source [CC BY4.0 license](https://creativecommons.org/licenses/by/4.0/). The publisher archive MD5 is verified by the prepare command. No recordings
or publisher tools are copied into Git.

This source was found through AeroDoppler's public README; its previously
reported29-case development summary was already seen. This is not an untouched
holdout. The source supplies presegmented individual passages, so this control
cannot measure full-recording recall or exhaustively label false proposals.

## Fixed experiment

- Production source463834f5bc9b839a74593b429dd88e92c7ad5779; all automatic defaults.
  The runner refuses changed production source rather than silently using this
  historical label. No aircraft IDs, harmonic traces, time windows, bands or
  coordinates enter discovery. It receives only each complete opaque WAV.
- All40 original WAVs, sorted by archive path and copied byte-for-byte as
  P01..P40. No case is selected or removed based on outcomes.
- Serial subprocesses,120-second deadline per case, single OpenBLAS/OMP thread,
  CPU median backend, no synthetic data. Every failed/timeout/partial outcome is
  retained. The complete prediction population freezes before evaluation.
- Evaluation then joins the publisher's manually traced single harmonic using
  its public first-sample UTC. At each reference point, an output ridge matches
  within max(2Hz,1% of reference frequency). Interpolation bridges at most1second;
  an exact observed point remains supported. No harmonic frequency scaling,
  event selection, time shifting, threshold tuning or refit is permitted.
- Retain every reference point, pointwise union coverage, best-single-ridge
  coverage and all out-of-audio reference points. The registered coverage
  criterion is union>=80% and best single ridge>=60%. This is a trace-recovery
  control, not validated source identity or general aircraft-detection accuracy.
  Unmatched output ridges lack exhaustive false-positive labels.

The publisher explicitly supplies phone WGS84 position, EGM96 elevation and UTC
sample-zero filenames. No hidden position is inferred. Its README does not
establish measured recorder position/clock uncertainty or start/end drift.
Those gaps prevent #53 field-corpus acceptance. No location search or acoustic
association to its supplied flight track is performed here.

## Replay

Download `raw_flight_data.zip` and `final_results_40_cases.csv` from the exact
public record above. In the recorded Python3.14.6/NumPy2.5.4/SciPy1.18.1/Numba0.68.1
environment, from runner commit `d78b3a9` with the pinned production
source and native extensions built. To register a different frozen source in a
new experiment, pass `--source-ref FULL_COMMIT`; the runner verifies the actual
production tree against that pin before creating outputs:

```bash
PYTHONPATH=src python scripts/benchmark_livermore_discovery.py prepare --data /path/to/public-data --output /path/to/new-inputs
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg PYTHONPATH=src python scripts/benchmark_livermore_discovery.py discover --inputs /path/to/new-inputs --output /path/to/new-predictions
PYTHONPATH=src python scripts/benchmark_livermore_discovery.py evaluate --data /path/to/public-data --predictions /path/to/new-predictions --output /path/to/new-evaluation
```

## Registered outcomes

All40 full-WAV discovery runs completed at runner `d78b3a9`, with no timeout,
failed case, evaluation error or out-of-audio reference point. Total audio was
3,605.33seconds; total wall time444.78seconds, with individual cases3.86–29.24s.
The detector returned1,102 ridges in49 acoustic groups; these counts do not
establish independent aircraft.

Only **5/40** cases met the exact registered trace-coverage criterion: P06,
P20,P21,P23,P35. Median pointwise union coverage was **55.86%**. P02 reached
82.1% union coverage but only57.0% best-single-ridge coverage, so it correctly
remains a failure under the predeclared conjunction. The full outcome table is
`trace-coverage-cases.csv`; all14,349 reference-point matches/errors are retained
in `trace-reference-points.csv.gz`, including every unmatched point. `population.json`
maps opaque IDs to the original public archive paths.

This is negative evidence for recovering the particular publisher-traced
harmonic, **not35 confirmed aircraft misses**. Saved outputs include other
harmonics; the publisher trace is a selected single harmonic and is not exhaustive
source truth. No metric, tolerance, model or discovery setting was changed after
evaluation. A post-hoc four-case spectrogram inspection found that additional
harmonics can remain visible while the traced one is absent or offset. That
inspection is diagnostic, not a replacement accuracy metric.

The [primary paper](https://arxiv.org/html/2611.12033v1) also makes clear that
the recordings were selected from longer sessions using flight-tracking
information, and examples with untraceable wind/noise were excluded. This
reinforces the development-selection limit; the dataset is not a blind continuous
field sample.

P28 was the only zero-output case. A separately retained diagnostic replay on
the same original audio recovered four raw DP tracks and three verified tracks,
none overlapping the publisher trace under the registered metric. Two verified
tracks were ascending and the third was a nearly flat descending component;
final selection returned no group. Thus final zero output alone does not prove
that the observed reference contour was extracted and then discarded. That
counterexample needs an extraction/reference diagnosis before changing acceptance.

These results do not establish low-SNR detection ranges, exhaustive recall or
false-proposal rates, independent field timing or location accuracy. No supplied
flight was searched or localized. Related #341/#13/#53 remain open.

## Registered reassignment comparison

After viewing the baseline, a second development comparison was registered in
[issue341](https://github.com/1337isnot1337/DOPPLERGEIST/issues/341#issuecomment-6877956899).
It uses the existing phase-derivative `reassigned_power` estimator in an explicit
isolated research subprocess, changing only the spectral representation passed
to the DP front. The same production source, all40 complete recordings, profiles,
thresholds,120-second deadline and original trace metric remain fixed. It does
not alter production code or feed reference traces into detection.

Every outcome and regression will be retained. The candidate advances to all six
original-hour AeroSonicDB background controls only if it strictly increases the
number meeting the original coverage criterion and preserves all five baseline
successes. Otherwise it is declined for promotion. This is a post-baseline
development comparison, not an unseen-data accuracy result or a threshold fit.
Use a new predictions/output directory and add `--spectral-mode reassigned` to
the discovery command.

All40 reassigned runs and14,349 reference-point evaluations completed, with no
failed/timeout case or out-of-audio point. The criterion was met by only **4/40**
(P06,P20,P21,P23): **P35 was lost and no case gained**. Median union coverage
fell from55.86% to53.12%. Returned ridge counts fell from1,102 to722, while groups
changed49->50; neither count establishes better precision or source independence.
One-shot total wall time was373.19s, versus444.78s in the ordinary run, with a
warm JIT/cache order and changed outputs; this is not a controlled speedup claim.

The predeclared promotion gate failed. The conditional six-hour background
controls were therefore **not run**, and no production method, threshold or
acceptance rule changes. Every case, regression and reference-point outcome is
retained in `reassignment-*` (point tables are gzip-compressed CSV).

## Actionable consumer failure

A separate post-hoc compatibility probe of the40 saved ordinary results at
main77694d5 found49 groups:43 unreconciled groups,5 supported groups and one
generic insufficient-sample failure. The first failure class remains with the
harmonic-reconciliation owner. The latter is tracked as [issue449](https://github.com/1337isnot1337/DOPPLERGEIST/issues/449):
P29 contains a valid seven-point discovery ridge, but matching's ten-point
requirement raises an untyped exception that the automatic path does not handle
as unsupported evidence. Its actual recorded-data reproducer and repair are
separate from changing detection thresholds or relabeling benchmark outcomes.
