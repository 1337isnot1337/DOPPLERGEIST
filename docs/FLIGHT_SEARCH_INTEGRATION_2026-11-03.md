# Flight-search integration: 2026-11-03

## Final result and scope

Three alternating pairs measured **1.9060× CPU** and **1.9088× wall-time** speedups with identical scored outputs and retention. CPU time decreased **47.54%**. The initial flight query and distance sieve measured an **18.2399× CPU speedup**.

The baseline was `611dca2`, and the final timed implementation was `ec2ac0d`. Published runtime `9ae43d3350faabead4e766757bce582c1118bb69` equals local `5066357`. It preserves the measured hot path and adds main's CLI-bound handling outside this workload. Main `ae772` geographic bounds were already integrated. Four recorded geographic checks passed separately.

The integration combines [PR256](https://github.com/1337isnot1337/DOPPLERGEIST/pull/256), [PR262](https://github.com/1337isnot1337/DOPPLERGEIST/pull/262), and [PR266](https://github.com/1337isnot1337/DOPPLERGEIST/pull/266), excluding their terrain, discovery, and refinement additions.

## How the work decreases

- **Earlier time rejection:** partition bounds include both event tolerances, maximum acoustic delay, and outward rounding. Both tile drivers apply them before decoding. Selected trajectories remain complete, with unchanged gaps and derivatives. Unsupported cases retain broader queries.
- **Scoring reuse:** immutable measurements and bounded failed-prefix caches avoid repeated preparation and proved failures. Strict thresholds, candidate order, and unknown-trial status remain unchanged.
- **Native work:** batched fits reuse scratch space. CPA kernels preserve projection arithmetic and row order. Python fallbacks retain unsupported input behavior.
- **Prepared decoding:** optional numeric inputs accompany original observations. Integrity and implementation guards select the fast reader. Invalid optional data uses the original decoder. Returned arrays remain independently writable.

## Final three-pair measurements

The [combined evidence](../benchmarks/results/flight-search-integration-20261103.json) contains measurements and controls. Seconds are rounded to six decimal places.

| Pair | Order | Baseline CPU | Integrated CPU | Baseline wall | Integrated wall |
|---|---|---:|---:|---:|---:|
| 1 | Baseline, integrated | 37.038329 | 17.790956 | 37.172103 | 17.856148 |
| 2 | Integrated, baseline | 34.949517 | 18.336099 | 35.063260 | 18.368998 |
| 3 | Baseline, integrated | 34.892294 | 18.684989 | 35.006901 | 18.719616 |
| Median | | **34.949517** | **18.336099** | **35.063260** | **18.368998** |

Median query/sieve CPU decreased **6.661430 → 0.365213 seconds**. CPA through retention decreased **28.288002 → 17.970878 seconds**. Stage medians need not sum to the median total. Median peak resident memory decreased **456.488281 → 342.667969 MiB**, or **24.93%**, including imports and input preparation.

The query decoded **4,694 → 197 tracks** and **713,100 → 40,690 samples**. CPA rows decreased **944 → 95**, and association work units decreased **302,818 → 147,985**.

All runs preserved **16,101 scored candidate payloads**, ranked top 100, retention, and scoring support evidence. Trial evidence matched: **10,821 evaluated**, **6,768 rejected**, and **590,900 unknown**. Unknown trials remain unknown.

Early diagnostics decrease with time exclusion. The comparator separately proves that all **58 removed unsupported-track reports** lie completely outside the partition interval. Thus, full-result equality is false while scored-output equality is true.

**Historical integration result:** before mesh caching, `c542b0f` (local `589dd1b`) measured **38.275990 → 18.946476 CPU seconds**, or **2.0202×**. That earlier sample batch remains separate from the final comparison.

The earlier preloaded point comparisons exclude index traversal and track loading. Each used three alternating pairs and preserved complete outputs. Clock windows are source-informed.

| Clock half-width | Baseline median CPU | Integrated median CPU | CPU speedup |
|---|---:|---:|---:|
| ±10 seconds | 0.963035 s | 0.780835 s | 1.2333× |
| ±120 seconds | 5.890398 s | 4.781747 s | 1.2319× |

## Independent CI and additional mesh reuse

[CI performance](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41717270256) measured **1.9798×** dense CPU speedup for `c542b0f` against `611dca2`. It passed **286 recorded tests plus four subtests**, and **71 Python-fallback tests with one skip**. Its current-code index build writes prepared columns. Local dense timing used the older index. Their component ratios are separate evidence.

[Installation CI](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41717300088) passed on **Python 3.11 and 3.14**, including native validation. It tested merge `8cb65d9`, combining PR head `c542b0f` with base `ae772`.

The additional mesh cache reuses exact receive-time grids across aircraft. Acoustic evaluation remains aircraft-specific. Copies protect custom hooks from mutation. Changed helpers, layouts, and error policies bypass reuse. Retained arrays and keys have **4 MiB accounting** plus an entry-count limit.

Three alternating pairs measured **18.610048 → 18.000399 CPU seconds**, or **1.0339×**, against the integration without this cache. All outputs matched. One pair was slower. Nine recorded tests passed with all three Python backends. This small incremental ratio is separate from the directly measured final speedup.

## Controls and limits

The final dense runs used fresh interpreters on CPU 7, identical inputs, alternating order, and one thread per numerical library. Successful-operation counters verified native execution. Numerical functions remained canonical, without diagnostic wrappers.

Dense timing includes index traversal, distance sieve, CPA, association, scoring, and retention. It excludes downloads, imports, index metadata, event preparation, terrain sampling, discovery, and refinement. The workload has one source-informed receiver, 16 independent groups, and one association partition without a clock prior. It establishes neither national completion nor independent localization accuracy.

Initial local checks also covered flight decoding, scoring, and conservative bounds. No generated aircraft or audio inputs support these results.

Prepared-index outputs matched exactly. Preparation took **7.829230 seconds**, increasing storage **41,385,984 → 85,929,984 bytes**. Different CPUs prevent a prepared-index speedup claim.

The harness detects profiling, tracing, and Python 3.12+ monitoring before and after computation. Instrumented runs are timing-ineligible, including historically mislabeled cProfile summaries. `python scripts/check_benchmark_instrumentation.py` passed six Python 3.12 controls, including the previously missed cProfile case.

## Activation and checkpoint compatibility

From the selected branch checkout, install and verify all three optional native extensions:

```bash
CC=gcc LDSHARED='gcc -shared' python -m pip install 'setuptools>=68' --editable '.[test]'
export DOPPLERGEIST_RIDGE_BACKEND=auto DOPPLERGEIST_ACOUSTIC_BACKEND=auto
export DOPPLERGEIST_CPA_BACKEND=auto PYTHONPATH=src
python - <<'PY'
import dopplergeist
from dopplergeist import matching, native_acoustic, native_cpa
print(dopplergeist.__file__)
backends = (matching.RIDGE_FIT_BACKEND, native_acoustic.ACOUSTIC_BACKEND,
            native_cpa.CPA_BACKEND)
print(backends)
assert all(value.startswith('native-c-') for value in backends)
assert callable(matching._native_fit_irls_batch)
assert callable(matching._native_validate_ridge_events)
assert callable(native_acoustic._native.solve)
assert callable(native_cpa._native.select)
PY
```

Successful installation alone does not establish native availability. The scoring caches activate automatically. Partition narrowing activates automatically for eligible `~t0`/`~t1` tiles in subset `robust_ridge` searches without silence constraints. The scheduler creates these partitions after spatial subdivision exhausts its ability to resolve an association-candidate overflow. Unsplit queries remain broad.

Restart the service after installation or backend changes, using its existing arguments. There is no hot reload. Shutdown cancels active managed workers and preserves partial artifacts.

Saved-search identity includes code, backend identities, and index file hashes. A prepared copy changes the file hash despite preserving scientific input identity. Switching indexes or backends can invalidate checkpoint compatibility. The narrow legacy reference upgrade requires all three Python backends and its original runtime. Native activation is suitable for new jobs, subject to the existing data requirements.

## Reproduce the recorded fixtures and comparison

Use identical dependencies and new output paths. From the current checkout, restore the recorded data and create the baseline checkout:

```bash
git worktree add --detach ../dopplergeist-baseline-611dca2 611dca2
(
  cd ../dopplergeist-baseline-611dca2
  CC=gcc LDSHARED='gcc -shared' python setup.py build_ext --inplace
)
python scripts/restore_artifacts.py --bundle data-adsb-derived --bundle data-terrain
PYTHONPATH=../dopplergeist-baseline-611dca2/src \
  python scripts/prepare_reference_upload.py --data-root data --output benchmark-inputs
```

The explicit baseline import creates the older index representation used locally. CI instead runs the index helper against current code. Regenerate fixtures for the new index because its identity includes the resolved Parquet path.

```bash
for flight_clock_width in 10 120; do
  PYTHONPATH=src python scripts/benchmark_prepared_measurements.py prepare \
    --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
    --index benchmark-inputs/reference-region.sqlite \
    --reference-report evidence/results/reference-local/report.json \
    --clock-half-width-s "$flight_clock_width" \
    --output "benchmark-inputs/point-$flight_clock_width.json"
done
PYTHONPATH=src python scripts/benchmark_prepared_measurements.py prepare \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --index benchmark-inputs/reference-region.sqlite \
  --reference-report evidence/results/reference-local/report.json \
  --full-day --max-tracks 2000 --max-samples 500000 --max-candidates 20000 \
  --anchor-window-s 1788864888.7151732 1788865236.7214916 \
  --include-track-query --output benchmark-inputs/dense-query.json

export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
flight_benchmark_cpu="${FLIGHT_BENCHMARK_CPU:-$(python -c 'import os; print(min(os.sched_getaffinity(0)))')}"
taskset -c "$flight_benchmark_cpu" python scripts/benchmark_prepared_measurements.py compare \
  --fixture benchmark-inputs/dense-query.json \
  --baseline-source ../dopplergeist-baseline-611dca2/src \
  --current-source src --repeats 3 --timeout-s 600 \
  --include-track-query --clock-partition-query \
  --require-current-native --require-current-native-acoustic \
  --require-current-native-cpa --output results/new-dense-comparison
```

Set `FLIGHT_BENCHMARK_CPU` to a free permitted CPU. To reproduce the final implementation from GitHub, build published `9ae43d3350faabead4e766757bce582c1118bb69` and select its checkout through `--current-source`. Its measured computation matches local `ec2ac0d`. The historical integration and point measurements used `c542b0f`. For point comparisons, select `point-10.json` or `point-120.json` and omit both query flags.

For optional repeated index reads, create a separate prepared copy:

```bash
PYTHONPATH=src python scripts/prepare_flight_index.py \
  --index /absolute/path/to/reference-region.sqlite \
  --output /absolute/path/to/new-prepared-reference.sqlite
```

Use new output paths for each run. Compare prepared and original indexes on the same CPU before any further speedup claim. Inspect exact-output checks before timings. Profile the remaining scoring stage with a separate diagnostic run.

Select the prepared copy through the operator configuration's `flight_indexes` list, retaining the terrain and provider configuration. New index builds automatically attempt preparation. Existing indexes remain valid without conversion.
