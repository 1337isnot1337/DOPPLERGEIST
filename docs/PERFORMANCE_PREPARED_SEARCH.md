# Prepared flight data and exact pipeline optimization

The final runtime's dense-search CI workload falls from **38.374 to 30.399
seconds**, or **20.78% less elapsed time**. The earlier local search comparison
falls from **33.986 to 26.794 seconds**, or **21.16% less time**.
A completed intermediate HTTP series falls from **58.233 to 52.668
seconds**, or **9.56% less time**, after exact refinement reuse is added.
These are separate measured workloads. Their speedup ratios must not be multiplied.

The finalized runtime is `b98a0fa3e9dc8a204ffddf00f0bc411c9206d868`.
Earlier measurements retain their original source identities:

- Baseline: `994d1ee48e25df6d30b23a356bba8f6502d8b7f6`, including PR #258.
- Dense search and initial HTTP: `ecb1726fb9872d0060265014aa830e598b4dd3b4`.
- Independent CI and portable component baseline: `c0c9e798f47b547ab581fa473912e7218e3b4c3e`.

The [measurement record](../benchmarks/results/prepared-flight-search-20261103.json)
contains individual samples, source identities, preparation costs, rejected
experiments, and comparison scope. Later changes on `main` are outside these pins.

## Dense search and independent replication

| Timed work | Baseline median | Current median | Speedup |
| --- | ---: | ---: | ---: |
| Complete measured search, wall | 33.985746 s | 26.793586 s | 1.268× |
| Complete measured search, CPU | 33.968096 s | 26.784584 s | 1.268× |
| Flight query and distance sieve, wall | 6.569945 s | 2.237149 s | 2.937× |
| CPA, associations, scoring and retention, wall | 27.846495 s | 24.058635 s | 1.157× |

Stage medians do not sum to the median of the complete search.
The query traverses 4,694 observed trajectories and 713,100 samples.
The unchanged sieve selects 1,354 trajectories and 357,324 samples.
The scorer evaluates 16,101 candidates and retains 100.
The recording supplies 16 independent event groups and 724 ridge samples.
All six runs return exactly equal complete outputs and logical retention records.

This workload uses one source-informed receiver point and one association-anchor
partition, without a recording-start clock prior. The regional archive has
incomplete coverage. The result does not establish independent location accuracy,
complete daily search, or national completion time.

The timer includes the initial flight query, distance sieve, associations,
scoring, and retention writes. It excludes imports, index metadata, event
preparation, downloads, terrain sampling, audio discovery, and refinement.
Both arms read the same prepared database; baseline reads its original payloads.

[Independent CI](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41701995581)
repeats the dense comparison on another machine: **38.451 to 30.292 seconds**,
or **1.269×**. Its three alternating pairs produce exactly equal complete outputs.
CI pins one available CPU and rebuilds the original index with baseline code.
That earlier workflow passes 133 recorded-input checks and four fallback checks,
without skips. Separate installation and static checks pass on Python 3.11 and 3.14.

[Final-runtime CI](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41708828025)
repeats all comparisons at `b98a0fa3`. Prepared dense-search wall medians are
**38.373940 versus 30.398725 seconds**, or **1.262× / 20.78% less time**.
CPU medians are 38.329208 versus 30.363599 seconds. Worker-lifetime peak RSS
medians are 541.410 versus 518.855 MiB. Query/sieve medians are 8.150010 versus
2.962375 seconds; scoring/retention medians are 30.179885 versus 27.415653 seconds.
All three pairs preserve complete outputs. The final workflow passes **164
recorded-input checks and four Python-fallback checks**, without skips.
[Final installation checks](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41708837646)
also pass on Python 3.11 and 3.14. HTTP CI jobs remain outside this branch's push gate.

## Full HTTP and refinement measurements

| Complete HTTP series | Baseline median | Current median | Result |
| --- | ---: | ---: | --- |
| Initial search changes | 54.020778 s | 54.855469 s | 1.55% more time |
| Search plus refinement reuse | 58.233276 s | 52.668349 s | 9.56% less time |

