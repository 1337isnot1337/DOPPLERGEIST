# Flight-search integration: 2026-11-03

## Result and scope

The integrated search used **50.50% less CPU time** on the recorded dense workload, with identical scored outputs and retention records. Three alternating pairs measured a **2.0202× CPU speedup** and **2.0232× wall-time speedup**. The initial flight query and distance sieve measured a **19.1969× CPU speedup**.

The baseline was main commit `611dca2`. The timed integration was published as `c542b0f`, with the same tree as local commit `589dd1b`. Later commit `5839b27` integrates geographic-bound changes from main `ae772`. Those functions are outside this dense workload. Four recorded geographic checks passed separately.

This work combines changes from [PR256](https://github.com/1337isnot1337/DOPPLERGEIST/pull/256), [PR262](https://github.com/1337isnot1337/DOPPLERGEIST/pull/262), and [PR266](https://github.com/1337isnot1337/DOPPLERGEIST/pull/266). It establishes a runnable integration and comparison against main. The measured version excludes their terrain, discovery, and refinement additions.

## How the work decreases

**Reject impossible times before trajectory decoding.** An association partition bounds the implied recording start of its first matched passage. The query expands that interval by both event tolerances and the maximum acoustic delay. Outward rounding preserves inclusive boundaries. Both serial and parallel tile drivers apply this bound before the index query.

The index still returns each selected segment in full. Sample times, gap boundaries, velocities, and spline endpoints remain unchanged. Silence constraints and unsupported input forms retain the broader query. A disjoint derived interval also retains the broader query.

**Reuse exact scoring inputs.** Immutable measurement preparation avoids repeated conversion and validation for each association. Bounded caches reuse failed trial prefixes only with matching scientific inputs and rejection evidence. Vectorized trial decisions preserve strict thresholds and candidate order. Native batches reduce repeated Python calls and reuse fit scratch space.

**Reduce CPA overhead.** Native kernels perform neighbor reduction and closest-approach projection with the established arithmetic and row order. The Python path remains available. Motion-support errors retain their explicit diagnostic meaning.

**Prepare repeated index reads.** An optional numeric representation stores exact decoder inputs beside the original compressed observations. The reader verifies source and prepared digests, implementation identity, metadata, and schema. Invalid optional data uses the original decoder. Each decoded track has independent writable arrays. Preparation preserves coverage and input identity.

## Three-pair measurements

The [combined evidence record](../benchmarks/results/flight-search-integration-20261103.json) contains the measurements and controls. Seconds in this table are rounded to six decimal places.

| Pair | Order | Baseline CPU | Integrated CPU | Baseline wall | Integrated wall |
|---|---|---:|---:|---:|---:|
| 1 | Baseline, integrated | 38.275990 | 18.946476 | 38.454555 | 19.006809 |
| 2 | Integrated, baseline | 34.727155 | 18.761897 | 34.815392 | 18.803821 |
| 3 | Baseline, integrated | 39.070329 | 20.972774 | 39.149456 | 21.022008 |
| Median | | **38.275990** | **18.946476** | **38.454555** | **19.006809** |

Median query/sieve CPU decreased from **7.216071 to 0.375898 seconds**. Median CPA, association, scoring, and retention CPU decreased from **30.603228 to 18.595927 seconds**. Independent stage medians need not sum to the median total. Median peak resident memory decreased from **457.238281 to 331.320312 MiB**, or **27.54%**. Memory includes imports and input preparation.

The query decoded **4,694 → 197 tracks** and **713,100 → 40,690 samples**. CPA rows decreased **944 → 95**, and association work units decreased **302,818 → 147,985**.

All runs produced exactly **16,101 scored candidate payloads**, the same ranked top 100, and the same retention records. Trial evidence matched: **10,821 evaluated**, **6,768 rejected**, and **590,900 unknown** trials. Unknown trials remain unknown. Support evidence during scoring also matched.

Early diagnostics differ because the query excludes irrelevant times. All **58 removed unsupported-track reports** describe complete emission intervals outside the proved partition interval. The comparator verifies this exclusion separately. Therefore, its full-result equality field is false, while scored-output equality is true.

## Controls and limits

Each run used a fresh interpreter on CPU 7, identical recorded inputs, and one thread for each numerical library. Run order alternated. Both versions used installed native extensions. The integrated counters recorded 206,740 successful native fits, 5,111 acoustic solves, and 63 CPA reductions per run. Timing used canonical numerical functions without diagnostic wrappers.

The timer includes index traversal, the distance sieve, CPA, association, scoring, and retention. It excludes downloads, imports, index metadata, event preparation, terrain sampling, audio discovery, and refinement. The workload uses one source-informed receiver, 16 independent groups, and one association partition without a recording-clock prior. This result establishes neither national completion nor independent localization accuracy.

Initial recorded checks passed: **94 flight tests plus four subtests**, **95 scoring tests**, and **71 Python-fallback tests with one skip**. An independent review also passed 20 focused prepared-index and partition-bound checks. No generated aircraft or audio inputs support these results.

The separate prepared-index comparison matched every result section exactly. Preparation took **7.829230 seconds** and increased storage from **41,385,984 to 85,929,984 bytes**. That comparison used CPU 6 against an earlier CPU 7 run. Its total runtime does not establish a prepared-index speedup.

## Reproduction

Use separate baseline and integration checkouts with identical dependencies. In each checkout, build the native extension:

```bash
CC=gcc LDSHARED='gcc -shared' python setup.py build_ext --inplace
```

From the integration checkout, run the comparison with the archived dense fixture and its original index:

```bash
taskset -c 7 env PYTHONPATH=src OPENBLAS_NUM_THREADS=1 \
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python scripts/benchmark_prepared_measurements.py compare \
  --fixture /absolute/path/to/dense-query.json \
  --index /absolute/path/to/reference-region.sqlite \
  --baseline-source /absolute/path/to/baseline-611dca2/src \
  --current-source "$PWD/src" --repeats 3 \
  --include-track-query --clock-partition-query \
  --require-current-native --require-current-native-acoustic \
  --require-current-native-cpa --output /absolute/path/to/new-comparison
```

For repeated index reads, create a separate prepared copy:

```bash
PYTHONPATH=src python scripts/prepare_flight_index.py \
  --index /absolute/path/to/reference-region.sqlite \
  --output /absolute/path/to/new-prepared-reference.sqlite
```

Use new output paths for each run. Compare prepared and original indexes on the same CPU before any further speedup claim. Inspect exact-output checks before timings. Profile the remaining scoring stage with a separate diagnostic run.
