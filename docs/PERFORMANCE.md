# Measured scoring performance

The 2026-11-03 implementation reduces median CPU time by **62.87%** on the broad-clock workload described here.
The same workload takes **68.92 → 25.59 CPU seconds**, a **2.69× speedup**.
Every scored candidate, diagnostic, support count, and retention record matches the scalar-consistent baseline exactly.

These measurements cover complete scoring at one receiver point, using recorded audio ridges and historical flight trajectories.
They exclude discovery, downloads, input loading, nationwide search, and refinement.
The receiver point and recording clock come from a historical fit.
This experiment does not establish independent location accuracy or a nationwide completion time.

## Measurements

Each result is the median of three runs per source in separate Python processes.
The harness alternates baseline/current, current/baseline, then baseline/current.
OpenBLAS, OpenMP, and MKL each use one thread.

| Recording-start window | Baseline CPU | Optimized CPU | CPU speedup | Baseline wall time | Optimized wall time | Median reported peak RSS, baseline → optimized |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ±120 seconds | 68.9247 s | 25.5895 s | **2.6935×** | 69.0860 s | 25.5983 s | 264.76 → 263.95 MiB |
| ±10 seconds | 4.6782 s | 4.0092 s | **1.1669×** | 4.6818 s | 4.0125 s | 207.25 → 205.05 MiB |

Broad-window CPU ranges were 66.2767–69.0722 seconds for the baseline and 25.1284–26.0193 seconds for the optimized source.
Narrow-window CPU ranges were 4.5853–6.0251 seconds and 3.2851–4.3290 seconds, respectively.
The narrow workload has more timing variation and a smaller benefit.
Peak RSS includes imports, input loading, and diagnostic capture through the end of scoring.
These are reported `getrusage(RUSAGE_SELF).ru_maxrss` readings.
Linux can retain an inherited peak across execution, and these runs did not capture separate `VmHWM` readings.
The table therefore does not establish precise memory savings.
CPU time, wall time, and exact-output comparisons are unaffected by this memory-measurement limitation.

The machine used an AMD EPYC 9V74 processor, Linux 6.18.57, and Python 3.12.14.
Package versions were NumPy 2.3.5, SciPy 1.17.0, and pandas 2.2.3.
[The measurement record](../benchmarks/results/performance-20261103.json) contains every run, the input hash, source commits, and workload counts.

### Fixed workloads

Both workloads use all 16 recorded ridge records, 16 independent groups, and 724 ridge samples from the archived discovery result.
The trajectory query retains complete recorded tracks within the declared query.
The preparation command stops on a budget excess instead of truncating the inputs.

| Quantity | ±120 seconds | ±10 seconds |
| --- | ---: | ---: |
| Recorded trajectories | 452 | 426 |
| Trajectory samples | 91,889 | 87,206 |
| CPA rows | 100 | 97 |
| Unsupported CPA tracks | 4 | 4 |
| Scored associations | 3,905 | 1,055 |
| Retained associations | 100 | 100 |
| Scalar fit calls, baseline → optimized | 65,207 → 72 | 2,456 → 31 |
| Acoustic calls, both versions | 850 | 53 |

Batch fits replace most scalar calls while preserving all required fits and all six IRLS iterations.
The two clock windows define different workloads.
The difference between those workloads is not a code speedup.
A narrower clock window requires independent recording-time evidence.

## Changes that reduce work

**Batch surviving clocks after each group.**
The scorer preserves the event order within each clock trial.
After the existing conservative screen, it fits surviving clocks together for the next group.
Later groups still wait until a surviving clock requires them.
The scorer consumes completed trials in the original clock order, preserving tie behavior.

**Reuse validated score contributions.**
The scorer validates each completed group once and retains its conservative prefix bound.
It preserves the original arithmetic order and rounds each positive accumulation upward.
Unknown groups retain their full possible contribution.
Strict comparisons preserve tied candidates and the original retention evidence.