Each series uses three fresh alternating pairs. The initial series establishes
**no complete-pipeline speedup**. Its narrower request has little dense-query cost;
producer search timing is essentially unchanged, at 22.759 versus 22.739 seconds.
Each current run in the later refinement series is faster than its paired baseline.

Every pair passes exact scientific JSON, logical SQLite, decoded audio, CSV-array,
and PNG-pixel comparisons. All uploads traverse intake, discovery, search, and
refinement, returning the same 23 candidates and 17 event records.
The request remains `inconclusive / search_incomplete`: 40 refinement points are
searched and 80 are skipped. All 15 independent event groups are considered.
Faster execution does not establish complete coverage or an accepted location.

The later series adds these exact files to the earlier runtime:

- `matching.py`: `8d7c6b8f7bf83f06203640df32136d1dbe625cd558270bc7b4184305f9024826`.
- `terrain.py`: `9390f39b25f41ee03e567b3c9c83fce9bf0a0285dc90f842124a39c93e43c8b2`.

The request, complete recording, index, terrain, and budgets remain unchanged.
Each verifier checks source stability. Verifier elapsed time includes service
startup, polling, shutdown, and artifact checks. Phase observations have one-second
polling uncertainty. Unchanged intake code also varies between runs, so the entire
HTTP saving cannot be attributed to terrain alone. Compare paired arms within a
series; absolute times across separate experiments have different host conditions.

A separate complete sensitivity-profile comparison isolates refinement reuse.
Median wall time falls from **9.064 to 8.178 seconds**, or **9.78% less time**.
Median CPU time falls from 9.054 to 8.175 seconds.
All six runs return exactly equal complete profiles and retain all **46 solves**.
Each performs 36,835 native acoustic calls. Input loading and earlier finalist
refinement are outside this component timer.

Pixel reuse applies to `terrain.Terrain` with local operator GeoTIFF files.
The online provider's `data_access.CachedTerrain` is unchanged. Profile-local
transformer reuse applies with either provider. The HTTP measurement uses local
rasters and makes no online-provider throughput claim.

The final `b98a0fa3` HTTP series has **two complete exact pairs and five verified
upload receipts**. Its third pair was interrupted before the last receipt.

| Completed final-runtime pair | Baseline | Current | Paired ratio |
| --- | ---: | ---: | ---: |
| 1, baseline then current | 58.389875 s | 51.997905 s | 1.122927× |
| 2, current then baseline | 57.154603 s | 54.008309 s | 1.058256× |

The unpaired third baseline took 59.612323 seconds and remains in the record.
The interrupted current attempt has no valid elapsed-time sample. The incomplete
series has `speedup: null`; no three-pair aggregate is reported.
The session's final exit status could not be recovered. These partial observations
do not establish a three-pair speedup for the final runtime. The completed
refinement series above remains the measured full-HTTP result.

## Discovery experiment and final correctness

The discovery normalization prototype reduces median stage wall time from
**6.156 to 5.761 seconds**, or **6.43% less time**, across three alternating pairs.
It processes the complete 3,600.1845-second saved PCM recording and writes the
normal JSON, 17 CSV files, and summary PNG. Decoding and search are excluded.
Pre-call imports are excluded; lazy plotting imports inside discovery are included.
Median peak RSS increases from 159.953 to 165.883 MiB, a 5.930 MiB tradeoff.

This timing precedes the final guards for C-contiguous arrays and canonical NumPy
functions. It is **not a separate timing claim for the final runtime**.
The final implementation passes a new full-recording comparison: all 60 spectra
match in bytes, dtype, shape, strides, and mutability. Complete event records,
CSV bytes, and diagnostic pixels also match. Eighteen portable real-PCM tests
cover odd/even medians, custom hooks, data types, layouts, and short inputs.
The final combined HTTP series supplies two exact integration pairs; its planned
three-pair timing series remains incomplete.

## What changes

- **Prepared trajectory inputs:** indexes store numeric constructor inputs beside
  the original compressed observations. Values follow original decoding and
  normalization, preserving rounding, inferred velocities, and altitude labels.
- **Vectorized trial bounds:** masks and conservative bounds operate across
  eligible clocks. Event order, upward rounding, strict rejection, diagnostics,
  and custom-function fallbacks remain unchanged.
