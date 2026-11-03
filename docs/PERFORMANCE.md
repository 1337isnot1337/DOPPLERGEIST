# Measured pipeline performance

The original PR225 point and HTTP comparisons use baseline `aa3dff686c989524daa20c081a816b792d9c8890` and the implementation published at `5699a657d57dc4f66b74ef000e20d3ba88f84704`.
The integration section separates validation of the combined implementation from these original comparisons.

The recorded PR225 implementation reduces median CPU time for complete point scoring by **45.94%** on the broad-clock workload.
The narrow-clock workload uses **49.56%** less CPU time.
Both comparisons preserve every scored association and its diagnostics exactly.
The changes reuse calculations and reduce data decoding without reducing the search domain, event coverage, solver iterations, or numerical precision.

These are incremental improvements over an already optimized baseline.
The earlier **2.69×** scorer result appears in the [historical comparison](#historical-scorer-comparison-2026-11-03).
The measurements cover different stages and environments, so their speedups do not combine into a complete-pipeline ratio.

## Integration with main: pending

Main commit [`0d6a92377af0f00b84dff9fa7966326d0014c20c`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/0d6a92377af0f00b84dff9fa7966326d0014c20c) merged [PR222](https://github.com/1337isnot1337/DOPPLERGEIST/pull/222).
That work independently adds batch-fit reuse and improvements to audio, terrain, trajectory decoding, and retention transactions.
Some changes overlap the original PR225 implementation.
The [PR222 report](PIPELINE_PERFORMANCE_2026-11-03.md) preserves its separate measurements.
The combined implementation also includes main commit [`21262e031388b3a5a8dd75979b2dc851608499b2`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/21262e031388b3a5a8dd75979b2dc851608499b2) and its checkpoint compatibility changes.

The earlier PR225 timings do not isolate an incremental gain over `0d6a923` or `21262e0`.
A fresh comparison will validate the frozen combined implementation separately.
Results against `aa3dff6` describe the combined changes.
Results against `0d6a923` describe the additional changes after PR222.
Results against `21262e0` describe the additional changes after that later main revision.

<!-- PERFORMANCE_INTEGRATION_PENDING: fill after source freeze and the fresh HTTP comparison. -->

| Integration item | Status |
| --- | --- |
| Integrated main source | `21262e031388b3a5a8dd75979b2dc851608499b2` |
| Frozen combined source | Pending |
| Batch-cache selection | Serialized cache from main; 4 MiB digest-key and payload cap |
| Fresh bounded HTTP result and baseline | Pending |
| Exact JSON, SQLite, and array comparison | Pending |

### Cache selection for the combined implementation

One isolated, instrumented pair compared two cache implementations in otherwise identical code based on main `0d6a923`.
The pair used NumPy 2.3.5 and the same real broad-clock workload.
All 3,905 scored associations and retention outputs matched exactly.

| Cache implementation | CPU time | Estimated retained Python objects | Process peak RSS |
| --- | ---: | ---: | ---: |
| Serialized cache from main, 4 MiB key/payload cap | 12.822287035 s | 4,333,666 bytes | 285.35 MiB |
| Previous object-cache variant, 32 MiB accounted-object cap | 14.751674511 s | 33,553,167 bytes | 310.86 MiB |

The serialized cache used **13.08% less CPU time** in this pair and is selected for integration.
Its 4 MiB cap covers SHA-256 digest bytes and serialized snapshots.
The observed key and payload bytes peaked at 4,194,233 bytes.
Python object headers and ordered-dictionary bookkeeping require additional memory, so 4 MiB is not a total-heap cap.
The estimated retained-object figures describe cache memory; RSS describes the entire process.
Reported RSS includes setup and diagnostics; `ru_maxrss` can retain an inherited peak.

The [cache-selection record](../benchmarks/results/cache-integration-20261103.json) preserves this single sequential pair and its scope.
The execution environment was reset after this comparison.
The record retains returned measurements and the successful equality check; the temporary full outputs were lost.
This experiment does not measure a whole-pipeline speedup or the final integrated source.
The historical 32 MiB measurements below remain measurements of their original implementation.

## Exact fit reuse: recorded PR225 point-scoring comparison

Each workload used three alternating baseline/current pairs in separate Python processes.
The order was baseline/current, current/baseline, then baseline/current.
Each source used the same frozen recorded ridges, observed trajectories, candidate budgets, and receiver point.

| Recording-start window | Baseline median CPU | Current median CPU | CPU speedup | Scored associations |
| --- | ---: | ---: | ---: | ---: |
| ±120 seconds | 28.803255077 s | 15.571095273 s | **1.84979×** | 3,905 |
| ±10 seconds | 4.386338558 s | 2.212487520 s | **1.98254×** | 1,055 |

The timed operation includes complete point scoring and retention writes.
It excludes imports, input loading, fixture preparation, acquisition, discovery, nationwide search, refinement, and result JSON serialization.
The receiver point and recording clock come from a historical fit.
This experiment measures computation on actual observations, without an independent location-accuracy claim.

All six outputs within each workload match exactly, with no numerical tolerance.
The comparison includes every scored association, fitted diagnostic, support count, ranked row, and retention record, bound, and stage.
Both workloads supply all 16 independent groups, and both sources retain the same 100 associations.
The narrow workload checks that the improvement also applies to fewer clock trials.
Changing the clock window itself is not a code speedup and requires independent time evidence.

### Workload and runtime

Both fixtures contain 16 recorded ridge records and 724 ridge samples.
The broad fixture contains 452 observed trajectories, 91,889 trajectory samples, and 100 CPA rows.
The narrow fixture contains 426 observed trajectories, 87,206 trajectory samples, and 97 CPA rows.
Both retain four unsupported CPA tracks in their accounting.
The preparation command rejects a budget excess instead of silently truncating inputs.

The point timings used Python 3.12.14, **NumPy 2.5.4**, SciPy 1.17.0, pandas 2.2.3, pyarrow 26.0.1, and pyproj 3.8.0.
The host used Linux 6.18.57 and an AMD EPYC 9V74 processor.
OpenBLAS, OpenMP, MKL, and NumExpr each used one thread.
A full upload ran on the shared host during these measurements, so process CPU time is the primary metric.

| Window | Baseline median wall time | Current median wall time | Reported peak RSS, baseline → current |
| --- | ---: | ---: | ---: |
| ±120 seconds | 28.816586 s | 15.579372 s | 260.46 → 293.25 MiB |
| ±10 seconds | 4.393367 s | 2.215673 s | 210.37 → 211.93 MiB |

These wall times describe a shared host, without exclusive CPU access.
Reported RSS includes imports, input loading, and captured diagnostics through scoring.
The measurement uses `getrusage(RUSAGE_SELF).ru_maxrss`, which can retain an inherited peak across execution.
Separate `VmHWM` readings were not recorded.
These figures describe process memory, without an isolated measurement of the cache heap.

The baseline commit is `aa3dff686c989524daa20c081a816b792d9c8890`.
The measured scoring implementation is local commit `5ca480f8678ca1ed31a765768324f623a44f0da8` plus the 32 MiB batch-cache patch.
That worktree patch changed `_RidgeFitCache.batch_limit` from 16 MiB to 32 MiB and clarified the cache-limit docstring.
The harness did not record HEAD separately for each worker.
Concurrent terrain/ENF integration at local commit `5420163f026b6c2621226add88cfa05fda326b46` did not change the exercised FlightIndex or scoring paths.
Published commit `5699a657d57dc4f66b74ef000e20d3ba88f84704` contains the same exercised scoring paths and the measured 32 MiB limit.
Its additional compact-checkpoint change does not affect this point-scoring measurement.
The [exact-fit measurement record](../benchmarks/results/exact-fit-reuse-20261103.json) contains all twelve final runs, source details, input hashes, and workload counts.

The complete HTTP runtime uses **NumPy 2.3.5**.
The seven selected real-input tests and all 50 cache checks also passed in that runtime, with `PYTHONPATH=src` only.
Those checks cover scalar parity, prepared measurements, cache mutation, eviction, layout, and nested scope restoration.
They provide a separate correctness check, without another point-timing measurement.
The two NumPy environments remain separate in the recorded results.

### Why exact reuse reduces work

Dense candidate traversal repeats complete batches of identical ridge fits.
The measured scoped cache reuses successful batches with the same fitter, parameters, and array contents.
Its keys preserve input order, shape, dtype, strides, and alignment.
They also preserve the frequency bounds, frequency scale, and drift fraction without rounding.
Memory layout matters because existing NumPy reductions can differ by one ULP between contiguous layouts.

Each cache hit returns separate diagnostic dictionaries.
Mutations cannot alter a later cached result.
Unsupported representations use the original path, and the cache does not retain failed or unsupported results.
The cache lifetime follows the existing scoring context, including nested-scope restoration.
The scorer also reuses validated event ceilings with their complete diagnostic dependencies.
The fitting equations, six IRLS iterations, conservative screens, tie behavior, and candidate accounting remain unchanged.

### Why the recorded batch-cache limit was 32 MiB

The recorded implementation holds at most 4,096 batch entries and 32 MiB per active scoring context.
The byte limit accounts for keys, diagnostic values, and dictionary storage.
This allocation grows with demand and is separate from the acoustic and prepared-measurement caches.

An instrumented capacity comparison used the same broad fixture in four sequential runs: 16 MiB, 32 MiB, 32 MiB, then 16 MiB.
All outputs matched exactly.
Each run made 7,351 batch lookups.

| Batch-cache limit | Median CPU, two runs | Hits per run | Fits executed per run | Evictions per run | Maximum retained bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 16 MiB | 18.937758264 s | 5,403 | 1,948 | 1,443 | 16,777,214 |
| 32 MiB | 17.334247567 s | 6,281 | 1,070 | 17 | 33,553,175 |

The 32 MiB limit reduced CPU time by **8.47%** relative to 16 MiB in this capacity comparison.
Median reported process RSS increased from 276.97 MiB to 293.20 MiB.
The larger limit retains more repeated fits and avoids repeated eviction on this workload.
The final point-scoring table uses fresh runs with this selected limit.
The capacity runs include instrumentation and remain separate from the final speedup calculation.
The exact-fit measurement record preserves both capacities and every counter.

## Other measured stages

These comparisons use actual recorded-audio jobs and observed flight data.
Each row has its own scope and repetition count.

| Stage | Baseline CPU | Current CPU | Repetitions | Equality check |
| --- | ---: | ---: | --- | --- |
| Refinement and decision | 83.7084 s | 77.4870 s | One unprofiled pair | Complete refined candidates and final JSON |
| Optional event plots | 4.383 s | 3.277 s | Three alternating pairs | Every PNG pixel |
| Checkpoint JSON encoding | 1.32042 s | 0.28718 s | Five alternating pairs | Complete decoded payload and identifiers |

### Refinement and decision

The replay starts from fixed archived finalists, without repeating discovery or search.
The trajectory lookup now selects the named finalist IDs within the same space/time envelope before decompressing tracks.
Decoded tracks decreased from **881 to 18**, and decoded samples decreased from 233,165 to 5,303.
The fitter still receives the same required complete tracks, with the original validation and sample-budget checks.
The single unprofiled pair used **7.43%** less CPU time.
Both timed arms included the same decode counter.
It returned the same 23 candidates and the same `inconclusive / search_incomplete` result.
This is a phase observation, without a repeated-run estimate of total pipeline speed.
The [refinement measurement record](../benchmarks/results/decision-refinement-20261103.json) preserves the observations and their scope.

### Optional event plots

The plot comparison rendered all 18 event images from a complete 3,600.1845-second real recording with 16 independent groups.
The renderer computes the same full spectral normalization and passes only visible frequency bins to the plotting library.
The median CPU speedup was **1.34×**, with identical pixels in every image.
Diagnostic plots are off by default, so this gain applies only when plots are requested.
It excludes audio intake and acoustic discovery.
The [plot measurement record](../benchmarks/results/real-discovery-plots-20261103.json) preserves all three pairs, the recorded input, and the NumPy 2.3.5 environment.

### Compact internal checkpoints

The encoding comparison used one completed real tile with 19,977 candidate associations.
Compact JSON reduced its encoded size from **39,363,929 to 23,490,375 bytes**, a **40.33%** reduction.
Median encoding CPU time improved by **4.60×** across five alternating pairs.
Every decoded value, payload hash, and retention checksum remained identical.
The production change preserves checkpoint filenames, atomic writes, and resume identifiers.
Human-facing reports retain their readable formatting.

The timer covers JSON encoding only.
It excludes file writes, reads, scoring, and complete checkpoint or resume operations.
The [checkpoint measurement record](../benchmarks/results/checkpoint-encoding-20261103.json) preserves all ten runs and the decoded-output checks.

## Recorded PR225 complete-recording HTTP comparison

One sequential baseline/current pair completed the entire bounded HTTP workflow on the original 3,600.1845-second MP3.
It used the separate **NumPy 2.3.5** runtime on a shared host.

| Measurement | Baseline | Current |
| --- | ---: | ---: |
| HTTP verification elapsed wall time | 264.809609269 s | 188.323150374 s |
| Event records | 18 | 18 |
| Returned candidates | 23 | 23 |
| Full pipeline requirements met | Yes | Yes |

The observed elapsed-time speedup is **1.40614×**, or **28.88%** less wall time.
This is one pair, without a repeated-run estimate or a process CPU comparison.
Both runs passed the HTTP and full-pipeline verification checks.
Both returned `inconclusive / search_incomplete`.
The 18 event records form 16 independent groups.
Optional event plots remained disabled during both HTTP runs.

The request used the source-informed bounds `[-73.545, 40.865, -73.505, 40.895]` and recording-start window `2026-09-08T20:17:20Z` through `20:17:40Z`.
Both sources used the same observed flight index, terrain, one search worker, 2 km coarse spacing, and 500 m refinement spacing.
The top-K limit remained 20, with three refinement finalists.
Both searches processed four coarse points across two tiles, plus the same 40 existing refinement points.
Both skipped 80 refinement points under the existing rules.
These explicit regional bounds define the comparison workload and do not establish national completion or independent location accuracy.

The scientific comparison found zero differences across 23 job JSON artifacts, three root JSON artifacts, and the logical SQLite ledger.
It normalizes declared implementation hashes, run and job identities, performance fields, and local paths.
It excludes declared resume and worker metadata.
The performance fields are elapsed time and reported process peak RSS.
It compares the full operator configuration separately from its digest.
SQLite comparison covers all logical tables, columns, and rows, except `run.identity` and physical storage layout.
Decoded scientific values, numeric types, and signed zeros compare exactly, with no numerical tolerance.
The [pinned comparison script](https://github.com/1337isnot1337/DOPPLERGEIST/blob/a3ba35342e491556973be34022f3e0a10ac1f6f4/scripts/compare_real_upload_performance.py) defines the complete normalization rules.
The ledger preserves 48,226 bounds, 958 records, and 18 stages.
Supplementary checks also matched one intake diagnostic, one decoded PCM file, 18 CSV files, and the decoded pixels of one PNG exactly.
This workload contains no NPZ files.
The intake comparison replaces only the exact input path in the recorded decoder command.

The [bounded HTTP measurement record](../benchmarks/results/bounded-http-20261103.json) preserves the timings, settings, source identities, and equality results.
Published commit `5699a657d57dc4f66b74ef000e20d3ba88f84704` matches all 34 production source files in the frozen HTTP checkout.

A full CONUS baseline reached its declared 1,800-second limit before completion (1,800.23 seconds of wall time).
That unfinished search provides no nationwide speed ratio.
Regional source data do not establish national flight coverage or independent location accuracy.
The historical HTTP checks below describe their own revisions and workloads.

## Reproduce the recorded PR225 comparisons

Use Python 3.12.14 to match the recorded point-timing runtime.
Use Git and the GitHub CLI `gh` with access to the public checkpoint assets.
Run these commands from the repository root.
Use a fresh output directory for each comparison.

Install the point-timing environment and restore the observed inputs:

```bash
python3.12 -m venv .venv-point
.venv-point/bin/python -m pip install '.[test]' \
  'numpy==2.5.4' 'scipy==1.17.0' 'pandas==2.2.3' \
  'pyarrow==26.0.1' 'pyproj==3.8.0'
.venv-point/bin/python scripts/restore_artifacts.py \
  --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=src .venv-point/bin/python scripts/prepare_reference_upload.py \
  --data-root data --output results/incremental-inputs
```

Create separate source trees from the public baseline and optimized commits:

```bash
git fetch origin
git worktree add --detach ../dopplergeist-incremental-baseline \
  aa3dff686c989524daa20c081a816b792d9c8890
git worktree add --detach ../dopplergeist-timing-current \
  5699a657d57dc4f66b74ef000e20d3ba88f84704
```

The public optimized commit contains the recorded 32 MiB limit.
The source disclosure above identifies the local commit and worktree patch used during measurement.

Freeze and compare both workloads:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
for width in 120 10; do
  PYTHONPATH=src .venv-point/bin/python scripts/benchmark_prepared_measurements.py prepare \
    --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
    --index results/incremental-inputs/reference-region.sqlite \
    --clock-half-width-s "$width" \
    --output "results/incremental-inputs/point-${width}s.json"

  PYTHONPATH=src .venv-point/bin/python scripts/benchmark_prepared_measurements.py compare \
    --fixture "results/incremental-inputs/point-${width}s.json" \
    --baseline-source ../dopplergeist-incremental-baseline/src \
    --current-source ../dopplergeist-timing-current/src \
    --repeats 3 --timeout-s 600 \
    --output "results/incremental-${width}s"
done
```

The comparison rejects changed inputs, missing trajectories, invalid retention ledgers, or any complete-output mismatch.
Both arms use the same interpreter and library versions.

Run the seven selected real-input tests and the cache checks:

```bash
DOPPLERGEIST_REAL_CPA_FIXTURE=results/incremental-inputs/point-120s.json \
PYTHONPATH=src .venv-point/bin/python -m pytest -q \
  tests/test_real_batch_scalar_parity.py \
  tests/test_real_batch_ridge.py \
  tests/test_real_prepared_measurements.py

PYTHONPATH=src .venv-point/bin/python scripts/check_real_batch_cache.py \
  --tracks data/adsb/2026-09-08/reference-region.parquet \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --candidate evidence/results/reference-local/report.json
```

The separate HTTP-runtime correctness check used the same commands with NumPy 2.3.5 and no additional dependency directory on `PYTHONPATH`.
It passed all seven tests and all 50 cache checks.

For the other stage comparisons, use a separate NumPy 2.3.5 environment:

```bash
python3.12 -m venv .venv-stages
.venv-stages/bin/python -m pip install '.[test]' \
  'numpy==2.3.5' 'scipy==1.17.0' 'pandas==2.2.3' \
  'pyarrow==26.0.1' 'pyproj==3.8.0' 'matplotlib==3.10.8'
```

The original refinement and plot comparisons used NumPy 2.3.5.
The checkpoint encoding helper uses the Python standard library.
To repeat the separate runtime checks, use `.venv-stages/bin/python` in the previous test and cache commands.

For refinement, use a completed real job with saved finalists, flight indexes, and terrain:

```bash
PYTHONPATH=src .venv-stages/bin/python scripts/benchmark_real_decision.py \
  --source ../dopplergeist-incremental-baseline/src \
  --job /path/to/real-job --output results/decision-baseline
PYTHONPATH=src .venv-stages/bin/python scripts/benchmark_real_decision.py \
  --source ../dopplergeist-timing-current/src \
  --job /path/to/real-job --output results/decision-current \
  --compare-to results/decision-baseline
```

The script compares every refined candidate, sensitivity result, and decision after the timed operation.
It omits the exploratory decode counter from the original pair.
For repeated measurements, alternate the source order and use new output directories.

For optional plots, use saved intake and discovery outputs from a real recording:

```bash
PYTHONPATH=../dopplergeist-timing-current/src \
.venv-stages/bin/python scripts/benchmark_real_discovery_plots.py \
  /path/to/real-job --baseline ../dopplergeist-incremental-baseline \
  --repeats 3 --output results/plot-comparison
```

For checkpoint encoding and compatibility, use the original filename of a completed real tile:

```bash
.venv-stages/bin/python scripts/benchmark_real_checkpoint_encoding.py \
  --checkpoint /path/to/real-job/search/tile-ID.json --repeats 5 \
  --output results/checkpoint-encoding.json

DOPPLERGEIST_REAL_TILE_CHECKPOINT=/path/to/real-job/search/tile-ID.json \
PYTHONPATH=src .venv-stages/bin/python -m pytest -q \
  tests/test_real_compact_checkpoints.py
```

The encoding helper compares readable and compact JSON, including one trailing newline in both timed operations.
Input decoding, output decoding, file writes, and equality checks remain outside the timer.
The compatibility tests also exercise atomic replacement and saved support-accounting parity.

### Complete bounded HTTP replay

Use the NumPy 2.3.5 environment and public source worktrees from the preceding commands.
Install FFmpeg so that `ffmpeg` and `ffprobe` are on `PATH`.
The [bounded upload helper](../scripts/benchmark_real_bounded_upload.py) starts each source in a fresh HTTP service.
It uses the same input file, request, operator configuration, and interpreter for both arms.

Restore the recorded inputs and prepare the shared index:

```bash
.venv-stages/bin/python scripts/restore_artifacts.py \
  --bundle data-source --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=../dopplergeist-timing-current/src \
.venv-stages/bin/python scripts/prepare_reference_upload.py \
  --data-root data --output results/bounded-inputs

.venv-stages/bin/python - <<'PY'
import json
from pathlib import Path
root = Path('results/bounded-inputs')
request = json.loads((root / 'request.json').read_text())
request['search']['bounds_wsen'] = [-73.545, 40.865, -73.505, 40.895]
request['time_window']['source_detail'] = (
    'Source-informed integration replay around the historical fitted recording '
    'start and benchmark receiver region; not independently measured recording '
    'time or a location-accuracy evaluation.'
)
operator = json.loads((root / 'operator.json').read_text())
operator['search_workers'] = 1
for name, value in (('request.json', request), ('operator.json', operator)):
    (root / name).write_text(json.dumps(value, indent=2) + '\n')
PY
```

The helper preserves the recorded 20:17:20–20:17:40 UTC window, search budgets, and refinement settings.
The public `data-source` bundle contains `reference-recording.wav`, not the original timed MP3.
For the original workload, supply the archived complete MP3:

```bash
cp /path/to/archived/reference-complete.mp3 results/bounded-inputs/recording.mp3
sha256sum results/bounded-inputs/recording.mp3
```

The measured MP3 contains 42,085,293 bytes and has SHA-256 `e1c13dafd8d1634bbf84df843c31771318e15a31ebb86dd165af7ee312ab80a0`.
If only the published WAV is available, use this command instead of the copy command:

```bash
ffmpeg -n -nostdin -i data/source/reference-recording.wav \
  -map 0:a:0 -vn -map_metadata -1 -ac 1 -ar 48000 \
  -c:a libmp3lame -b:a 96k results/bounded-inputs/recording.mp3
```

This conversion creates a new encoding of the real recording.
It defines a new comparison workload and requires fresh results.
The original hash, event counts, candidate counts, and timings do not apply automatically.
Both arms must use the same resulting MP3 file.

Run the two fresh HTTP arms sequentially:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
.venv-stages/bin/python scripts/benchmark_real_bounded_upload.py \
  --source ../dopplergeist-incremental-baseline/src \
  --inputs results/bounded-inputs --output results/http-baseline --timeout-s 900
.venv-stages/bin/python scripts/benchmark_real_bounded_upload.py \
  --source ../dopplergeist-timing-current/src \
  --inputs results/bounded-inputs --output results/http-current --timeout-s 900
```

Fetch the pinned comparison tools and run both equality checks:

```bash
git fetch origin a3ba35342e491556973be34022f3e0a10ac1f6f4
git worktree add --detach ../dopplergeist-comparison-tools \
  a3ba35342e491556973be34022f3e0a10ac1f6f4
.venv-stages/bin/python \
  ../dopplergeist-comparison-tools/scripts/compare_real_upload_performance.py \
  --baseline results/http-baseline --current results/http-current \
  --output results/http-science-comparison.json
.venv-stages/bin/python scripts/check_real_upload_arrays.py \
  --baseline results/http-baseline --current results/http-current \
  --output results/http-array-comparison.json
```

The comparator pin contains the exact comparison implementation used for the recorded pair.
The separate tools worktree preserves its source identity without changing either measured production source.
The array check covers the saved artifacts that actually exist in each workload.

## Historical scorer comparison (2026-11-03)

The earlier scorer implementation reduced median CPU time by **62.87%** on its broad-clock workload.
The same workload takes **68.92 → 25.59 CPU seconds**, a **2.69× speedup**.
Every scored candidate, diagnostic, support count, and retention record matches the scalar-consistent baseline exactly.

These measurements cover complete scoring at one receiver point, using recorded audio ridges and historical flight trajectories.
They exclude discovery, downloads, input loading, nationwide search, and refinement.
The receiver point and recording clock come from a historical fit.
This experiment does not establish independent location accuracy or a nationwide completion time.

### Measurements

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

#### Fixed workloads

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

### Changes that reduce work

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

### Numerical baseline

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

### Reproduce the historical comparison

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

### Method for further optimization

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

### Independent runner and integration validation

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

#### Integration with main at d6a0c860

The tested integration commit is `d6a0c860bd5a64797b3bde29bb1f74c689d0ed52`.
It includes main `6d3e3f7`, with PR #210's configured workers and PR #213's association traversal optimization.
The fitter changes preserve those concurrent changes.

[The integrated CI run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41659297200) passed all eight real-input tests and both complete-output comparisons.
It used two alternating pairs per workload and the same scalar-consistent baseline.
Broad-window median CPU time was **69.4880 → 25.0318 seconds (2.7760×)**.
Narrow-window median CPU time was **5.6747 → 4.0153 seconds (1.4133×)**.
The CI measurement record includes all eight integration runs separately from the earlier measurements.
Python 3.11 and 3.14 installation, compilation, CLI, and packaged-asset checks also passed.

#### Complete-recording HTTP checks

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

Each search worker retains its own bounded cache; row-major tile scheduling does
not guarantee that neighboring work reaches the same worker. Grouping work by
geography remains a separate scheduling opportunity requiring a full search and
load-balance comparison.