**Prepare measurements once per scoped cache.**
Repeated fits reuse selected samples, normalized weights, and the independent-sample count.
Content-sensitive keys detect changed measurements.
The prepared-measurement cache has a 4 MiB limit.
Cached diagnostic dictionaries contain scalar values and use separate shallow copies.

**Reuse trajectory calculations.**
A packed polynomial evaluates position and velocity with one interval lookup.
Its arithmetic matches the original separate evaluations.
The cache retains at most eight small spline pairs and adds at most 6 MiB of coefficients.
Large splines use the original path.
The acoustic solver reuses its final position and velocity only after the unchanged-time condition succeeds.

**Remove repeated scalar reference fits.**
The old batch fitter repeated up to three scalar fits for every batch.
The regression suite compares every eligible fitted clock against the scalar model on the recorded workload.
The batch fitter keeps scalar fallback for unsupported, nonfinite, degenerate, overflowing, or noncanonical numeric inputs.

The staged table has a limit of 4,096 event-clock slots.
Larger products use the existing scalar traversal.
This limit changes the execution path without reducing the search domain.

## Numerical baseline

The untouched starting revision is `7a8dd27979bd9a984c8675c38a00dfbf98a5b01e`.
Its batch fitter uses NumPy array squaring where the scalar fitter uses Python scalar powers.
One recorded fit exposed a one-ULP rounding difference in the prior.
Later IRLS iterations propagated this difference.
The original first/middle/last checks did not detect every affected clock.

Commit `d7cc1dd2e8089768253492b3269dfae97b3ad1a4` corrects those powers and preserves the original repeated reference checks.
It also preserves the original geometry, measurement preparation, and search traversal.
This numerical correction is separate from the speed changes.
The performance comparison uses this scalar-consistent commit as its baseline.

Commit `3725e9d2027d979e579ba9c347fb688ebf0895c3` contains the optimized source used for these measurements.
All six outputs match exactly within each workload.
The comparison includes every scored association, all diagnostics, support counts, ranked rows, and persisted retention records, bounds, stages, and checksums.
The harness uses no numerical tolerance.

Against untouched main, the broad workload retains the same top 100 candidates and support counts.
One discarded candidate retains the legacy rounding difference in its old diagnostic values.
Exact equality with untouched main is therefore not the correctness claim.
An earlier single observation took 77.43 CPU seconds on untouched main, but the table uses the repeated scalar-consistent baseline.

## Reproduce the comparison

Use Python 3.11 or later, Git, and the GitHub CLI `gh` configured for release downloads.
Run these POSIX-shell commands from the repository root.
For the published source comparison, use optimized commit `3725e9d2027d979e579ba9c347fb688ebf0895c3` as the current checkout.
Use a fresh output directory for each experiment.
The commands require access to the public checkpoint assets and sufficient disk space for the restored flight and terrain data.

Install the runtime and restore the recorded inputs:

```bash
python -m venv .venv
.venv/bin/python -m pip install '.[test]'
.venv/bin/python scripts/restore_artifacts.py \
  --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=src .venv/bin/python scripts/prepare_reference_upload.py \
  --data-root data --output results/performance-inputs
```

Create the baseline worktree:

```bash
git worktree add --detach ../dopplergeist-scalar-baseline \
  d7cc1dd2e8089768253492b3269dfae97b3ad1a4
```

Freeze each workload and compare both sources:

```bash
for width in 120 10; do
  PYTHONPATH=src .venv/bin/python scripts/benchmark_prepared_measurements.py prepare \
    --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
    --index results/performance-inputs/reference-region.sqlite \
    --clock-half-width-s "$width" \
    --output "results/performance-inputs/point-$width.json"

  PYTHONPATH=src .venv/bin/python scripts/benchmark_prepared_measurements.py compare \
    --fixture "results/performance-inputs/point-$width.json" \
    --baseline-source ../dopplergeist-scalar-baseline/src \
    --current-source src --repeats 3 --timeout-s 600 \
    --output "results/performance-$width"
done
```

Run the focused regression suite with the recorded broad-window fixture:

```bash
DOPPLERGEIST_REAL_CPA_FIXTURE=results/performance-inputs/point-120.json \
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_real_prepared_measurements.py \
  tests/test_real_geometry_kinematics.py \
  tests/test_real_batch_scalar_parity.py
```

The comparison command fixes numerical library thread counts for its worker processes.
It stops on any candidate, diagnostic, support, or retention mismatch.
It also rejects a changed index hash, missing trajectory, empty workload, or invalid retention ledger.
The focused tests skip without an explicitly supplied real fixture.

The [Real performance comparison workflow](../.github/workflows/real-performance.yml) repeats this procedure on a separate GitHub runner.
It uses two pairs per workload and saves the raw timing summaries.
The workflow also runs the focused real-input tests.
It does not run the historical synthetic suite.

## Method for further optimization

1. Freeze the source, recording, trajectory index, clock window, and search budgets.
2. Profile a complete bounded workload with all independent groups.
3. Identify repeated work through call counts and cumulative CPU time.
4. Preserve the physical model, conservative bounds, support failures, and candidate accounting.
5. Compare complete outputs before accepting a timing result.
6. Alternate separate-process runs and report their medians and ranges.
7. Measure discovery, acquisition, search, and refinement separately before predicting total runtime.

Existing data indexes and terrain caches avoid repeated acquisition costs.
The recording clock controls the number of plausible flight associations.
Clock evidence can reduce work, but an unsupported clock restriction changes the scientific question.

Worker count also affects throughput and memory use.
Excess workers can increase memory pressure and compete for the same CPU resources.
The measurements here establish single-worker scoring gains without assuming linear parallel scaling.

An existing process continues to use its loaded source.
New measurements require a new run with the new source identity.
Checkpoint reuse must pass the existing source and input identity rules.

## Independent runner and integration validation

The [independent CI run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41656583534) passed all eight focused real-input tests.
Both complete-output comparisons also passed, with two alternating pairs per workload.
The PR installation/static checks pass for the measured source.

| Window | Baseline median CPU | Optimized median CPU | Speedup |
| --- | ---: | ---: | ---: |
| ±120 seconds | 45.1467 s | 17.3027 s | 2.6092× |
| ±10 seconds | 3.7122 s | 2.7628 s | 1.3436× |

The GitHub runner used Python 3.12, NumPy 2.5.4, SciPy 1.18.1, and pandas 3.1.0 on Ubuntu 26.04.1.
[The CI measurement record](../benchmarks/results/performance-ci-20261103.json) preserves all eight runs and their source revisions.
These ratios support the local result on a second environment without pooling timings from different machines.

### Integration with current main

The tested integration commit is `d6a0c860bd5a64797b3bde29bb1f74c689d0ed52`.
It includes main `6d3e3f7`, with PR #210's configured workers and PR #213's association traversal optimization.
The fitter changes preserve those concurrent changes.

[The integrated CI run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41659297200) passed all eight real-input tests and both complete-output comparisons.
It used two alternating pairs per workload and the same scalar-consistent baseline.
Broad-window median CPU time was **69.4880 → 25.0318 seconds (2.7760×)**.
Narrow-window median CPU time was **5.6747 → 4.0153 seconds (1.4133×)**.
The CI measurement record includes all eight integration runs separately from the earlier measurements.
Python 3.11 and 3.14 installation, compilation, CLI, and packaged-asset checks also passed.

### Complete-recording HTTP checks

The full-domain HTTP replay used the entire 3,600.1845-second reference recording and an explicit source-informed clock.
It completed intake, discovery, and acquisition, then reached its 900-second limit during adaptive geographic search.
Its source remained unchanged, and the service stopped cleanly.
It did not complete refinement or a scientific decision.
The partial job and timeout receipt remain available for inspection.

This timeout does not establish a complete-pipeline speedup.
The current search subdivides dense tiles that the older historical replay omitted after budget failures.
That older elapsed time is not a comparison for equal work.

