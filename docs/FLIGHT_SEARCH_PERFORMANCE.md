# Flight-search performance

The optimized scorer used 42–46% less CPU time on two real-input workloads.
Every compared scientific output matched exactly.
The [measurement record](../benchmarks/results/flight-search-20261103.json) contains every timing sample and input count.

## Results

Times are median CPU seconds, with minimum and maximum in brackets.
The ratio divides the baseline median by the optimized median.

| Workload | Baseline CPU | Optimized CPU | Ratio |
| --- | ---: | ---: | ---: |
| Regional point, fitted clock ±120 s | 14.759 [13.904, 14.883] | 7.970 [7.926, 8.296] | 1.85× |
| Dense partition of full-day observations | 62.635 [58.964, 66.567] | 36.068 [31.175, 37.388] | 1.74× |

Median wall time changed from 14.780 to 7.986 seconds and from 62.793 to 36.122 seconds, respectively.
Median peak memory changed from 336.81 to 338.09 MiB and from 652.96 to 657.79 MiB.
Memory covers the worker lifetime through scoring, including imports and input loading.

| Input count | Regional | Dense |
| --- | ---: | ---: |
| Observed trajectories | 452 | 4,694 |
| Trajectory samples | 91,889 | 713,100 |
| Closest-approach rows | 100 | 944 |
| Scored associations | 3,905 | 16,101 |

Both workloads use all 16 independent groups, 724 measured ridge samples, and retain the same 100 candidates.
Each optimized regional run recorded 38,890 successful native ridge fits and 850 successful native acoustic solves.
Each optimized dense run recorded 228,240 fits and 5,731 solves.

## Source and method

The baseline is main [`fec518e`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/fec518e51f14afe8d36203e6c5e1be1277dea14e).
The measured optimized source combines that revision with [PR #237](https://github.com/1337isnot1337/DOPPLERGEIST/pull/237) at [`41d064`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/41d06469935f776988e1a4f04ab386d0355b433b).
PR #237 supplies the native acoustic kernel, closest-approach reuse, and batch-ceiling reuse.
The native ridge fitter and acoustic evidence cache come from [PR #228](https://github.com/1337isnot1337/DOPPLERGEIST/pull/228).
The new harness controls dense partitions and checks native execution.

The final focused real-input suite passed 52 tests with zero skips.
Long-ridge coverage passed 540 comparisons.

The publication base is main [`c37128bb`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/c37128bb08f12b8a68cf1f1cbf86adc2436f60fd).
It preserves later index-digest and job-cancellation changes outside the timed scorer.
The selected prepared-CPA path subsumes the sample and schema reuse from [PR #248](https://github.com/1337isnot1337/DOPPLERGEIST/pull/248).
The `_sample_cache` interface remains available for compatibility.
These inherited changes receive no separate speedup attribution.
The measured baseline and optimized numerical source remain unchanged.

Each workload uses three pairs of fresh processes: baseline/current, current/baseline, then baseline/current.
Each workload uses one pinned CPU and one numerical thread.
Both sources share Python 3.12.14, NumPy 2.5.4, SciPy 1.17.0, and pandas 2.2.3.
GCC 13.3.0 builds the native extensions.

The timer wraps `_score`, benchmark counters, candidate-row capture, and retention writes.
It includes distance checks, closest approaches, associations, physical fits, and retention.
It excludes imports, input loading, acquisition, discovery, refinement, and result JSON serialization.
Profiling runs separately.
Comparison requires exact equality for every scored association, diagnostic, support count, ranking, and logical SQLite row.

Both workloads use a receiver hypothesis from a historical development fit.
The dense workload owns one 348.006-second association-anchor partition of the full-day inventory.
This partition assigns hypotheses without clipping their physical fit intervals.
The archive excludes known jets and cannot establish complete flight coverage.
These measurements establish no nationwide, complete-upload, full-day-completion, or independent localization-accuracy result.

## Reproduce the dense comparison

Use an environment with the project dependencies, GCC, and the GitHub CLI.
Run these commands from this integration checkout.
On Linux, select an available CPU for `BENCHMARK_CPU`.
Use new output paths for each comparison.

```bash
CC=gcc python setup.py build_ext --inplace
git worktree add --detach ../DOPPLERGEIST-flight-baseline \
  fec518e51f14afe8d36203e6c5e1be1277dea14e
python scripts/restore_artifacts.py \
  --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=src python scripts/prepare_reference_upload.py \
  --data-root data --output benchmark-inputs/flight-search
PYTHONPATH=src python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --index benchmark-inputs/flight-search/reference-region.sqlite \
  --reference-report evidence/results/reference-local/report.json \
  --full-day --max-tracks 5000 --max-samples 2000000 \
  --max-candidates 20000 \
  --anchor-window-s 1788864888.7151732 1788865236.7214916 \
  --output benchmark-inputs/flight-search/dense.json
BENCHMARK_CPU=0
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
taskset -c "$BENCHMARK_CPU" python scripts/benchmark_prepared_measurements.py compare \
  --fixture benchmark-inputs/flight-search/dense.json \
  --baseline-source ../DOPPLERGEIST-flight-baseline/src --current-source src \
  --repeats 3 --require-current-native --require-current-native-acoustic \
  --output results/flight-search-dense
```

For the regional control, replace the full-day and anchor arguments with `--clock-half-width-s 120`.
Use different fixture and result paths.
For separate phase diagnostics, add `--stage-timing`.

The [real-performance workflow](../.github/workflows/real-performance.yml) also runs these comparisons on manual dispatch.
It requires both native extensions, checks the explicit Python fallback, and includes the dense partition.
