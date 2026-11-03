# Flight checking and sieve performance

## Measured result

The clock-partition query bound removes impossible whole flight segments before
JSON decoding, spline construction, distance checks, and closest-approach work.
The dense recorded replay queried **197 segments instead of 4,694**. It preserved
all **16,101 scored candidate payloads**, the **100 retained results**, and the
complete retention records and trial evidence.

Three alternating baseline/current pairs gave these median CPU times:

| Scope | Baseline | This change | Speedup |
| --- | ---: | ---: | ---: |
| Index query and conservative distance sieve | 6.413 s | 0.398 s | 16.11x |
| CPA, association scoring, and retention | 26.500 s | 24.964 s | 1.06x |
| Complete measured hot path | 34.073 s | 25.356 s | 1.34x |

Each row has its own median; stage medians need not sum to the total median.
Total wall-time medians were 34.146 and 25.400 seconds. The baseline is
`b5ff48fe0e9d6e6feac7a4faf5268630f0c85d8b`, which already includes native ridge and
acoustic solvers and numeric flight decoding. Earlier gains are not credited here.

This replay uses the original recording's 16 prepared event groups and 724 ridge
samples, one source-informed receiver, a full-day regional observation index, and one existing
348-second association ownership partition. It is a computation benchmark, not
an independent location-accuracy or nationwide-throughput result.

Timing includes index traversal, track decoding, the distance sieve, CPA
processing, association scoring, and retention. It excludes imports, index
metadata, event preparation, downloads, terrain sampling, audio discovery, and
refinement. Both sources used the same Python 3.12 runtime, dependencies,
single-thread numerical settings, CPU affinity, recorded inputs, and GCC flags.
The measured numerical functions were not replaced by counting wrappers.

## What changed

### Select possible source times before decoding tracks

Let the first matched passage imply recording start `A` inside the existing
half-open partition `[L, U)`. Its clock interval has tolerance `t_first`.
Each effective tolerance is `quality.cpa_tolerance_s + offset_tolerance_s / 2`.
A later passage with implied start `B` and tolerance `t_event` can participate
only if its interval intersects the first interval. Thus it lies within the
partition expanded by both tolerances. Any event may be first, so the bound uses
the maximum effective tolerance across every event.

Add each event's audio-relative CPA time to bound receive time. Subtract at most
`maximum_CPA_radius / sound_speed` to bound emission time. Every inverse operation
rounds outward, including subtraction at Unix timestamp precision.

The query selects **complete segments** touching this envelope. It never clips a
trajectory, removes an interior sample, or changes its spline. Serial and worker
paths derive the same anchor once and use it for both querying and scoring.
Silence filters, noncanonical settings, invalid tolerances, and disjoint query
windows keep the original broad query.

On the dense replay:

| Work | Baseline | This change |
| --- | ---: | ---: |
| Decoded flight segments | 4,694 | 197 |
| Decoded source samples | 713,100 | 40,690 |
| CPA rows | 944 | 95 |
| Association work units | 302,818 | 147,985 |
| Unsupported CPA track evaluations | 62 | 4 |

Every removed unsupported track's complete emission interval misses the proven
query envelope. All four retained unsupported reports remain identical. The
590,900 unknown trials and 15,777 unclassified candidate assessments also remain
unchanged. The replay remains incomplete where its original evidence was incomplete.

### Fuse closest-approach neighbor calculations

An optional C extension traverses the existing bounded spatial-neighbor graph.
It combines squared distances, local-minimum selection, and adjacent-segment
projection without creating expanded observer-index and coordinate arrays.
It preserves arithmetic order, asymmetric minima, first-edge ties, and row order.
Python still performs endpoint spline optimization and final row construction.

Five alternating trials of ten iterations on eight archived ADS-B segments gave
these full CPA-stage results, including preparation:

| Receiver points | Baseline CPU per iteration | Native CPA | Speedup |
| ---: | ---: | ---: | ---: |
| 1 | 1.411 ms | 1.091 ms | 1.29x |
| 32 | 3.598 ms | 2.767 ms | 1.30x |
| 128 | 4.977 ms | 3.572 ms | 1.39x |
| 1,024 | 15.017 ms | 10.183 ms | 1.47x |
| 4,096 | 48.600 ms | 38.321 ms | 1.27x |

All 205 baseline comparisons matched exactly. This small real-track workload
measures the CPA implementation, not complete search throughput.

The extension is optional. Unsupported layouts, floating-point policies, or
exceptional arithmetic retain the Python path. Set
`DOPPLERGEIST_CPA_BACKEND=python` before starting the process to select it explicitly.
Checkpoints record the active backend. Existing implementation-mismatch checks
require a new output directory for ordinary checkpoints from older code.
The separately supported legacy continuation requires Python ridge, acoustic,
and CPA backends.

### Batch the unchanged native ridge fit

The native ridge extension now accepts a matrix of clock trials. It reuses scratch
storage and releases the GIL once per batch. Each row keeps the existing six IRLS
iterations, pairwise reductions, box constraints, and output arithmetic.
Custom scalar hooks, old extension binaries, unusual inputs, and failed probes
retain the established fallback. Native output may not overlap its inputs.

The dense replay uses 5,421 native batches for 227,378 trial rows, plus 862 scalar
fits. Batching alone measured a modest 1.06x dense improvement; its sparse replay
was approximately neutral. The main sieve gain comes from doing less impossible
work before decoding.

## Reproduce and validate

Build the optional extensions with `CC=gcc python setup.py build_ext --inplace`.
Use the recorded-input preparation in `.github/workflows/real-performance.yml`;
it restores public observations and creates `benchmark-inputs/dense-query.json`.
Build the same existing native extensions in the pinned baseline checkout.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/benchmark_prepared_measurements.py compare \
  --baseline-source /path/to/baseline/src --current-source src \
  --fixture benchmark-inputs/dense-query.json \
  --index benchmark-inputs/reference-region.sqlite \
  --include-track-query --clock-partition-query \
  --require-current-native --require-current-native-acoustic \
  --require-current-native-cpa --repeats 3 --output results/flight-sieve

python scripts/benchmark_real_cpa_rows.py \
  --baseline-source /path/to/baseline/src --points 1 32 128 1024 4096 \
  --repeats 5 --iterations 10 --skip-reuse-comparison \
  --output results/flight-cpa.json
```

Use one available CPU affinity for both arms when comparing elapsed time.
The normal comparison requires exact complete output equality. Partition-query
mode also requires exact scored outcomes, rankings, trial evidence, and retention.
Only declared early-work counts may decrease; each removed unsupported interval
must be outside the query. Repeated outputs must be deterministic within each arm.
Profiler runs and numerical wrapper instrumentation cannot produce speed claims.

The added recorded-input tests cover native arithmetic, buffer overlap, fallback
behavior, outward clock boundaries, complete-track preservation, serial/worker
query integration, and checkpoint backend identity. No generated recordings or
aircraft tracks are used. The remaining dominant cost is association scoring.