- **Native acoustic reuse:** the solver reuses exact spline intervals and exact
  fixed points. Retired samples still contribute to the global stopping condition.
  Tolerances and iteration limits remain unchanged.
- **Refinement reuse:** each profile shares its unchanged coordinate transformers.
  Each local sampler retains at most 1,024 exact single-pixel masked reads.
  Pixel selection, raster precedence, missing data, geoid correction, and returned
  array mutability remain unchanged. Changed or custom readers use original reads.
- **Discovery normalization:** contiguous frequency columns accelerate median
  reductions for eligible finite float32 arrays. Returned layout and every
  arithmetic expression remain unchanged. Other inputs use the original path.

Prepared data uses little-endian float64 arrays and bounded JSON metadata, with
no executable object format. Tracks remain independently mutable. Original
payload integrity checks remain mandatory, including cache hits. Prepared hashes
and implementation identity must match; incompatible optional data uses original
payloads. Runtime identity includes normalization code, dependencies, Python, and
CPU capabilities. Operators can prepare a new copy after changing the runtime.
The acoustic scratch allocation is bounded at 2 MiB; larger requests keep the
original native calculation. No optimization changes search budgets or resolution.

Local validation includes 70 focused search tests, 13 refinement/terrain tests,
and 18 discovery tests, without skips. The refinement cases cover closed,
replaced, changed, and custom readers, masked pixels, bounded eviction, and hooks.

## Measurement method

1. Freeze real observations, request settings, source hashes, and workload counts.
   Keep complete outputs so comparisons can detect changed scientific work.
2. Measure the full workflow first. Profile separately to locate substantial costs;
   exclude profiler instrumentation from reported timing pairs.
3. Optimize repeated work while preserving operations, bounds, and scenario counts.
   Reject faster results that omit candidates, diagnostics, arrays, or coverage records.
4. Compare full values exactly before accepting timings. Include ordered inventory,
   candidate fields, logical retention rows, and array bytes and layouts where relevant.
5. Use fresh interpreters or services in alternating baseline/current order.
   Use one numerical thread and pause other team benchmarks during each comparison.
6. Record wall time, CPU time, memory, preparation, and storage separately.
   Report workload-specific medians and all samples; never multiply component ratios.

Local runs do not pin CPU affinity or flush operating-system caches. Unrelated
host load is uncontrolled. CI timing pins one available CPU. Three pairs are a
small performance sample, so retain the workload and variability qualifications.
Native backends and prepared decoding must actually execute when required.
Every measured current dense run records 4,694 successful prepared decodes.

## Rejected and deferred experiments

| Experiment | Observed result | Decision |
| --- | --- | --- |
| FFmpeg `filter_threads=1`, three pairs | 8.195 → 8.644 s median | Slower; rejected |
| FFmpeg `flush_packets=0`, one pair | 8.444 → 7.751 s | Below the declared 10% time-reduction gate; stopped |
| FFmpeg direct-file output, one pair | 7.689 → 7.915 s | Slower; rejected |
| Native ridge IRLS fixed points, five pairs | 0.212 → 0.226 s median | Slower; rejected |

Decoder trials preserve all 57,602,952 PCM bytes, sample counts, and peak amplitude.
The IRLS trial preserves every result byte from 36,835 actual calls, but this
kernel is too small to dominate the full refinement profile. These changes are
not integrated. Single-pair results are screening observations, not stable medians.
An earlier nominal-solve reuse prototype was simplified to transformer reuse;
all 46 final solves remain, with fewer custom-hook guards.

Raw-STFT overlap reuse is **unimplemented and unmeasured**. The real recording has
14,100 spectral frames but 7,197 distinct aligned windows: 6,903 transforms repeat.
However, raw spectrogram work occupies only 0.693 profiled seconds. At equal
per-frame cost, perfect reuse of the repeated 48.96% would save about 0.339 seconds.
This idealized estimate helped prioritize normalization instead. It is not a cache
speedup. A future cache must preserve windows and recompute chunk-dependent statistics.
Bounded chunk concurrency also remains unimplemented; results must enter merging
and harmonic grouping in original order.

An earlier decoding-only experiment measured 7.929× on 4,694 trajectories against
`8bd72aed`. It excludes SQL reads and cache hits, and does not describe full search.