A separate HTTP replay on the integrated source passed the complete application-path check in **247.04 seconds**.
It used the same complete recording and clock window, with explicit source-informed bounds `[-73.545, 40.865, -73.505, 40.895]`.
The bounds contain four actual 2 km grid points.
The operator retained the original search budgets, solver settings, 500 m refinement spacing, and three finalists.
Discovery produced 18 ridge records in 16 independent groups.
The verifier checked intake, discovery, acquisition, search, refinement, and decision, including 23 returned diagnostic candidates.
Search processed both tiles, four coarse points, and 40 refinement points without tile or refinement failures.
The verifier reported no pipeline-evidence errors, unchanged source files, and clean service shutdown.

The scientific result was **`inconclusive / search_incomplete`**.
Incomplete regional flight coverage and remaining search/model limitations still prevent an accepted location.
The bounded replay verifies the complete application path, not nationwide completion or a speed ratio against the timed-out run.
The CI measurement record preserves both HTTP outcomes and their separate source revisions.

## DEM cache locality (2026-11-03)

A terrain-only stress check sampled 12 actual saved coarse tiles from the public
original-MP3 search, three times each. With the existing 32 MiB per-worker DEM
cache, clustered calls took 2.46 CPU seconds and interleaved calls took 5.56 CPU
seconds in the baseline run. Reusing cached raster metadata and decoded pixels
reduced clustered raster opens from 81 to 26 and CPU time to 2.10 seconds;
interleaved CPU time was 5.41 seconds with 78 opens. The twelve elevation arrays
matched bit-for-bit across implementations. Each figure is one loaded-machine
observation, and this is not a whole-search speed estimate. A separate exploratory
128 MiB cache run did not materially improve the interleaved workload, so the
32 MiB cap is unchanged. See [the recorded measurements](../benchmarks/results/dem-locality-20261103.json).

To repeat on a real saved job and populated terrain cache:

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=src python scripts/benchmark_dem_locality.py \
  --job /path/to/job --cache /path/to/cache --output /path/to/result.json
```

Each search worker retains its own bounded cache. The parallel driver submits
tile cores in a deterministic Hilbert walk and yields results in the original
order; each worker now scores up to two nearby uncached tiles in one task, keeping
both on the same worker cache. Assignment between pairs remains dynamic. The
ordered driver materializes the current wave before submitting it, which can
delay the first task on a heavily resumed run.
Because the parent checkpoints a pair when its worker task returns, an
interruption can require recomputing one finished tile from that pair.

A static, equal-duration, 12-worker LRU replay on 115 saved real tiles (234 DEM
references, 54 rasters) estimated 213 opens for row-major single-tile tasks, 220
for Hilbert single-tile tasks, and 169 for Hilbert pairs. The paired schedule is
20.7% fewer modeled opens than row-major. This models cache misses; it does not
measure executor timing, load balance, or full-search speed. See the
[replay output](../benchmarks/results/dem-scheduler-locality-model-20261103.json)
and reproduce it with:

```bash
PYTHONPATH=src python scripts/benchmark_dem_scheduling_model.py \
  --search-dir /path/to/job/search --workers 12 \
  --output /path/to/dem-scheduler-model.json
```

Four actual saved full-day no-approach tiles also reproduced their payloads and
retention checksums with two workers. This checks result parity, not full-run
runtime.

In one separate paired test of a full-day clock partition with 17,776
associations, the merged scoring optimizations took 94.00 CPU seconds versus
243.29 seconds for the earlier two-event-filtering version. All 100 retained
candidates, retention checksum, and shared count fields matched exactly. The
older version also emitted a `minimum_matched_events` diagnostic, now retained
by this branch. A subsequent run with this combined branch took 103.41 CPU
seconds, 2.35 times faster than the earlier version, with the entire tile
payload and retention checksum exactly equal. These individual measurements do
not establish a nationwide runtime.
The [benchmark receipt](../benchmarks/results/combined-dense-20261103.json)
records the source revisions and scope.

Isolating the validated-ceiling cache from PR #225 on this same partition took
105.97 CPU seconds versus 103.41 for the combined source, with the entire payload
equal. This single observation does not establish a gain for that cache on the
dense workload; other cache changes in PR #225 are separate.
