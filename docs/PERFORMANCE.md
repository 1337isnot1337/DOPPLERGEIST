# Measured pipeline performance

## Optional CUDA discovery filter

The default acoustic discovery path uses SciPy on the CPU. On a machine with a
compatible NVIDIA GPU and driver, an optional CuPy backend accelerates the
31-bin frequency-axis median filter. Install a CuPy wheel compatible with your
CUDA driver in the same Python environment as DOPPLERGEIST, then select it:

```sh
python -m pip install cupy-cuda12x
DOPPLERGEIST_MEDIAN_BACKEND=cuda dopplergeist discover recording.mp3 --output results/cuda-discovery
```

Set the variable for `analyze` or `serve` in the same way. This example assumes
the CUDA 12 CuPy wheel is compatible with the installed driver; consult the
[CuPy installation guide](https://docs.cupy.dev/en/stable/install.html) for
other configurations. CPU remains the default; set `DOPPLERGEIST_MEDIAN_BACKEND=cpu`
to select it explicitly. CUDA errors are reported instead of silently switching
backends. A CUDA audio checkpoint records the selected backend and CuPy version,
so resume requires the same selection and version.

On one 28-second real recording, a GTX 1080 Ti and its host produced identical
discovery JSON and 21 ridges on both backends. A single complete discovery run
took 5.01 s on CPU and 3.59 s with CUDA. For one 4096 × 221 float32 spectrogram,
the filter output was exactly equal and median warm filter time over three runs
was 350 ms on CPU versus 1.9 ms on CUDA including transfers. These measurements
are specific to that recording and machine; they do not establish a search or
localization speedup, GPU parity on every device, or localization accuracy.

## Integrated pipeline acceleration, 2026-11-03

The integrated version reduces dense-search CPU time by **49.66%** and complete regional-upload elapsed time by **15.51%**.
Both results use three alternating pairs against pinned main revision `ae7721b`.
The [compact measurement record](../benchmarks/results/integrated-pipeline-20261103.json) contains every pair and its comparison results.
The implementation is in [PR274](https://github.com/1337isnot1337/DOPPLERGEIST/pull/274).

The branch combines [PR266](https://github.com/1337isnot1337/DOPPLERGEIST/pull/266), including PR256, with [PR262](https://github.com/1337isnot1337/DOPPLERGEIST/pull/262).
These changes avoid irrelevant flight decoding, reuse exact measurements and rejected prefixes, batch native fits, and reuse terrain and refinement inputs.
This integration also removes empty-association allocations, resolves the terrain-cache overlap, and preserves the geographic constraints from PR270.
The corrected benchmark keeps numerical functions unchanged during performance measurements.
Diagnostic wrappers and profilers cannot produce a production speedup claim.

### Complete regional HTTP workflow

Three alternating pairs reduced median complete HTTP elapsed time from **57.824 seconds to 48.853 seconds**. This is a **1.184× speedup and 15.51% less elapsed time**. Median CPU time decreased from **57.464 seconds to 48.407 seconds**, or **15.76%**. All six fresh runs completed, and all three strict paired comparisons passed.

| Pair | Order | Baseline HTTP seconds | Candidate HTTP seconds | Baseline CPU seconds | Candidate CPU seconds | HTTP speedup |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Baseline, candidate | 55.824 | 49.987 | 55.532 | 49.711 | 1.117× |
| 2 | Candidate, baseline | 59.393 | 47.888 | 59.089 | 47.593 | 1.240× |
| 3 | Baseline, candidate | 57.824 | 48.853 | 57.464 | 48.407 | 1.184× |
| Median | Three runs per revision | **57.824** | **48.853** | **57.464** | **48.407** | **1.184×** |

The HTTP timer includes service startup, upload, the complete workflow, service shutdown, and evidence verification. Wrapper wall-time medians were 57.832 and 48.862 seconds. Wrapper input checks and imports, external downloads, and prepared-index construction are outside this timed scope. Service startup imports and local acquisition remain part of the workflow.

The separate dense-search control reduced median CPU time from 35.475 to 17.858 seconds: **1.987×**. Its wall-time medians were 35.600 and 18.111 seconds: **1.966×**. The approximately twofold result applies to dense search. The complete HTTP control saved 15.5% of elapsed time.

#### Equality and controls

Baseline revision: `ae7721b7d3099980b884175cde1a3b07fc3fb1b5`.
Candidate revision: `49c90338f7be87921dcae45119d111efeea68596`.
Both revisions include the geographic refinement constraint from #270.

Each run used a fresh interpreter, HTTP service, and job. Both revisions used the same prepared SQLite index, dependencies, interpreter, operator configuration, request, and recorded audio. CPU affinity was CPU 0, with one numerical thread.

Both used native ridge fitting and acoustic propagation. The same existing default disabled detail plots. The verifier and comparators came from the candidate checkout for both revisions. Neither revision changed during the six runs.

The MP3 exactly matched the historical recording: 43,202,925 bytes, SHA-256 `707083f0344823eeea7f130faec6c22b6628b8b9fea04d026915d93df9a07b15`. Every run retained **17 ridges, 15 independent groups, and 23 candidates**. Every result remained **`inconclusive`**, with reason **`search_incomplete`**. These source-informed regional bounds and clock settings measure runtime. They do not establish location accuracy.

Each comparison reported **zero scientific-payload differences and zero array differences**. It compared 20 job JSON artifacts, three root JSON artifacts, and one logical SQLite database. Array verification covered decoded PCM, 17 CSV files, the overview PNG, and intake diagnostics. No scientific score, candidate, trial, retention row, or array was exempted. Normalization covered declared execution metadata only. Every service stopped successfully without forced termination.

The host was shared, with CPU affinity controls. Operating-system file caches were not flushed. One unpinned, read-only JSON extraction lasted 2.44 seconds during the first baseline run. No second numerical workload ran concurrently. All pairs remain in the report.

#### Remaining elapsed time

These approximate stage medians use HTTP transitions observed every 0.25 seconds. All six listed stages were observed in all three runs per revision.

| Stage | Baseline seconds | Candidate seconds |
| --- | ---: | ---: |
| Queued | 0.252 | 0.253 |
| Intake | 7.059 | 7.315 |
| Discovery | 6.086 | 6.342 |
| Local acquisition | 0.543 | 0.548 |
| Search | 25.765 | 20.142 |
| Refinement | 13.421 | 11.009 |

Search remains the largest stage at approximately 20.14 seconds, followed by refinement at 11.01 seconds. Intake and discovery together account for approximately 13.66 seconds. Stage medians do not sum exactly to the median HTTP duration. The decision stage appeared in only one poll sequence per revision, so it has no three-run estimate.


### Dense query and scoring

The integrated version takes **17.85767 seconds of CPU time**, compared with **35.47495 seconds** for pinned main `ae7721b`, on the recorded dense partition.
This is a **1.98654× CPU speedup** and **49.66% less CPU time**.
Median elapsed time decreases from **35.60028 to 18.11127 seconds**, a **1.96564× speedup**.
Both versions process the same 16,101 association candidates and retain the same 100 ranked modes.

The baseline is `ae7721b7d3099980b884175cde1a3b07fc3fb1b5`, including the latest geographic refinement bounds.
The measured local candidate is `a1859d16aaf3f8b09d564f3218180a672804f843`.
The public candidate is `49c90338f7be87921dcae45119d111efeea68596`.
Their complete Git trees are identical. Publication changed commit metadata only.

#### Timed scope and repeated measurements

The timer includes the flight query, conservative distance filter, closest-approach calculations, association scoring, and retention writes.
It excludes imports, index metadata, event preparation, downloads, index construction, terrain sampling, audio discovery, and refinement.
The workload uses one source-informed receiver and one association-anchor partition, without a recording-start clock prior.
The incomplete regional archive cannot establish independent location accuracy, complete daily search, or national completion time.

Each version runs in a fresh process on CPU 0, with one numerical thread.
The three pairs alternate baseline/candidate, candidate/baseline, then baseline/candidate.
The runtime uses Python 3.12.14, NumPy 2.5.4, SciPy 1.17.0, pandas 2.2.3, PyArrow 26.0.1, pyproj 3.8.0, and rasterio 1.5.2.
Both versions use their built native backends and the same prepared SQLite file.
The timer preserves the original numerical function identities. Numerical wrappers, phase instrumentation, and profilers are absent.
The harness verifies exact outputs outside the timed region.

| Pair | Order | Baseline CPU | Candidate CPU | Baseline elapsed | Candidate elapsed |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Baseline, candidate | 35.593029 s | 17.857673 s | 35.783980 s | 18.111270 s |
| 2 | Candidate, baseline | 35.474948 s | 18.683996 s | 35.600283 s | 18.834998 s |
| 3 | Baseline, candidate | 35.399849 s | 17.004541 s | 35.543712 s | 17.062545 s |
| Median | | **35.474948 s** | **17.857673 s** | **35.600283 s** | **18.111270 s** |

| Component | Baseline CPU median | Candidate CPU median |
| --- | ---: | ---: |
| Flight query and distance filter | 7.010340 s | 0.119326 s |
| Closest approaches, associations, scoring, and retention | 28.464538 s | 17.694768 s |

Component medians do not sum to the complete median. Component speedups do not multiply into a pipeline speedup.
Peak RSS medians through scoring are **456.671875 MiB** and **329.660156 MiB**, respectively.
These memory measurements include worker imports and input loading. They exclude the parent comparison process and later output serialization.
The operating-system file cache remains available between runs. Fresh workers do not establish performance with uncached files.

#### Exact outcomes and reduced work

All three pairs preserve exact candidate payloads, ranked modes, trial and support evidence, and logical retention tables.
Repeated outputs from each version are deterministic.
Each retention database contains **499 records, 15,777 bounds, and one stage**.
The outputs preserve **15,777 bounded candidate assessments** and **590,900 unknown trials**.

| Work item | Baseline | Candidate |
| --- | ---: | ---: |
| Queried tracks | 4,694 | 197 |
| Queried samples | 713,100 | 40,690 |
| Selected tracks | 1,354 | 197 |
| Closest-approach rows | 944 | 95 |
| Association work units | 302,818 | 147,985 |
| Unsupported tracks at closest approach | 62 | 4 |
| Processed association candidates | 16,101 | 16,101 |
| Ranked retained modes | 100 | 100 |

The original emission interval is `[1788825600.17, 1788911999.6]`.
The candidate uses the conservative partition interval `[1788865079.6561337, 1788868750.471493]`.
The harness verifies that queried tracks form a subset and that early work counts do not increase.
All **58 removed unsupported tracks** have complete emission intervals outside the feasible partition interval.

The full diagnostic documents differ because those early counts decrease.
The report therefore sets `identical_results` to false and `identical_scored_candidates_rankings_and_retention` to true.
Each candidate run records **206,740 successful native fits, 5,111 native acoustic solves, and 63 native closest-approach reductions**.

#### Prepared-index cost and unpartitioned control

One preparation run took **6.422 seconds** to create the reusable numeric index.
The source index occupies **41,385,984 bytes (39.468750 MiB)**.
The prepared copy occupies **85,929,984 bytes (81.949219 MiB)**.
The prepared representation adds **44,544,000 bytes (42.480469 MiB)** to the copy.
Keeping both files requires **127,315,968 bytes (121.417969 MiB)**.
The copy preserves the original payloads, source identity, and coverage metadata for compatible baseline readers.
Preparation is outside the repeated query timer. The measured gain combines preparation, partition filtering, and scoring changes.
These measurements do not isolate the prepared format's contribution or its separate break-even count.

The unpartitioned control removes only the association anchor and its scope sentence from the same fixture.
Its candidate limit remains 20,000. Both versions stop with the same error:

```text
ValueError: Association work/storage budget exceeded; search is incomplete
```

This control establishes exact budget-error parity. It establishes neither completed full-day output parity nor a full-day speedup.

### Reproduce the dense comparison

Use a Linux host with Python 3.12, GCC, Git, and the GitHub CLI.
Use separate clean source trees for the two pinned commits.
Keep other CPU-intensive work outside the measurement interval.

```bash
git fetch origin
git worktree add --detach ../dopplergeist-measured \
  49c90338f7be87921dcae45119d111efeea68596
git worktree add --detach ../dopplergeist-baseline \
  ae7721b7d3099980b884175cde1a3b07fc3fb1b5
cd ../dopplergeist-measured

python3.12 -m venv .venv-performance
. .venv-performance/bin/activate
python -m pip install 'setuptools==84.1.0'
python -m pip install -e '.[test]' \
  'numpy==2.5.4' 'scipy==1.17.0' 'pandas==2.2.3' \
  'pyarrow==26.0.1' 'pyproj==3.8.0' 'rasterio==1.5.2'
CC=gcc python setup.py build_ext --inplace
(cd ../dopplergeist-baseline && CC=gcc python setup.py build_ext --inplace)

export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export DOPPLERGEIST_RIDGE_BACKEND=auto
export DOPPLERGEIST_ACOUSTIC_BACKEND=auto
export DOPPLERGEIST_CPA_BACKEND=auto

python scripts/restore_artifacts.py \
  --bundle data-source --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH="$PWD/../dopplergeist-baseline/src" \
  python scripts/prepare_reference_upload.py \
    --data-root data --output benchmark-inputs
```

The restore helper verifies the archived sizes and hashes from `evidence/artifact-manifest.json`.
The index builder uses the original observed bounds and retains the incomplete-coverage metadata.
It produces **717,735 source rows and 4,694 segments**.
The original ingestion excluded known jets. The observed bounds do not establish complete geographic coverage.

Freeze the exact partition fixture and the optional regression fixtures:

```bash
python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --reference-report evidence/results/reference-local/report.json \
  --index benchmark-inputs/reference-region.sqlite \
  --full-day --max-tracks 2000 --max-samples 500000 --max-candidates 20000 \
  --anchor-window-s 1788864888.7151732 1788865236.7214916 \
  --include-track-query --output benchmark-inputs/dense-query.json

for width in 120 10; do
  python scripts/benchmark_prepared_measurements.py prepare \
    --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
    --reference-report evidence/results/reference-local/report.json \
    --index benchmark-inputs/reference-region.sqlite \
    --clock-half-width-s "$width" --output "benchmark-inputs/point-$width.json"
done

python scripts/benchmark_prepared_flight_search.py prepare-index \
  --source src --index benchmark-inputs/reference-region.sqlite \
  --destination benchmark-inputs/reference-region-prepared.sqlite \
  --output results/flight-preparation.json
```

The dense fixture contains **16 independent groups and 724 ridge samples**.
Its original query traverses **4,694 tracks and 713,100 samples**.
The original filter retains **1,354 tracks and 357,324 samples**, with **944 closest-approach rows and 62 unsupported tracks**.
The 120-second and 10-second fixtures support regression checks. They are outside this headline timing series.

Run the canonical harness without diagnostic flags:

```bash
taskset -c 0 python scripts/benchmark_prepared_measurements.py compare \
  --fixture benchmark-inputs/dense-query.json \
  --index benchmark-inputs/reference-region-prepared.sqlite \
  --baseline-source ../dopplergeist-baseline/src --current-source src \
  --repeats 3 --timeout-s 600 --output results/integrated-dense \
  --include-track-query --clock-partition-query \
  --require-current-native --require-current-native-acoustic \
  --require-current-native-cpa
```

The result must report `performance_timing_eligible: true` and exact parity of scored outputs.
The comparison file also contains the independent proof of reduced work and every timed sample.
If CPU 0 is unavailable, select one allowed CPU.
Record that reproduction difference.


### Reproduce the complete upload comparison

Use the prepared inputs and activated environment from the preceding procedure.
Encode the canonical WAV once for both revisions:

```bash
ffmpeg -nostdin -v error -i data/source/reference-recording.wav \
  -ac 1 -ar 48000 -c:a libmp3lame -b:a 96k benchmark-inputs/reference.mp3

python - <<'PY'
import json
from pathlib import Path
root = Path('benchmark-inputs')
operator = json.loads((root / 'operator.json').read_text())
operator['flight_indexes'] = [str((root / 'reference-region-prepared.sqlite').resolve())]
operator['search_workers'] = 1
with (root / 'operator-prepared.json').open('x') as output:
    json.dump(operator, output, indent=2)
    output.write('\n')
PY
```

Run three fresh pairs in alternating order:

```bash
set -euo pipefail
DG_RESULTS=results/integrated-http
mkdir "$DG_RESULTS"
DG_COMMON=(
  --audio benchmark-inputs/reference.mp3
  --request benchmarks/reference-regional-upload-request.json
  --operator benchmark-inputs/operator-prepared.json
  --allow-new-encoding --reference-wav data/source/reference-recording.wav
  --cpu 0 --threads 1 --timeout-s 900 --poll-interval-s 0.25
)
for DG_PAIR in 1 2 3; do
  DG_ORDER=(baseline current)
  if [ "$DG_PAIR" = 2 ]; then DG_ORDER=(current baseline); fi
  for DG_ARM in "${DG_ORDER[@]}"; do
    DG_SOURCE=../dopplergeist-baseline/src
    if [ "$DG_ARM" = current ]; then DG_SOURCE=src; fi
    python scripts/benchmark_real_regional_upload.py \
      --source "$DG_SOURCE" "${DG_COMMON[@]}" \
      --output "$DG_RESULTS/pair-$DG_PAIR-$DG_ARM"
  done
  python scripts/benchmark_real_regional_upload.py \
    --compare "$DG_RESULTS/pair-$DG_PAIR-baseline" \
              "$DG_RESULTS/pair-$DG_PAIR-current" \
    --output "$DG_RESULTS/pair-$DG_PAIR-comparison.json"
done
```

The measured encoder is FFmpeg 6.1.1. Its MP3 digest activates the fixed 17-ridge and 15-group control.
A different encoder can produce different bytes and event counts.
The explicit `--allow-new-encoding` declaration permits a new paired control against the canonical WAV.
Such a control cannot inherit these historical counts or timing claims.
Every pair must pass both scientific-payload and array comparisons before a speedup claim.

### Regression gates and operating limits

The native gate passed **329 tests and four subtests**, with zero skips, across 36 real-input modules.
The explicit Python gate passed **71 tests**. One native-only export test skipped because that gate disabled its backend.
The native gate passed that same test.
After the PR270 integration, **37 relevant real refinement tests passed**, with zero skips.
The performance workflow now includes the geographic-boundary module and both association regressions.
The [installation checks](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41719340040) passed on Python 3.11 and 3.14.
They cover packaged native backends, source compilation, CLI startup, and browser assets.
The [independent performance run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41719123985) contains the separate runner results.

The host uses an AMD EPYC 9V74 processor, Linux 6.18.57, and GCC 13.3.0.
Both timing series use one CPU. They make no multicore scaling claim.
The explicit local rasters instantiate `Terrain`, which retains the serial search path.
Increasing `search_workers` alone does not enable parallel execution for that terrain class.

An earlier geometry experiment improved small query slices but slowed the complete 4,694-track query by approximately 3%.
That experiment is absent from this implementation.
The retained changes passed the larger workload and the complete upload comparisons.

### Use the optimized implementation

Build the native extensions with `python -m pip install -e .`.
Prepare a separately named index with `python scripts/prepare_flight_index.py --index ORIGINAL.sqlite --output PREPARED.sqlite`.
Set `flight_indexes` in the operator configuration to that prepared index.
The default `auto` backends select compatible native extensions.
A fresh output directory permits the optimized runtime to establish its own checkpoint identity.
Existing checkpoint compatibility rules remain documented in the backend section of this guide.

## Prepared flight inputs and exact search reuse

[PR262](https://github.com/1337isnot1337/DOPPLERGEIST/pull/262) adds an optional
prepared trajectory representation, vectorized conservative trial bounds, and
exact native acoustic reuse. Against `994d1ee`, which already includes PR258,
the historical instrumented dense workload falls from
**33.986 to 26.794 seconds: a 1.268× diagnostic ratio, or 21.16% less elapsed time**.
Final-runtime CI at `b98a0fa3` records **38.374 to 30.399 seconds,
or a 1.262× diagnostic ratio / 20.78% less time**, and passes 168 recorded-input and fallback checks.
All compared scientific outputs and logical retention records remain equal.

The original prepared-flight harness wrapped numerical functions during these
dense measurements. The wrappers add overhead and can disable optimizations
guarded by function identity in the combined runtime. These figures retain
diagnostic and exact-output value. They do not measure canonical production throughput.
The [historical timing scope](PERFORMANCE_PREPARED_SEARCH.md#historical-timing-scope)
explains the qualification and the corrected harness controls.

The final implementation also reuses local terrain pixels and profile coordinate
transforms, and arranges spectral median inputs contiguously. A completed
intermediate HTTP series improves 9.56%. The final source has two complete exact
HTTP pairs, both faster, followed by an interrupted third pair. The report keeps
that incomplete series separate and makes no three-pair final HTTP claim.

The [prepared-search guide](PERFORMANCE_PREPARED_SEARCH.md) gives the complete
samples, preparation cost, storage tradeoff, HTTP measurements, operator steps,
and reproduction commands. Its pinned baseline separates these gains from the
earlier changes documented below. Component speedups are not multiplied.

## Indexed flight queries and repeated evidence checks

[PR258](https://github.com/1337isnot1337/DOPPLERGEIST/pull/258) reduces repeated work in indexed flight loading and ridge-evidence validation.
The measured production changes are pinned at [`a82f4b0`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/a82f4b02a5a4097693954ddec8e2c2386189e63a).
The incremental baseline, [`27da08a`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/27da08a878ac2ec90cd7e2c07f43765ceeea609b), already includes PR237's native fitting, acoustic computation, single-pass queries, and CPA improvements.
Those existing improvements are not attributed to PR258.
The [measurement record](../benchmarks/results/query-scoring-20261103.json) preserves samples, source pins, runtime, and comparison scopes.

### Compared with the implementation at task start

A separate three-pair comparison measures the complete dense query/sieve/scoring unit against starting main [`18e29d0`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/18e29d0e91b7b450aeca29915ceb72ee987349be).
Median CPU time falls from **63.798 to 32.507 seconds: 1.963× faster, with 49.05% less CPU time**.
Wall medians are **63.893 → 32.566 seconds**, or **1.962×**.
All six executions preserve the same complete scientific output and logical retention rows.

This measures the final version's combined improvement, including PR237's native kernels and single-pass queries, which merged while PR258 was being developed.
The incremental PR258 measurements below separate this patch's contribution from those earlier changes.
The starting query makes two traversals and yields 6,695 track objects / 1,047,000 samples across them; the final query makes one traversal and yields 4,694 / 713,100.
These operational counts include repeated yields. Both versions query the same unique inventory and select the same flights.
The combined speedup is measured directly; it is not a product of component measurements or a full-upload timing claim.

### Incremental measurements

Each row uses three alternating fresh baseline/current pairs on the same host.
Speedup is the baseline median divided by the current median.

| Measured scope | Baseline CPU median | Current CPU median | Speedup | Time reduction |
| --- | ---: | ---: | ---: | ---: |
| Broad point scoring, loaded tracks, ±120 s clock | 6.218 s | 5.682 s | 1.094× | 8.63% |
| Initial flight query, distance sieve, and dense scoring | 37.419 s | 36.161 s | 1.035× | 3.36% |
| Query and distance sieve within that dense run | 9.524 s | 6.960 s | 1.368× | 26.92% |
| Separate cold query and distance sieve, track cache disabled | 10.459 s | 7.471 s | 1.400× | 28.57% |

Dense whole-path wall medians are **37.473 → 36.220 seconds**.
Its query-plus-scoring CPU samples, in baseline/current pairs, are **39.870/36.161**, **37.419/38.104**, and **35.826/31.773 seconds**.
One whole-path pair is slower, despite a faster query stage in every pair.
Scoring-stage medians in this series are 27.895 and 28.996 seconds; the shared host introduces material timing variation.
Keep the modest whole-path result when evaluating this patch; do not replace it with a product of separate component ratios.
Worker-lifetime median peak RSS is **516.02 → 498.16 MiB**, including imports and input preparation.

The dense workload queries the full indexed day: **4,694 trajectories and 713,100 samples**.
The production overload path selects the same ordered **1,354 trajectories and 357,324 samples** in both versions.
Scoring evaluates **16,101 associations**, uses **16 independent ridge groups**, and retains the same **100 candidates**.
All six executions produce exactly equal queried and selected inventories, candidates, diagnostics, support accounting, ranking, and logical retention rows.
Both arms perform **228,240 successful native ridge fits** and **5,731 successful native acoustic solves** per dense execution.
The preloaded broad-point workload likewise preserves all **3,905 scored associations**, including diagnostics and retention.

### Independent CI replication

The [recorded-input CI run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41695355631) at `52db126` repeats the same comparisons against `27da08a` on a separate runner.
This commit adds a workflow build-dependency fix; its production code is identical to `a82f4b0`.
All three paired executions of each workload preserve exact outputs.

| CI workload | Baseline CPU median | Current CPU median | Speedup |
| --- | ---: | ---: | ---: |
| Point scoring, ±10 s clock | 0.579 s | 0.553 s | 1.048× |
| Point scoring, ±120 s clock | 3.759 s | 3.433 s | 1.095× |
| Initial query, sieve, and dense scoring | 23.694 s | 19.969 s | 1.187× |

CI dense-query wall medians are **23.827 → 20.104 seconds**, or **1.185×**.
The query/sieve component improves **1.528×**, and the CPA/scoring/retention component improves **1.097×**.
The whole-path improvement is measured directly, not derived by multiplying those components.
This runner uses Ubuntu 26.04, Python 3.12.16, NumPy 2.5.4, SciPy 1.18.1, and pandas 3.1.0.
Its absolute times should not be compared with the local runner's times; retain both matched comparisons.

The same run passes **99 recorded-input regressions and four explicit Python-fallback tests, with zero skips**.
The [installation checks](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41695366731) pass on Python 3.11 and 3.14.
Local decoder verification additionally compares all 4,694 actual indexed payloads against the pandas path, including exact arrays, spline coefficients, derivatives, and labels.
The initial CI attempt failed before benchmarks because the baseline extension build lacked runtime `setuptools`; the workflow now installs its declared build dependency explicitly.
Regional and bounded-HTTP CI jobs are not enabled by this branch's push conditions, so these CI results do not establish upload performance.

### Complete HTTP upload check

Three alternating complete MP3-upload pairs compare against [`494b874`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/494b874a42d8599e5950a05ef60f06a96ef4d1b9).
This baseline has the same numerical implementation as `27da08a`, plus the intervening job-startup/cancellation change, which both HTTP arms include.
All six executions complete upload, decoding, discovery, search, refinement, and decision verification.
Median elapsed time in the HTTP verification receipt is **51.211 → 49.500 seconds**, or **1.035× faster / 3.34% less time**.
Baseline samples are **51.349, 51.211, 51.094 seconds**; current samples are **54.366, 48.963, 49.500 seconds**.
The first pair is slower and remains in the measurement record. This is a modest incremental upload gain, not the roughly twofold dense-workload gain above.
The reported search timer has medians **22.789 → 21.621 seconds**; its scope is contained within the full workflow.

Every pair has zero scientific or array differences after the declared run-metadata normalization, without a numerical tolerance.
The comparison includes 20 scientific JSON artifacts, three root JSON files, the logical SQLite ledger, decoded PCM, 17 CSV files, and PNG pixels.
Each ledger preserves 29,738 bounds, 852 records, 12 stages, and one run.
Each upload retains 17 detected event records and 23 candidates; its decision remains `inconclusive / search_incomplete`.
Both arms use the same original MP3, request, operator configuration, index, terrain, numerical thread count, and CPU affinity.
The small source-informed regional request is an integration/performance control; it does not establish independent location accuracy.

### Where the time is removed

**Construct the representation needed by the next stage.** Indexed segments already contain canonical numeric JSON records.
Previously, each cache miss built a pandas table and immediately converted its columns into NumPy arrays for track normalization.
The new private column adapter supplies those arrays directly.
The existing `_frame_track` and `_segment_velocity` routines still perform normalization, velocity inference, and spline construction.
Noncanonical or mixed representations retain pandas.
The index schema, compressed payloads, integrity checks, cache keys, mutation isolation, and sample-budget checks are unchanged.
No index rebuild is required.

**Validate canonical evidence without repeatedly rebuilding Python objects.** Association scoring often checks complete, valid fit evidence with the same structure.
The optional C helper recognizes that narrow case and avoids the repeated Python field loop and per-event cache-key construction.
It only returns success for valid evidence in exact built-in containers and numeric types.
Mutations are rechecked on every call.
Invalid, incomplete, or custom inputs retain the original Python validation, including failure precedence and custom-object behavior.
Aggregate scores, Python summation, NumPy boundary handling, fit iterations, thresholds, and whole-batch ceiling reuse are unchanged.

These changes avoid work without reducing observed flights, event samples, search resolution, or candidate budgets.
A direct-distance alternative to the spatial tree was measured and rejected: its roughly 0.06-second geometry saving did not justify changing that path.

### Measurement method

The comparison harness accepts `--include-track-query` for preparation and comparison.
Each worker opens a fresh `FlightIndex` and starts timing before the initial traversal and conservative distance sieve.
The production 32 MiB track-cache budget remains enabled for the combined run; no track lookup occurs before its timer starts.
The default still measures complete scoring after loading selected tracks, so older commands keep their scope.

The dense run includes CPA preparation, association generation, physical scoring, and retention.
It excludes imports, index metadata, event preparation, downloads, terrain sampling, audio discovery, and refinement.
It queries all indexed times without a recording-clock prior, but scores one declared association-anchor partition, `[1788864888.7151732, 1788865236.7214916)`.
This partition controls association ownership; physical fit intervals are unchanged.
This is a measured dense search unit, not a measurement of every partition or receiver location.

Baseline/current order alternates as B/C, C/B, B/C.
Each arm runs in a new interpreter with the same inputs, one numerical thread, and CPU affinity fixed to CPU 2.
The separate cache-disabled query experiment uses CPU 0 and fresh index objects.
Operating-system file caches are not purged; “cold” describes the application track cache, not cold storage.
The host is shared, so CPU affinity does not imply exclusive machine access.
Separate profiling and native-validator hit-rate diagnostics are excluded from timing medians.
The reported PR258 runs used numerical operation counters and candidate capture in both timed arms.
Current comparisons preserve numerical function identities; separate diagnostic workers collect wrapped counters, as described below.

The local runtime is Python 3.12.14, NumPy 2.5.4, SciPy 1.17.0, pandas 2.2.3, pyproj 3.8.0, pyarrow 26.0.1, and SQLite 3.53.1 on Linux x86-64.
Native extensions use GCC with the existing strict floating-point build options.
Archived source-informed receiver and clock controls freeze computational workloads; they do not establish independent localization accuracy or nationwide throughput.

### Reproduce the query-plus-scoring comparison

Run these Linux commands from the optimized checkout, with GCC available.
Choose unused output paths because the harness refuses to overwrite prior results.

```bash
CC=gcc python -m pip install 'setuptools>=68' --editable '.[test]'
export PYTHONPATH=src
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python -c 'from dopplergeist import matching, native_acoustic; assert callable(matching._native_validate_ridge_events); assert native_acoustic._native is not None'
python scripts/restore_artifacts.py --bundle data-adsb-derived --bundle data-terrain
python scripts/prepare_reference_upload.py --data-root data --output benchmark-inputs
git worktree add --detach ../dopplergeist-baseline 27da08a878ac2ec90cd7e2c07f43765ceeea609b
(cd ../dopplergeist-baseline && CC=gcc python setup.py build_ext --inplace)

python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --index benchmark-inputs/reference-region.sqlite \
  --reference-report evidence/results/reference-local/report.json \
  --full-day --max-tracks 2000 --max-samples 500000 --max-candidates 20000 \
  --anchor-window-s 1788864888.7151732 1788865236.7214916 \
  --include-track-query --output benchmark-inputs/dense-query.json

benchmark_cpu=$(python -c 'import os; print(min(os.sched_getaffinity(0)))')
taskset -c "$benchmark_cpu" python scripts/benchmark_prepared_measurements.py compare \
  --fixture benchmark-inputs/dense-query.json --include-track-query \
  --baseline-source ../dopplergeist-baseline/src --current-source src \
  --repeats 3 --timeout-s 600 --output results/performance-dense-query \
  --require-current-native --require-current-native-acoustic
```

Check native availability after installation; source updates require rebuilding the extension and restarting a running service.
The runtime remains usable through its Python fallback, but that fallback does not receive the native evidence-validation saving.
Current comparisons require the native ridge backend and successful native acoustic operations.
A separate diagnostic worker verifies successful native ridge execution.
The harness refuses to report a speedup if any exact-output comparison fails.
The `Real performance comparison` workflow runs recorded regressions and these paired measurements, and preserves summaries as artifacts.

## Measured native computation and bounded reuse

The implementation at [`41d0646`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/41d06469935f776988e1a4f04ab386d0355b433b) completed the regional HTTP replay in a median **37.188 seconds**, compared with **62.031 seconds** for the already optimized main baseline [`fec518e5`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/fec518e51f14afe8d36203e6c5e1be1277dea14e).
That is **1.668× faster**, with **40.05% less elapsed time**, across three alternating fresh pairs.
The [recorded-input CI run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41685506906) passed all complete-scoring and HTTP equality gates.
The [compact measurement record](../benchmarks/results/exact-native-pipeline-20261103.json) preserves the individual samples, source pins, runtime, controls, and comparison scope.

| Workload | Baseline wall median | Optimized wall median | Speedup |
| --- | ---: | ---: | ---: |
| Complete regional HTTP replay, three pairs | 62.031 s | 37.188 s | **1.668×** |
| Complete point scoring, ±10 s clock, two pairs | 2.164 s | 1.273 s | **1.700×** |
| Complete point scoring, ±120 s clock, two pairs | 13.858 s | 7.652 s | **1.811×** |

HTTP baseline samples span **61.861–62.422 seconds**; optimized samples span **37.106–38.206 seconds**.
Median driver CPU time falls from **61.607 to 36.863 seconds**; it includes the verifier and its child processes.
Every pair processes the complete 3,600.1845-second recording and returns **17 ridge records, 15 independent groups, and 23 candidates**.
The decision remains `inconclusive / search_incomplete`.

Each HTTP pair compares 20 job JSON files, three root JSON files, the logical SQLite ledger, decoded PCM, 17 CSV files, and PNG pixels.
All three pairs have zero scientific or array differences after the declared metadata normalization, with no numerical tolerance.
Each ledger contains the same 29,738 bounds, 852 records, 12 stages, and one run.
The broad point workload compares all **3,905 candidates**, including diagnostics and support records, and retains the same 100 across 16 groups.
Its worker-lifetime peak RSS changes from **381.92 to 383.83 MiB**.
Each timed broad call records **38,890 successful native ridge operations and 850 successful native acoustic operations**.
All **78 selected recorded-input regression tests pass** at this measured checkpoint.

### Why this version is faster

The optional acoustic extension fuses spline evaluation, Newton updates, and vector reductions while preserving polynomial arithmetic order and the global stopping rule.
The optional ridge extension preserves six IRLS iterations and the original reduction order.
Python continues to handle unsupported representations, motion diagnostics, and exceptional numerical cases.

Repeated associations reuse validated batch ceilings within the existing 4 MiB budget for digest keys and serialized fit payloads.
A separate 8 MiB cache retains conservative, floor-independent acoustic loss evidence.
Every call still validates public inputs and applies its current ranking cutoff and group count.
The budgets cover their documented payload or evidence accounting; they are not limits on total process memory.
First-use hashing and serialization have a cost, so the complete-job measurements above determine the net benefit.

Trajectory queries continue in one pass when they exceed their initial budget.
CPA preparation reuses receiver coordinates, per-track samples, and spatial trees across bounded chunks, then builds one compact table.
Unsupported-motion checks batch interval work while retaining endpoint behavior and failure accounting.
Detector thresholds, event coverage, search resolution, solver iterations, and scientific tolerances are unchanged.

The native ridge implementation and narrow acoustic loss-bound cache are integrated from [PR228](https://github.com/1337isnot1337/DOPPLERGEIST/pull/228) at `2625539`.
The acoustic solver, batch-ceiling reuse, motion-support batching, one-pass queries, and CPA changes are separate contributions in [PR237](https://github.com/1337isnot1337/DOPPLERGEIST/pull/237).
Previously merged main optimizations remain in the comparison baseline.

### Measurement controls and limits

HTTP pairs run in baseline/current, current/baseline, and baseline/current order, with fresh processes and output directories.
Both arms share one MP3, request, operator configuration, flight index, and terrain set; both use one pinned CPU and one numerical thread.
Input restoration, index preparation, and MP3 encoding occur before timing.
Operating-system page caches are not purged.
Point scoring uses two alternating pairs and measures input loading separately.
Separate profiling runs do not contribute to timing medians.

The HTTP job uses Python 3.12.16; the point job uses Python 3.12.15.
Both use NumPy 2.5.4, and each comparison matches the complete runtime between its baseline and optimized arms.
The HTTP input is the original MP3 encoding with SHA-256 `707083f0344823eeea7f130faec6c22b6628b8b9fea04d026915d93df9a07b15`.
The regional request spans `[-73.545, 40.865, -73.505, 40.895]` and recording-start times from `2026-09-08T20:17:20Z` to `20:17:40Z`.
It uses one search worker, 2 km coarse spacing, 500 m refinement spacing, top-K 20, and three refinement finalists.

Install with a compatible C compiler and use the [native-backend checks and reproduction commands](#reproduce-the-optional-native-backends).
Either extension can fall back to Python, and both backends have explicit Python selectors.
Native performance and exact arithmetic controls were measured on Linux; macOS and Windows native performance remain unmeasured.

These are computation controls on a real recording and historical observations with source-informed regional bounds and clock evidence.
They do not establish independent location accuracy, nationwide completion time, or first-time network-acquisition speedup.
Earlier measurements below retain their original commits, encodings, and runtimes.
Their absolute times cannot be compared across runners, and component speedups must not be multiplied into a whole-pipeline claim.

### Integration confirmation

Source [`d935180`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/d93518010345a921b09722b8d7fc4ca1961c396e) incorporates later main changes through `b149d894`.
Its [complete replay](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41687118475) passes **78 recorded-input tests and all four explicit Python-fallback tests, with zero skips**.
This corrects the earlier fallback step's missing fixture setting, which had caused three tests to skip at `41d0646`.
All three HTTP pairs and both complete point comparisons again have exact scientific outputs and logical ledgers.
Against the same frozen baseline `fec518e5`, median HTTP time is **90.863 → 53.700 seconds**, or **1.692×**, on this separate runner.
Median driver CPU time is **88.862 → 53.148 seconds**; narrow and broad point-scoring speedups are **1.720×** and **1.827×**.
The differing absolute times illustrate why comparisons must stay within a matched run.
The [Python 3.11 and 3.14 installation checks](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41687129205) also pass.
The compact measurement record contains this confirmation separately from the first measured checkpoint.
Further main integration, its exact comparison baseline, and final gate results are recorded in [PR237](https://github.com/1337isnot1337/DOPPLERGEIST/pull/237).

## Historical PR225 integration measurements

The integrated implementation completed the fresh bounded HTTP workflow in **54.176928122 seconds**, compared with **78.379028870 seconds** for baseline `aa3dff6`.
That is an observed **1.44672×** speedup and **30.88%** less elapsed time in one sequential pair on the same CI runner.
The [integrated measurement record](../benchmarks/results/integrated-http-20261103.json) preserves exact output comparisons and the measured source pins.

The original PR225 point and HTTP comparisons use baseline `aa3dff686c989524daa20c081a816b792d9c8890` and the implementation published at `5699a657d57dc4f66b74ef000e20d3ba88f84704`.
The integration section separates validation of the combined implementation from these original comparisons.

The recorded PR225 implementation reduces median CPU time for complete point scoring by **45.94%** on the broad-clock workload.
The narrow-clock workload uses **49.56%** less CPU time.
Both comparisons preserve every scored association and its diagnostics exactly.
The changes reuse calculations and reduce data decoding without reducing the search domain, event coverage, solver iterations, or numerical precision.

These are incremental improvements over an already optimized baseline.
The earlier **2.69×** scorer result appears in the [historical comparison](#historical-scorer-comparison-2026-11-03).
The measurements cover different stages and environments, so their speedups do not combine into a complete-pipeline ratio.

## Integration with main: verified

Main commit [`0d6a92377af0f00b84dff9fa7966326d0014c20c`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/0d6a92377af0f00b84dff9fa7966326d0014c20c) merged [PR222](https://github.com/1337isnot1337/DOPPLERGEIST/pull/222).
That work independently adds batch-fit reuse and improvements to audio, terrain, trajectory decoding, and retention transactions.
Some changes overlap the original PR225 implementation.
The [PR222 report](PIPELINE_PERFORMANCE_2026-11-03.md) preserves its separate measurements.
The combined implementation includes main commit [`b7be4330c37eb9ec2bfca23a55d840bf9bb3acab`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/b7be4330c37eb9ec2bfca23a55d840bf9bb3acab).
Its fitting source is unchanged from [`21262e031388b3a5a8dd75979b2dc851608499b2`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/21262e031388b3a5a8dd75979b2dc851608499b2), which added checkpoint compatibility changes.

The earlier PR225 timings do not isolate an incremental gain over `0d6a923`, `21262e0`, or `b7be433`.
The fresh comparison below validates the frozen combined implementation against `aa3dff6`.
It measures the combined changes since that baseline.
An incremental HTTP timing comparison against the integrated main revision `b7be433` remains unmeasured.

| Integration item | Status |
| --- | --- |
| Integrated main source | `b7be4330c37eb9ec2bfca23a55d840bf9bb3acab` |
| Frozen combined source | [`66146714c6c22a448a7a54830a82d31034c2be44`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/66146714c6c22a448a7a54830a82d31034c2be44) |
| Batch-cache selection | Serialized cache from main; 4 MiB digest-key and payload cap |
| Fresh CI verification | [Run 41678922355](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41678922355); passed |
| HTTP baseline source | `aa3dff686c989524daa20c081a816b792d9c8890` |
| Fresh bounded HTTP elapsed time | 78.379028870 → 54.176928122 seconds; one sequential pair |
| Exact JSON, SQLite, and array comparison | Passed; zero differences after declared metadata normalization |

### Fresh integrated HTTP comparison

Both arms used the same fresh MP3 encoding of the complete published real recording, restored observed flight data, and terrain.
The baseline ran first, followed by the integrated source on the same CI runner.
The request, operator settings, and search budgets were identical between arms.
Each numerical library used one thread.
The request used bounds `[-73.545, 40.865, -73.505, 40.895]` and recording-start window `2026-09-08T20:17:20Z` through `20:17:40Z`.
It used one search worker, 2 km coarse spacing, 500 m refinement spacing, a top-K limit of 20, and three refinement finalists.

| Measurement | Baseline `aa3dff6` | Integrated `66146714` |
| --- | ---: | ---: |
| HTTP verification elapsed wall time | 78.379028870 s | 54.176928122 s |
| Event records | 16 | 16 |
| Returned candidates | 23 | 23 |
| HTTP and full-pipeline verification | Passed | Passed |
| Decision | `inconclusive / search_incomplete` | `inconclusive / search_incomplete` |

The measured wall-time ratio is **1.4467233855×**, with a **30.87828606%** elapsed-time reduction.
This is one sequential pair, without a repeated-run estimate or a process CPU measurement.
The source-informed regional request and recording clock make this a controlled integration workload.
It does not establish nationwide completion time or independent location accuracy.

The scientific comparison checked **17 job JSON files, three root JSON files, and one logical SQLite ledger**.
The ledger contained 16,894 bounds, 706 records, one run, and six stages in each arm.
It found zero differences after the declared run-identity, path, timing, and other metadata normalization.
The comparison retains exact decoded scientific values, numeric types, and signed zeros, with no numerical tolerance.

A separate comparison checked one intake diagnostic, one decoded PCM artifact, 16 CSV files, and the decoded pixels of one PNG.
All comparisons passed, and the manifest check covered **19 artifacts per arm**.
This workload contained no NPZ artifact.
The [integrated record](../benchmarks/results/integrated-http-20261103.json) preserves the verification results and comparison scope.

The fresh MP3 contains **43,202,924 bytes** and has SHA-256 `811a61eea5d21b5a99f008b499d399de9a20e475aaa0fc23cc233c7560605523`.
It is a new encoding of the published WAV, distinct from the original MP3 used for the earlier PR225 HTTP pair.
Both arms used this same file.
The old and new pairs have different encodings and execution environments, so their absolute times must remain separate.

The fresh runtime used Python 3.12.15, **NumPy 2.3.5**, SciPy 1.17.0, pandas 2.2.3, pyarrow 26.0.1, and pyproj 3.8.0.
It also used rasterio 1.5.2, Matplotlib 3.10.8, and FFmpeg 8.0.1-3ubuntu2.
All **38 selected real-input tests passed in 19.20 seconds**, with no skips.
The standard Python **3.11 and 3.14** CI jobs also passed.
The [successful verification run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41678922355) records the setup, test gate, sequential HTTP runs, and comparisons.
The [workflow at the measured commit](https://github.com/1337isnot1337/DOPPLERGEIST/blob/66146714c6c22a448a7a54830a82d31034c2be44/.github/workflows/real-performance.yml) preserves the exact replay commands in its fresh-HTTP job.
Reproduction must use the recorded baseline and current source pins, with one shared recording file for both arms.
A new encoding requires a new input hash and fresh results.

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
For the recorded 32 MiB revision, the seven selected real-input tests and all 50 cache checks passed in that runtime, with `PYTHONPATH=src` only.
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
For the recorded 32 MiB revision, it passed all seven tests and all 50 cache checks.

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

On a separate ordering-only replay of 12 saved real tile footprints (up to 1,024
points each, repeated three times), contiguous per-tile sampling reduced DEM
raster opens from 78 to 26 and sampler CPU from 5.89 s to 2.73 s (2.16x).
Elevation arrays matched exactly. Wall time was slower in the clustered order
(13.36 s versus 11.26 s), so the result supports cache locality but not end-to-end
speedup. This offline replay excludes download latency; reproduce with the same
[`benchmark_dem_locality.py`](../scripts/benchmark_dem_locality.py) script.

### Bounded worker-affine scheduling prototype

The scheduler prototype keeps the lazy row-major request stream and ordered
parent merge. It pins four consecutive uncached tile requests to one worker,
choosing a worker from a conservative geographic DEM footprint and its reported
in-memory DEM keys. A bounded lookahead of four tiles per worker keeps request
materialization independent of total search size; results and checkpoints remain
per tile. The worker cache keys are returned only as scheduling metadata and do
not enter tile payloads or retention records.

On the saved 745-tile checkpoint sequence, 130 payloads referenced terrain and
recorded 280 tile-to-DEM accesses across 66 unique rasters. A 32 MiB LRU model
replayed those observed footprints: round-robin assignment hit 28/280 accesses
(10.0%), four-tile worker chunks hit 117/280 (41.8%), and static contiguous
lanes hit 133/280 (47.5%). Bounding-box DEM prediction covered the recorded DEM
set for all 130 terrain-using tiles; mean per-tile precision was 90.6%, with
three predicted DEM footprints on otherwise empty tiles. These cache figures
are simulated from saved payload footprints, not timed worker measurements;
they do not establish search runtime or load balance.

A real worker replay used six contiguous saved tiles with 1,024 grid points each,
sampled twice through two workers. Both the shared pool and affinity scheduler
started two worker processes, and all elevation hashes matched. The affinity
scheduler reduced DEM raster opens from 43 to 38, decoded-cache misses from 27 to
23, and increased cache hits from 11 to 15. Summed terrain-sampler CPU fell from
4.19 to 3.89 seconds (1.08x) in this single replay. Wall time was not treated as
a result because it was one run under changing host load. Reproduce with
[`benchmark_dem_worker_affinity.py`](../scripts/benchmark_dem_worker_affinity.py);
the [run record](../benchmarks/results/dem-worker-affinity-20261103.json) is
terrain-stage evidence, not a full-search speed estimate.

Applying this scheduler to a saved search changes the package identity and
requires its validated checkpoint compatibility path before resuming that job.

## Reproduce the optional native backends

Installation builds the acoustic, ridge, and closest-approach (CPA) extensions when a compatible C compiler is available.
The package remains usable when an optional extension cannot build.
A source checkout used for timing must contain its own built extensions; an installed copy elsewhere does not establish native use.

```bash
. .venv/bin/activate
CC=gcc python -m pip install --editable '.[test]'
python - <<'PY'
from dopplergeist.geometry import ACOUSTIC_BACKEND
from dopplergeist.matching import RIDGE_FIT_BACKEND
from dopplergeist.native_cpa import CPA_BACKEND
print("Acoustic:", ACOUSTIC_BACKEND)
print("Ridge:", RIDGE_FIT_BACKEND)
print("CPA:", CPA_BACKEND)
assert ACOUSTIC_BACKEND.startswith("native-c-")
assert RIDGE_FIT_BACKEND.startswith("native-c-")
assert CPA_BACKEND.startswith("native-c-")
PY
```

The native acoustic solver retains polynomial evaluation order, global Newton stopping, and Python motion-support diagnostics.
The ridge extension retains the six IRLS iterations and reduction order.
The CPA extension preserves the existing closest-approach selection and arithmetic order.
All three extensions disable floating-point reassociation and contraction.
Incompatible numeric representations use the existing Python implementations.
Acoustic and scalar ridge calls also fall back for unsupported NumPy error policies.
Batched ridge arithmetic retains its existing ignored-error block and restores the caller's policy for diagnostics.
The optional ridge implementation is integrated from [PR228](https://github.com/1337isnot1337/DOPPLERGEIST/pull/228).

Set all three selectors before starting a process to force the Python implementations:

```bash
export DOPPLERGEIST_ACOUSTIC_BACKEND=python
export DOPPLERGEIST_RIDGE_BACKEND=python
export DOPPLERGEIST_CPA_BACKEND=python
```

The default for each selector is `auto`; invalid selector values fail explicitly.
The legacy checkpoint upgrade requires all three Python backends and its original runtime and input controls.
Ordinary checkpoints include the selected backend and implementation identities and reject an implementation mismatch.

### Recorded-input scoring comparison

Install the GitHub CLI (`gh`) before restoring the published input bundles; the restoration script uses `gh release download`.
Use a fresh output directory and preserve the baseline checkout for the entire comparison.
The commands compare the checked-out source against `fec518e5`; use source `41d0646` to repeat the native-computation table's measured optimization checkpoint.
Build the extensions in that checkout first. Another source revision or runtime produces a new comparison.
The following commands freeze the same real observations and source-informed receiver/clock workload for both implementations:

```bash
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONPATH=src
git worktree add --detach ../DOPPLERGEIST-perf-baseline fec518e51f14afe8d36203e6c5e1be1277dea14e
python scripts/restore_artifacts.py --bundle data-adsb-derived --bundle data-terrain
python scripts/prepare_reference_upload.py --data-root data --output benchmark-inputs
for width in 10 120; do
  python scripts/benchmark_prepared_measurements.py prepare \
    --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
    --index benchmark-inputs/reference-region.sqlite \
    --clock-half-width-s "$width" --output "benchmark-inputs/point-$width.json"
  python scripts/benchmark_prepared_measurements.py compare \
    --fixture "benchmark-inputs/point-$width.json" \
    --baseline-source ../DOPPLERGEIST-perf-baseline/src --current-source src \
    --repeats 2 --require-current-native --require-current-native-acoustic \
    --output "results/native-scoring-$width"
done
```

The comparison alternates arm order in fresh worker processes.
It compares every candidate, diagnostic, support record, ranking, and logical retention row exactly before reporting a speedup.
Timed runs preserve the original numerical functions so guarded production optimizations remain active.
Unmeasured scalar and native-ridge call counts are `null`, not zero.
The native acoustic solver exposes an internal success counter without wrapping its numerical functions.
Native ridge calls are checked in a separate diagnostic worker:

```bash
python scripts/benchmark_prepared_measurements.py diagnose \
  --source src --fixture benchmark-inputs/point-120.json \
  --instrument-numerics --require-native --require-native-acoustic \
  --output results/native-scoring-operations
```

Numerical wrappers can disable guarded caches, so diagnostic counts describe that execution path only.
Diagnostic timings do not establish a production speedup.
The workflow checks that this diagnostic worker preserves the canonical worker's complete scientific outputs.
Input loading is reported separately, and the RSS measurement covers the worker lifetime through scoring.

The complete-fit cache shares its existing 4 MiB digest-key and serialized-payload budget with validated batch ceilings.
Python object headers and dictionary bookkeeping require additional memory.
The separate screening cache permits at most 8 MiB of conservatively charged private loss evidence per scoring context.
It never retains a candidate's ranking cutoff: every call applies its current cutoff and group count.
These caches help repeated workloads; first-use hashing and serialization have a cost, so complete-job measurements decide whether they help a workload.

### Complete HTTP methodology

The `Real performance comparison` workflow also replays the complete recording through the HTTP application.
Select an exact baseline commit and enable the regional comparison.
Its three pairs run in baseline/current, current/baseline, and baseline/current order, with fresh directories and one shared MP3, request, operator configuration, index, and terrain set.
Both arms use the same pinned CPU and one numerical thread.
Input restoration, index preparation, and MP3 encoding happen before the timed arms.

Every pair must pass whole-recording intake, discovery, acquisition, search, refinement, and decision checks.
The comparison requires exact scientific JSON, logical SQLite contents, decoded audio, CSV/array values, and PNG pixels.
Only declared path, run identity, timing, and native implementation metadata are normalized; scientific floats have no tolerance.
Medians are emitted only after all pairs pass, and the individual samples remain available.
Profiling runs separately and never contributes to timing medians.

The original MP3 retains its 17-ridge/15-group control.
A different encoding requires an explicit declaration and the canonical WAV identity; it cannot inherit historical event counts or timing claims.
Both new-encoding arms must still process the complete recording, consider every group, and produce exactly equal outputs.
These regional computation controls use source-informed bounds and clock evidence.
They do not establish independent location accuracy, nationwide completion time, or a cold-cache acquisition speedup.

## Explicit terrain and tile workers

A real MP3 replay from [Eclipse Soundscapes ESID 762](https://zenodo.org/records/21786378)
compared one versus six tile workers with the same cached all-aircraft April 8
index, explicit Copernicus DEM and EGM2008 geoid. The test used a source-informed
Texas regional box `[-98.98, 30.29, -98.73, 30.47]`, the provisional
`04:26:49–04:28:49Z` recording-start window, 750 m coarse spacing and 150 m
finalist spacing. It used source `f898ee1` with native backends on the homelab;
all runs searched 20 tiles and 852 grid points. Inputs and clock are not an
independent accuracy benchmark.

In three alternating pairs (1/6, 6/1, 1/6), complete upload wall times were
13.971, 13.094 and 13.301 s with one worker, and 12.425, 12.950 and 12.280 s
with six: medians **13.301 vs 12.425 s**, or **1.07x** on this workload.
Median search-stage times were **6.440 vs 5.713 s**. All event lists, 105
ordered candidates and inconclusive decisions matched exactly; the first pair
also had 5,495 identical scored retention rows and identical assessed-mode IDs.
Each run reported complete requested geographic search and available data. This is not a
national runtime estimate. A separate 212-point comparison was slower with six
workers: 16.84 vs 17.47 s end to end, one pair.

Coverage accounting differed: serial global-floor pruning recorded 82,374
unknown and 8,332 rejected trials, while parallel per-tile work recorded 26,955
unknown and 63,751 rejected. Both sums were 90,706 and the best discarded
score bound was identical, but the individual diagnostics and discarded counts
were not identical. Different workloads may have different outcomes. The saved
real-input reports and job artifacts are on the homelab under
`/srv/homelab/datasets/dopplergeist-explicit-terrain-benchmark-20261103/`.