## Preparation cost and operator use

| One-time preparation | Result |
| --- | ---: |
| Wall / CPU time | 7.418266 / 7.370144 s |
| Original SQLite file | 41,385,984 bytes |
| Prepared SQLite copy | 85,929,984 bytes |
| Added storage | 44,544,000 bytes |

Preparation copies the index, decodes canonical observations, writes the optional
representation, and commits. The original remains unchanged. Input identity,
source records, and coverage declarations stay equal. Original payloads remain
available for compatibility and fallback.
The timer excludes imports and separate whole-file integrity verification.
That verification reads the source before timing, warming its file pages.
Two comparable searches recover the measured preparation cost. This estimate
uses the combined code-and-format saving, not an isolated format benefit.

Prepare an existing index in the serving runtime. Choose a new destination:

```bash
python scripts/prepare_flight_index.py \
  --index /absolute/path/original.sqlite \
  --output /absolute/path/prepared.sqlite
```

Set the operator configuration's index path:

```json
{"flight_indexes": ["/absolute/path/prepared.sqlite"]}
```

Keep the existing terrain, coverage, and search configuration. Start the service
as described in [PRODUCT.md](PRODUCT.md). New indexes include prepared inputs by
default. Unprepared indexes remain usable; preparation does not expand coverage.

## Reproduce the comparisons

Use the final checkout containing these scripts, Python 3.12, GCC, and the same
dependencies for all source trees. Build the pinned dense runtime and baseline:

```bash
export PYTHONPATH=src
export CC=gcc
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
python -m pip install 'setuptools>=68'
python -m pip install --editable '.[test]'
git worktree add --detach ../dopplergeist-baseline \
  994d1ee48e25df6d30b23a356bba8f6502d8b7f6
git worktree add --detach ../dopplergeist-dense \
  ecb1726fb9872d0060265014aa830e598b4dd3b4
(cd ../dopplergeist-baseline && python setup.py build_ext --inplace)
(cd ../dopplergeist-dense && python setup.py build_ext --inplace)
```

Restore public observations. Build the original index with baseline code, then
prepare a common copy with the measured dense runtime:

```bash
python scripts/restore_artifacts.py --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=../dopplergeist-baseline/src \
  python scripts/prepare_reference_upload.py --data-root data --output benchmark-inputs
python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --index benchmark-inputs/reference-region.sqlite \
  --reference-report evidence/results/reference-local/report.json \
  --full-day --max-tracks 2000 --max-samples 500000 --max-candidates 20000 \
  --anchor-window-s 1788864888.7151732 1788865236.7214916 \
  --include-track-query --output benchmark-inputs/dense-query.json
python scripts/benchmark_prepared_flight_search.py prepare-index \
  --source ../dopplergeist-dense/src --index benchmark-inputs/reference-region.sqlite \
  --destination benchmark-inputs/reference-region-prepared.sqlite \
  --output results/flight-preparation.json
python scripts/benchmark_prepared_flight_search.py compare \
  --fixture benchmark-inputs/dense-query.json \
  --baseline-source ../dopplergeist-baseline/src --current-source ../dopplergeist-dense/src \
  --baseline-index benchmark-inputs/reference-region-prepared.sqlite \
  --current-index benchmark-inputs/reference-region-prepared.sqlite \
  --preparation-report results/flight-preparation.json \
  --repeats 3 --timeout-s 600 --output results/performance-prepared-flight-search \
  --require-native --require-native-acoustic --require-current-prepared
```

### Bounded HTTP replay

Use the existing `benchmark-inputs` directory from the preparation steps above.
The measured upload is the archived **43,202,925-byte MP3**, with SHA-256
`707083f0344823eeea7f130faec6c22b6628b8b9fea04d026915d93df9a07b15`.
Place that exact file at `benchmark-inputs/recording.mp3`. The public WAV or a new
MP3 encoding is a **new workload**: decoding cost, decoded samples, and downstream
results can differ. Do not attribute the archived timing results to that substitute.

Set the exact bounded request and one-worker operator configuration. Both arms
must read the same prepared index. Keep the restored terrain paths and the
preparation helper's search budgets unchanged:

