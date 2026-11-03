# Pipeline performance: 2026-11-03

Later exact fitting and I/O changes have a separate [throughput guide](PERFORMANCE_EXACT_THROUGHPUT.md). This report preserves its original sources and measurements.

The optimized scorer reduces median dense-workload CPU time from **42.2787 to 8.8591 seconds: 4.772× faster**. The sparse workload improves from **3.5491 to 2.2310 seconds: 1.591× faster**. Both results use three alternating pairs and require exact scoring results and logical ledger contents.

A fresh regional HTTP comparison processes the complete MP3 in **261.8356 versus 148.5474 seconds**. That is **1.763× faster**, or **43.27% less wall time**, in one sequential pair. Both runs complete every pipeline stage and return the same inconclusive result.

These are separate measurements. Component ratios are never multiplied into a workflow claim. The [measurement JSON](../benchmarks/results/pipeline-components-20261103.json) contains every trial, range, source identity, runtime, and comparison outcome.

## Sources and controls

| Source | Role |
| --- | --- |
| [`7a8dd279`](https://github.com/1337isnot1337/DOPPLERGEIST/tree/7a8dd27979bd9a984c8675c38a00dfbf98a5b01e) | Untouched original baseline |
| [`d7cc1dd2`](https://github.com/1337isnot1337/DOPPLERGEIST/tree/d7cc1dd2e8089768253492b3269dfae97b3ad1a4) | Baseline with the isolated scalar-power correction |
| [`bee7793c`](https://github.com/1337isnot1337/DOPPLERGEIST/tree/bee7793cf539d4d48fe2fb888f223c1e403a71ef) | Staged scorer before complete-batch reuse, equivalent to local `00727d4` |
| [`f4f8bede`](https://github.com/1337isnot1337/DOPPLERGEIST/tree/f4f8bede6529481810a2984479246f9faf2122ae) | Frozen final timing source, identical tree to local `b3875b33` |
| [`a3ba3534`](https://github.com/1337isnot1337/DOPPLERGEIST/tree/a3ba35342e491556973be34022f3e0a10ac1f6f4) | Integrated core through upstream main `1f60cb5`, identical tree to tested local `ef30def8` |

The original and corrected baselines share the old detail-plot policy. The final regional timing source uses that same policy. Its speedup excludes the later optional plots from PR #215 and cached terrain metadata from PR #224.

All workloads use actual recordings and historical aircraft observations. The WAV produces 18 measured ridges in 16 independent groups. The HTTP MP3 produces 17 ridges in 15 groups. Each timing pair uses identical input bytes, scientific parameters, and budgets.

The receiver regions and clocks are source-informed development controls. They do not provide independent location truth. The restored aircraft archive excludes known jets and cannot establish complete coverage. Runtime and exact agreement therefore do not establish localization accuracy.

## Scoring results and repeated work

The direct controls compare the corrected baseline with the frozen final source. Input loading is outside the scoring timer. Each revision runs in a separate interpreter.

| Workload | Associations | Baseline CPU median | Final CPU median | CPU speedup |
| --- | ---: | ---: | ---: | ---: |
| Dense, `previous-fit` | 1,927 | 42.2787 s | 8.8591 s | 4.772× |
| Sparse, `offset` | 206 | 3.5491 s | 2.2310 s | 1.591× |

Dense CPU trials range from 41.7976–44.1917 seconds before and 8.6578–10.3526 seconds after. Sparse trials range from 3.3633–3.7990 seconds before and 2.1610–2.3343 seconds after. The JSON retains wall time, excluded loading time, memory measurements, and execution order.

A separate incremental control measures complete-batch reuse against the staged scorer:

| Workload | Staged CPU median | With complete-batch reuse | CPU speedup |
| --- | ---: | ---: | ---: |
| Dense | 16.7566 s | 8.7102 s | 1.924× |
| Sparse | 2.4510 s | 2.1388 s | 1.146× |

These incremental controls also use three alternating pairs. All four comparisons preserve complete candidate payloads, discarded-candidate accounting, and logical ledger contents. They use Python 3.12.14, SQLite 3.53.1, CPU 6, and one numerical thread.

Profiling identified repeated source fitting after existing acoustic reuse. An unchanged dense replay made **3,981 batch calls with only 548 distinct exact inputs**. Its **3,433 repeated calls represent 86.2%** of the total. This instrumented replay explains the opportunity. Its timing is not a speedup measurement.

The new cache reuses an entire successful fit batch. Its key preserves scalar parameter types and array values, data types, shapes, strides, and alignment. It retains the original batch shape and reduction behavior. Unsupported representations follow the unchanged fitter.

The cache holds at most **4 MiB of keys and serialized values**, with at most **4,096 entries**. Each hit restores fresh result objects. Caller mutations cannot affect later results. The cache excludes `None` fallbacks and exceptions. Its lifetime ends with the scoring call.

The limit covers cache storage, not total process memory or temporary allocations. Recorded-input checks cover layout differences, changed inputs, eviction, caller ownership, malformed containers, and fallbacks.

Upstream [PR #212](https://github.com/1337isnot1337/DOPPLERGEIST/pull/212) supplies the staged scorer. Complete-batch reuse extends that implementation. The [original-arithmetic alternative](https://github.com/1337isnot1337/DOPPLERGEIST/tree/c1b7e93ed47ae26beffcf07fdf3ee9ebe639b955) remains available separately. An earlier one-process comparison found it slower than the staged scorer.

## Complete regional HTTP control

The regional pair uploads the whole 43,202,925-byte MP3. It does not crop the recording or select fewer events. Both runs consider all 15 independent groups.

The common request uses bounds `[-73.545, 40.865, -73.505, 40.895]`. Its clock interval is `2026-09-08T20:17:20Z` through `20:17:40Z`. These controls come from the historical development hypothesis.

Both runs process two tiles and four coarse points. Each searches 40 refinement points and records 80 skipped points under the same rules. Each returns 23 candidates from 20 retained hypotheses, with three refined and 17 unrefined hypotheses. Neither run records a tile or refinement failure.

The exact comparator passes with **zero scientific differences** across:

- 20 job JSON artifacts and three root JSON artifacts.
- One logical SQLite ledger containing 29,738 bounds, 852 records, 12 stages, and one run.
- Discovery, candidate diagnostics, work accounting, refinement, and decision evidence.

The verifier observes all seven stages, including automatic provenance, intake, discovery, acquisition, search, refinement, and decision. Both services stop cleanly. Both return `inconclusive` with `reason_code=search_incomplete`. A completed computation does not imply a supported location.

The baseline runs first, followed by the optimized source. Both use Python 3.12.3, SQLite 3.45.1, CPU 4, and one numerical thread. Combined process-and-child CPU falls from 260.2496 to 147.8406 seconds. This remains one fresh pair, not a repeated workflow distribution.

HTTP polling suggests search falls from 150.68 to 59.79 seconds and refinement from 81.50 to 60.72 seconds. These stage intervals have polling uncertainty. The decision stage completes too quickly for a separate observed interval.

## Other components

The [same evidence file](../benchmarks/results/pipeline-components-20261103.json) preserves these earlier controls. Times in this table are wall seconds. Audio, helper, and empty-tile rows use three-pair medians. Warm-cache rows use three queries after an initial query.

| Workload | Control | Before | After | Speedup |
| --- | --- | ---: | ---: | ---: |
| Full WAV discovery, without intake or plots | Old/new source | 7.357 | 6.044 | 1.22× |
| Two recorded ridge windows | Old/new source | 0.183 / 0.0736 | 0.0607 / 0.0256 | 3.02× / 2.87× |
| 441 tracks, 89,504 samples, warm query | Cache disabled/enabled | 1.568 | 0.101 | 15.53× |
| 1,183 tracks, 287,491 samples, warm query | Cache disabled/enabled | 4.725 | 2.745 | 1.72× |
| Geometry identities for 214 tracks | Old/new helper | 0.712 | 0.0107 | 66.50× |
| Duplicate-index query, track cache disabled | Old/new helper | 2.970 | 1.490 | 1.99× |
| 283 scalar terrain/geoid queries | Old/new helper | 0.482 | 0.151 | 3.20× |
| 256 actual empty tiles | Ordinary/batched commits | 2.169 | 0.765 | 2.84× |

Discovery adopts scalar medians from [PR #221](https://github.com/1337isnot1337/DOPPLERGEIST/pull/221). Ridge tracing reuses transition slices, penalties, and predecessor indices. Window sizes and strict tie comparisons remain unchanged.

The trajectory cache checks payload integrity before reuse and returns independent tracks. Its protected admission prevents large scans from repeatedly evicting useful entries. The cache holds at most 32 MiB of serialized snapshots and 2,048 entries per index. `track_cache_bytes=0` disables it.

The first full-day query takes 4.041 seconds without caching and 4.936 seconds with caching: approximately **22% slower**. Across one cold and three warm queries, the full-day workload improves by 1.35×. The smaller regional workload improves by 3.43× across four queries. These controls do not establish a cold operating-system cache.

Binary geometry identities avoid repeated JSON conversion. A bounded cache also reuses coordinate transforms for terrain queries. These helper controls cover 71,571 trajectory samples and 274 distinct candidate coordinates.

Retention batches at most 32 consecutive empty tiles per transaction. Every coarse stage, global stage, checksum, and checkpoint remains present. An interrupted transaction leaves checkpoints that fail normal stage validation until replay. The benchmark includes all 512 stages but excludes progress updates and resume reads.

Audio and helper controls use Python 3.12.14. Trajectory-cache and transaction controls use Python 3.12.3 with SQLite 3.45.1. Each pair uses one shared runtime and package set.

The configured replay also measures one versus four workers from [PR #210](https://github.com/1337isnot1337/DOPPLERGEIST/pull/210). Wall time changes from 63.08 to 50.86 seconds, or 1.24×, in one pair. All 16 scientific JSON artifacts, three CSV files, and 283 ranked rows match. This separate source-informed replay retains incomplete model support.

## Arithmetic differences and incomplete runs

The final comparisons use the corrected baseline because the original batch power arithmetic differs from scalar arithmetic. One discarded dense candidate changes related diagnostics and a ledger checksum. The measurement JSON preserves those earlier differences.

A longer MP3 replay exposes one upper-bound difference: `3.785201622023032` versus `3.7852016220230325`. An isolated replay retains its 15 groups, six selected flights, 33 clocks, and exact score floor. The corrected baseline and optimized source produce identical complete payloads. The discrepancy remains attributed to the isolated arithmetic correction.

Both obsolete CONUS runs stopped intentionally after the final regional comparison completed. Their final shared prefix contains 87 nonempty tiles: 86 match exactly, and one contains that known correction. This partial comparison does not establish complete-workflow parity.

Two earlier original-baseline attempts stopped with retention-database errors under SQLite 3.53.1. The cause remains unestablished. A later system-runtime attempt reached the 900-second HTTP timeout. Its failed receipt and complete pre-resume snapshot remain intact.

The resumed original run and obsolete combined run remain interrupted and incomplete. Their exact final CPU and active wall accounting are unavailable. Unknown values remain null. No nationwide speedup or completed nationwide localization is claimed.

## Reproduce the measurements

Install the dependencies from [SETUP.md](SETUP.md). Use one interpreter and package set for each pair. Select a new output directory for each run. Limit numerical threads before the measurement.

```bash
. .venv/bin/activate
export PYTHONPATH=src
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python scripts/restore_artifacts.py \
  --bundle data-source --bundle data-adsb-derived --bundle data-terrain

git fetch origin
git worktree add --detach ../DOPPLERGEIST-perf-original \
  7a8dd27979bd9a984c8675c38a00dfbf98a5b01e
git worktree add --detach ../DOPPLERGEIST-perf-corrected \
  d7cc1dd2e8089768253492b3269dfae97b3ad1a4
git worktree add --detach ../DOPPLERGEIST-perf-final \
  f4f8bede6529481810a2984479246f9faf2122ae

PERF_BASELINE=../DOPPLERGEIST-perf-original
PERF_CORRECTED=../DOPPLERGEIST-perf-corrected
PERF_FINAL=../DOPPLERGEIST-perf-final
PERF_INDEX=results/perf-input/reference-region.sqlite

python - <<'PY'
import json
from pathlib import Path
from dopplergeist.data_access import FlightIndex
fixture = json.loads(Path('tests/data/real-search-workloads.json').read_text())
FlightIndex.from_parquet(
    'results/perf-input/reference-region.sqlite',
    'data/adsb/2026-09-08/reference-region.parquet',
    coverage=fixture['index_coverage'],
)
PY
```

### Scoring controls

The portable fixture checks source bytes, coverage declarations, normalization, and input counts. Local source paths can differ after restoration. The dense case contains 214 tracks and 117 CPA rows. The sparse case contains 219 tracks and 65 CPA rows.

```bash
python scripts/benchmark_real_search_batch.py \
  --fixture tests/data/real-search-workloads.json \
  --index "$PERF_INDEX" --case previous-fit \
  --baseline-source "$PERF_CORRECTED/src" \
  --current-source "$PERF_FINAL/src" \
  --repeats 3 --output results/new-final-dense

python scripts/benchmark_real_search_batch.py \
  --fixture tests/data/real-search-workloads.json \
  --index "$PERF_INDEX" --case offset \
  --baseline-source "$PERF_CORRECTED/src" \
  --current-source "$PERF_FINAL/src" \
  --repeats 3 --output results/new-final-sparse
```

On Linux, prefix these commands with `taskset -c 6` to match the measured affinity. The published scoring controls use the Python 3.12.14 environment. The `--prepare-only` flag checks inputs without timed scoring. Each command writes its comparison under `OUTPUT/runs/comparison.json`.

### Component controls

```bash
python scripts/benchmark_real_audio_performance.py \
  data/source/reference-recording.wav --baseline "$PERF_BASELINE" \
  --ridge-config data/source/reproduce-local.json \
  --repeats 3 --output results/new-audio-comparison

python scripts/benchmark_real_performance_helpers.py \
  --index "$PERF_INDEX" \
  --bounds -73.87498229500986 40.62693175890468 -73.17498229500987 41.12693175890468 \
  --time-range 1788897749.6620934 1788903449.6620934 \
  --baseline "$PERF_BASELINE" --repeats 3 --output results/new-helper-comparison

python scripts/benchmark_real_track_cache.py --index "$PERF_INDEX" \
  --bounds -74.299988 40.100005 -72.700011 41.599964 \
  --time-range 1788898500 1788902400 --passes 4 \
  --output results/new-track-cache.json

python scripts/benchmark_real_empty_tiles.py --index "$PERF_INDEX" \
  --tiles 256 --batch-size 32 --passes 3 --output results/new-empty-tile-comparison
```

For the full-day cache case, use bounds `-74.05 40.55 -73.55 41.05` and times `1788825600 1788912000`. Add `--max-tracks 5000 --max-samples 750000`. The empty-tile fixture preserves completed checkpoints from the failed baseline. Its control compares every ledger table and stage checksum.

### Regional HTTP pair

Select the Python 3.12.3/SQLite 3.45.1 environment to match the published HTTP runtime. Prepare one operator file and one complete MP3 for both sources. The request fixture preserves the regional bounds and 20-second clock interval.

```bash
PYTHONPATH="$PERF_FINAL/src" python scripts/prepare_reference_upload.py \
  --data-root data --output results/regional-inputs

python - <<'PY'
import json
from pathlib import Path
path = Path('results/regional-inputs/operator.json')
operator = json.loads(path.read_text())
operator['search_workers'] = 1
path.write_text(json.dumps(operator, indent=2) + '\n')
PY

ffmpeg -nostdin -i data/source/reference-recording.wav \
  -ac 1 -ar 48000 -c:a libmp3lame -b:a 96k \
  results/regional-inputs/reference.mp3

python scripts/benchmark_real_regional_upload.py \
  --source "$PERF_CORRECTED/src" \
  --audio results/regional-inputs/reference.mp3 \
  --request benchmarks/reference-regional-upload-request.json \
  --operator results/regional-inputs/operator.json \
  --output results/regional-baseline --timeout-s 7200 --threads 1

python scripts/benchmark_real_regional_upload.py \
  --source "$PERF_FINAL/src" \
  --audio results/regional-inputs/reference.mp3 \
  --request benchmarks/reference-regional-upload-request.json \
  --operator results/regional-inputs/operator.json \
  --output results/regional-current --timeout-s 7200 --threads 1

python scripts/benchmark_real_regional_upload.py \
  --compare results/regional-baseline results/regional-current \
  --output results/regional-comparison.json
```

Encoder builds can change MP3 bytes. This reconstruction does not promise the historical MP3 hash. Both sources must receive the same newly encoded file. The driver expects 17 ridges, 15 groups, and all groups considered. Its `--check-inputs` flag checks preparation without upload or fits.

## Recorded-input verification

The integrated revision [`a3ba3534`](https://github.com/1337isnot1337/DOPPLERGEIST/tree/a3ba35342e491556973be34022f3e0a10ac1f6f4), identical to local `ef30def8`, passes **36 focused checks in 34.39 seconds**. Source compilation and CLI help also pass. This gate uses Python 3.12.3, SQLite 3.45.1, CPU 5, and one numerical thread. Its separate CPA fixture contains 100 rows. It is distinct from the dense timing fixture.

The earlier `9a46b7b` revision passes the same 36 checks in 34.80 seconds. Its public equivalent is `01775bb1`. [Hosted installation and static checks](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41669485319) also pass on Python 3.11 and 3.14 for `a3ba3534`. The JSON retains the earlier hosted result for `01775bb1`.

```bash
python -m pip install '.[test]'
python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --index "$PERF_INDEX" --clock-half-width-s 120 \
  --output results/new-real-cpa-fixture.json

DOPPLERGEIST_REAL_CPA_FIXTURE=results/new-real-cpa-fixture.json \
python -m pytest -q \
  tests/test_real_track_cache.py \
  tests/test_real_retention_batch.py \
  tests/test_real_performance_helpers.py \
  tests/test_real_index_staging.py \
  tests/test_real_prepared_measurements.py \
  tests/test_real_geometry_kinematics.py \
  tests/test_real_batch_scalar_parity.py \
  tests/test_real_complete_batch_cache.py

python -m compileall -q src
python -m dopplergeist.cli --help
```

These checks use recorded observations and the restored GLO30/EGM96 terrain files. No synthetic suite ran. The additional PR #224 cache-hit check requires unavailable GLO90 tiles. It did not run and is not included in the 36 passes.

## Method for future optimization

Freeze the source revisions, input bytes, scientific parameters, and budgets first. Profile an actual expensive workload to identify repeated work. Treat profile times as attribution because instrumentation changes runtime.

Measure a change against its direct control. Alternate process order and preserve cold-cache behavior. Compare complete scientific payloads and logical ledgers before reporting a speedup. Record skipped work, unsupported tracks, and failed attempts.

Then measure the complete workflow with identical inputs. Keep source-informed runtime controls separate from independent accuracy evaluation. Stop optional measurements once the result answers the remaining performance question.
