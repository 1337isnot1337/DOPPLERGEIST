# Exact throughput changes

This guide explains the implementation and the repeated regional HTTP method.
A speed measurement qualifies only after the strict scientific comparison passes.
The [historical performance report](PIPELINE_PERFORMANCE_2026-11-03.md) retains its original sources, measurements, arithmetic qualifications, and incomplete runs.

## Complete regional upload: 1.40× faster

Three alternating pairs process the complete 43,202,925-byte reference MP3 through the HTTP pipeline.
The [HTTP measurements](../benchmarks/results/exact-throughput-http-final-20261103.json) retain every arm, control, phase observation, and comparison result.
Median wall time falls from **103.9694 to 74.0442 seconds**, a **1.404×** speedup and **28.78%** reduction.
Median process-and-child CPU time falls from **103.7595 to 73.9053 seconds**.
Baseline wall times range from 101.4740–110.0640 seconds; optimized times range from 71.8078–76.8914 seconds.

The baseline is pinned main `21262e031388b3a5a8dd75979b2dc851608499b2`.
The measured optimized source is local `4f528cdfb5ca424aa54dc94d552bcf6b939ba66a`.
Its production source matches public commit [a21edb95](https://github.com/1337isnot1337/DOPPLERGEIST/commit/a21edb95e39e67113b8fcd721aa0f3556919cf9d).
Later integration through main `7565d8` changes no production source or benchmark harness.

All three comparisons have **zero scientific differences**.
Each compares 20 job JSON artifacts, three root JSON artifacts, and the complete logical SQLite ledger.
Each ledger contains 29,738 bounds, 852 records, 12 stages, and one run.
Comparison excludes only declared implementation, timing, and path metadata; numerical differences have no tolerance.

Every run retains 17 ridge records, considers all 15 independent groups, and returns 23 candidates.
Each processes two coarse tiles, four coarse points, and 40 refinement points under the same budgets.
Every run returns `inconclusive / search_incomplete`.
The experiment measures runtime and computational agreement, without establishing a location.

These runs use Python 3.12.3, SQLite 3.45.1, CPU 4, one numerical thread, and tmpfs output.
The source trees, input bytes, dependencies, verifier, and plotting policy stay fixed across all six runs.
Optional event-detail plots are disabled by both source defaults and the explicit benchmark policy.

A separate single pair compares starting main `1f60cb5` with the first optimized run in this environment.
Wall time falls from **141.0466 to 76.8914 seconds**, a **1.834×** speedup, with zero scientific differences.
This comparison includes upstream improvements integrated during the task.
The repeated comparison against `21262e` measures the additional gain from this implementation.
The starting-main pair stays outside the repeated-pair statistics.

## Repeated scoring and fitting controls

The [final point-scoring report](../benchmarks/results/exact-throughput-scoring-final-20261103.json) compares main `21262e` with the integrated optimized source.
Each workload uses three alternating pairs in fresh processes, pinned to CPU 8 with one numerical thread.
Input loading is outside the scoring timer.

| Point-scoring workload | Associations | Baseline CPU median | Optimized CPU median | Speedup |
| --- | ---: | ---: | ---: | ---: |
| Dense, `previous-fit` | 1,927 | 6.5387 s | 5.0391 s | 1.298× |
| Sparse, `offset` | 206 | 1.5713 s | 1.3252 s | 1.186× |

All 12 runs preserve every scored candidate, diagnostic, count, ranking, retention payload, and logical SQLite row.
The report retains every trial and range.

The separate [native batch comparison](../benchmarks/results/exact-native-batches-20261103.json) covers 80 real batches and 1,680 clock fits.
Each timed arm performs ten complete passes, with three alternating pairs inside one process.
Median CPU time falls from 1.18284 to 0.23050 seconds, a **5.13×** component speedup.
All diagnostics match exactly, and every verified clock fit enters the native kernel.
This timing includes batch preprocessing but excludes input loading and acoustic propagation.
It does not measure the complete pipeline.

## Exact caches and current retention floors

Each scoring call owns its fit caches.
Context-local state separates jobs, nested calls, and later evaluations.
The [matching implementation](../src/dopplergeist/matching.py) preserves exact parameter values and measured input content in cache keys.
Batch keys also preserve array types, shapes, strides, and alignment.
These details matter because storage layout can change floating-point reduction order.

The [screen cache](../src/dopplergeist/acoustic_screen.py) stores loss bounds.
Each call applies the current retention floor and group count to those bounds.
A changed floor therefore produces a new decision from the same numerical evidence.
The separate ceiling cache uses complete diagnostic content and classification parameters.
Unsupported representations retain the ordinary calculation.

Complete fit batches use at most 4 MiB of keys and snapshots, with 4,096 entries.
Python container headers and dictionary bookkeeping require additional memory.
Screen evidence has an 8 MiB limit.
Acoustic arrays and prepared measurements have separate limits of 32 MiB and 4 MiB.
Cache hits return independent diagnostics or arrays.
Total process memory also includes live tracks and temporary allocations.
The [batch implementation](../src/dopplergeist/batch_ridge.py) excludes fallback results and exceptions from its complete-fit cache.
Custom measurement and event containers bypass that cache.
Changing the batch fitter clears its previous snapshots.

## Trajectory reuse and finalist lookup

The [index implementation](../src/dopplergeist/data_access.py) retains up to 32 MiB of decoded trajectory snapshots and 2,048 entries per index.
Every fetched payload passes its checksum before reuse.
Each caller receives an independent track.
Admission stops before a large scan repeatedly evicts entries that the same scan already used.
Initial serialization can make a cold query slower.

[Finalist refinement](../src/dopplergeist/automatic.py) requests the required segment identifiers directly in SQL.
It avoids decompression of unrelated flights.
Named lookup retains the original spatial and time envelope, whole segments, sample limits, and conservative fallback for old indexes.
Custom query adapters retain their existing behavior.
Missing segments still prevent refinement.
The sensitivity profile reuses the finalist trajectories within the same decision.

## Optional native fitting

The native kernel performs the same six robust fitting iterations, constraints, and diagnostic calculations.
It preserves the tested NumPy pairwise reduction order, expression grouping, and Python scalar-power semantics.
Floating-point contraction is disabled.
Compatible contiguous batches also use this kernel through the existing batch path.
Unsupported input representations retain Python calculations.
The scalar path also preserves explicit NumPy error policies.

The extension is optional.
A missing compiler can produce a working Python installation.
A successful installation therefore does not establish native use.
The benchmark records the actual backend identity and native binary hash.
Its explicit native expectation rejects an unintended fallback.
The [native source](../src/dopplergeist/_native_ridge.c) and [build declaration](../setup.py) define this path.

Set `DOPPLERGEIST_RIDGE_BACKEND=python` before process startup to select the Python fitter.
This setting supports the existing legacy checkpoint migration command.
Legacy batch arithmetic retains its separate cache key and never enters the native batch kernel.
The migration guard still rejects a loaded native backend.
See [checkpoint continuation](PRODUCT.md) for the existing limits.
Actual migration of the historical stopped job was not rerun because that job was unavailable.

### Installation and regression checks

After PR225 integration, the local gate passed 48 recorded-input checks for native fitting, backend selection, legacy arithmetic, caches, screening, and complete batches.
The full CPA fixture passed its unchanged 20,000-candidate limit without truncation.
The corrected backend-selector check also passed separately after its installed-package path fix.
[Hosted CI](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41679250198) passed all 36 packaged regression checks on both Python 3.11 and 3.14.
Both jobs explicitly verified that the installed native extension loaded.
The extension remains optional; earlier packaging checks also verified installation with an unavailable compiler.
Native Windows execution remains unverified.

## Durable output with less I/O

An empty worker tile returns a small [retention descriptor](../src/dopplergeist/parallel_retention.py).
A tile with scoring evidence still uses its private SQLite ledger.
The parent checks the run, score kind, stage, and checksum.
It records the empty stage in its durable ledger before it writes the checkpoint.
Normal stage validation still governs interruption and resume.
The descriptor removes temporary databases without removing parent retention evidence.

[Compact checkpoint JSON](../src/dopplergeist/tiled_search.py) removes indentation from large checkpoint and support files.
Parsed values, payload checksums, and logical ledger content remain unchanged.
The exact comparator checks those values and logical rows.

The index digest cache compares device, inode, size, modification time, and change time.
Unchanged managed indexes reuse their digest.

A lock error triggers a checked full-file hash.
A receipt-write error preserves the digest from that hash.
This fallback preserves read-only index access and checks for source mutation or replacement.
This cache assumes the existing immutable-index contract.

## Earlier completed measurements

The [throughput results](../benchmarks/results/exact-throughput-20261103.json) preserve measurements from before the execution environment reset.
One fresh run per implementation recorded these wall times:

| Earlier comparison | Baseline | Intermediate optimized implementation | Single-pair speedup |
| --- | ---: | ---: | ---: |
| Starting main, `1f60cb5` | 170.49 s | 91.38 s | 1.87× |
| Comparison main, `0d6a923` | 123.12 s | 91.38 s | 1.35× |

The intermediate runtime was `3847be8`, with public equivalent `530db8b`.
Both comparisons had zero scientific differences and passed the full pipeline controls.
They retained 17 ridges, 15 independent groups, and 23 candidates.
These single pairs are separate from later repeated measurements.
The reset removed the temporary run files.
The report reconstructs only retrieved tool output.

The [broad scoring control](../benchmarks/results/exact-throughput-scoring-before-restart-20261103.json) completed three exact pairs.
Its median CPU time changed from 12.6933 to 12.3251 seconds, approximately 1.03×.
This improvement is modest relative to trial variation.
The narrow control lacked its final optimized result.
It has no completed three-pair median.
Component ratios cannot be multiplied into a workflow speedup.

## Reproduce three complete HTTP pairs

Use one interpreter and dependency environment from [SETUP.md](SETUP.md).
Restore the real inputs from [ARTIFACTS.md](ARTIFACTS.md).
Use new directories for preparation and results.

From the current repository root, prepare one index, operator file, and complete MP3:

```bash
python scripts/restore_artifacts.py \
  --bundle data-source --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=src python scripts/prepare_reference_upload.py \
  --data-root data --output results/throughput-inputs
python - <<'PY'
import json
from pathlib import Path
path = Path("results/throughput-inputs/operator.json")
operator = json.loads(path.read_text())
operator["search_workers"] = 1
path.write_text(json.dumps(operator, indent=2) + "\n")
PY
ffmpeg -nostdin -n -i data/source/reference-recording.wav \
  -ac 1 -ar 48000 -c:a libmp3lame -b:a 96k \
  results/throughput-inputs/reference.mp3
```

Encoder versions can change MP3 bytes.
Both implementations receive this same file.
The reference control requires 17 ridges, 15 groups, and consideration of every group.

Create the frozen baseline checkout:

```bash
git worktree add --detach ../DOPPLERGEIST-throughput-base \
  21262e031388b3a5a8dd75979b2dc851608499b2
DG_BASELINE_SRC="$(git -C ../DOPPLERGEIST-throughput-base rev-parse --show-toplevel)/src"
DG_CURRENT_SRC="$(pwd)/src"
```

For the Linux GCC build, run:

```bash
python -m pip install 'setuptools>=68'
CC=gcc LDSHARED='gcc -shared' python setup.py build_ext --inplace
PYTHONPATH=src python -c \
  "from dopplergeist.matching import RIDGE_FIT_BACKEND; print(RIDGE_FIT_BACKEND)"
```

Choose an allowed CPU for `DG_CPU`.
Keep the source and native binary unchanged throughout the experiment.
The runner requires source bytes to match their recorded Git commits.

```bash
DG_CPU=3
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
taskset -c "$DG_CPU" python scripts/benchmark_real_http_pairs.py \
  --baseline-source "$DG_BASELINE_SRC" --current-source "$DG_CURRENT_SRC" \
  --audio results/throughput-inputs/reference.mp3 \
  --request benchmarks/reference-regional-upload-request.json \
  --operator results/throughput-inputs/operator.json \
  --verifier scripts/verify_upload_http.py \
  --expected-detail-plots none \
  --expected-baseline-backend python --expected-current-backend native \
  --threads 1 --pairs 3 --timeout-s 7200 \
  --output results/throughput-three-pairs
```

The [pair runner](../scripts/benchmark_real_http_pairs.py) alternates baseline/current order and starts each arm in a fresh process.
It compares each completed pair before the next pair.
Its summary retains every trial, median, range, paired ratio, and exact-comparison count.
It stops on an error and preserves partial outputs and logs.
It refuses pooled statistics across changed environments, inputs, verifiers, or implementations.

The regional runner defaults to the original detail-plot policy, `all`.
The explicit `none` policy matches these current source defaults.
Source defaults and actual output counts must agree.
The comparator preserves exact scientific numbers and logical ledger rows.

### Reproduce the native batch component

The fixture exporter reads archived real ridges and observed flight trajectories.
After preparing the index above, run:

```bash
PYTHONPATH=src python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --reference-report evidence/results/reference-local/report.json \
  --index results/throughput-inputs/reference-region.sqlite \
  --clock-half-width-s 120 --max-tracks 5000 --max-samples 1000000 \
  --max-candidates 20000 --top-k 100 \
  --output results/throughput-inputs/real-cpa-full.json
PYTHONPATH=src DOPPLERGEIST_RIDGE_BACKEND=auto \
  taskset -c "$DG_CPU" python scripts/benchmark_real_native_batches.py \
  results/throughput-inputs/real-cpa-full.json \
  results/throughput-native-batches.json --repeats 3 --rounds 10
```

The full fixture contains 452 trajectories, 91,889 trajectory samples, 16 recorded ridges, and 100 CPA rows.
The batch control selects up to five available CPA rows per event and evaluates 21 clock trials per row.
Regenerate the fixture on another checkout because it contains an absolute index path.
Use a new output filename for each comparison.

## Interpretation limits

The regional bounds and recording clock come from the development hypothesis.
Incomplete aircraft coverage leaves the result `inconclusive`, with `search_incomplete`.
A completed workflow does not establish a location.

All reported HTTP runs stored output on tmpfs and used one CPU with one numerical thread.
Their ratios do not establish disk throughput or nationwide completion time.
A fresh process does not imply a cold operating-system cache.
Results from a replacement environment remain a separate measurement series.