```bash
cp /absolute/path/archived-recording.mp3 benchmark-inputs/recording.mp3
python - <<'PY'
import hashlib
import json
from pathlib import Path

inputs = Path("benchmark-inputs")
recording = inputs / "recording.mp3"
assert recording.stat().st_size == 43202925
with recording.open("rb") as stream:
    assert hashlib.file_digest(stream, "sha256").hexdigest() == "707083f0344823eeea7f130faec6c22b6628b8b9fea04d026915d93df9a07b15"
request = {
    "schema_version": 1,
    "search": {"coverage": "conus", "bounds_wsen": [-73.545, 40.865, -73.505, 40.895]},
    "time_window": {
        "start_utc": "2026-09-08T20:17:20Z", "end_utc": "2026-09-08T20:17:40Z",
        "source": "user",
        "source_detail": "Source-informed regional runtime control using the historical fitted clock and the published four-point receiver region; not independent timing evidence or a location-accuracy evaluation.",
    },
}
operator = json.loads((inputs / "operator.json").read_text())
operator["flight_indexes"] = [str((inputs / "reference-region-prepared.sqlite").resolve(strict=True))]
operator["search_workers"] = 1
assert operator["search_budget"] == {"spacing_m": 2000, "tile_cells": 16, "top_k": 20,
                                     "refine_spacing_m": 500, "refine_finalists": 3}
assert operator["refine_finalists"] == 3 and operator["offline"] is True
for name, value in (("request.json", request), ("operator.json", operator)):
    (inputs / name).write_text(json.dumps(value, indent=2) + "\n")
PY
python scripts/benchmark_real_bounded_comparison.py \
  --baseline-source ../dopplergeist-baseline/src --current-source src \
  --inputs benchmark-inputs --output results/performance-bounded-http \
  --repeats 3 --timeout-s 900
```

This command runs three alternating pairs with fresh services and jobs. It
requires `inconclusive / search_incomplete`, complete workflow receipts, and exact
scientific and array comparisons. Preparation is outside the timer. The controller
preserves logs and receipts, and reports a speedup only after all requested pairs
complete successfully. An interrupted run must remain an incomplete series.

### Refinement and discovery

For refinement, build the public component baseline. The committed fixture
contains the real finalist, unchanged discovery observations, and provenance:

```bash
git worktree add --detach ../dopplergeist-component-baseline \
  c0c9e798f47b547ab581fa473912e7218e3b4c3e
(cd ../dopplergeist-component-baseline && python setup.py build_ext --inplace)
python scripts/benchmark_real_refinement.py compare \
  --baseline-source ../dopplergeist-component-baseline/src --current-source src \
  --index benchmark-inputs/reference-region-prepared.sqlite --terrain-root . \
  --repeats 3 --require-native --require-native-acoustic \
  --output results/performance-refinement
```

This timer covers the complete profile and its exact-fit cache, excluding
imports, index lookup, terrain construction, event preparation, and earlier
finalist refinement. Every arm writes its full result and source hashes.
The portable wrapper has AST, CLI-help, and static validation. The reported
component timings came from the earlier tested harness on these same recorded
inputs; the optional portable-wrapper timing smoke was canceled.

Discovery requires a saved real service job with decoded PCM, intake metadata,
and discovery artifacts. Replace the job path with that existing directory:

```bash
python scripts/benchmark_real_discovery_normalization.py compare \
  --baseline-source ../dopplergeist-component-baseline/src --current-source src \
  --job /absolute/path/saved-job --pairs 3 \
  --output results/performance-discovery
```

The discovery script checks all spectra outside timing. It continues three-pair
screening only when its first exact pair clears the declared improvement threshold.
The completed HTTP comparisons supply separate integration checks.
Use new output directories. Commands fail on unequal outputs or unused required
backends. Their reports contain samples and medians; workers preserve complete
comparison outputs. Keep profiling separate and avoid competing benchmarks.

The [performance workflow](../.github/workflows/real-performance.yml) contains
recorded-input regression commands and the dense comparison. It uploads the
preparation report and pins one CPU for timing. Local full HTTP replays remain
separate from the branch's automatic dense and static CI gates.
