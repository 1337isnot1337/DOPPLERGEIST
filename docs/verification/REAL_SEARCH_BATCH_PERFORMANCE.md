# Real-input source-fit batching comparison

This benchmark compares complete point-scoring stages on the recorded reference
audio and historical aircraft observations. It checks every retained candidate,
the stage accounting, and every retention-ledger row before reporting speed.
It does not measure location accuracy or nationwide runtime.

## Fixed workload

[`real-search-workloads.json`](../../tests/data/real-search-workloads.json) contains
the 18 measured proposals from the full reference-recording scan, grouped into
16 independent events. It stores these observations once and defines two cases.

| Case | Receiver setting | CPA rows | Associations | Retained modes |
| --- | --- | ---: | ---: | ---: |
| `previous-fit` | Archived fitted hypothesis | 117 | 1,927 | 100 |
| `offset` | 0.05 degrees north and 0.10 degrees west of that hypothesis | 65 | 206 | 28 |

Both cases use a 120-second recording-start window around the historical fitted
clock, a 5-second fit sweep, a 0.5-second fit step, and `top_k=100`. The aircraft
query spans 5,700 seconds. Each receiver has a query rectangle extending 0.35
degrees east/west and 0.25 degrees north/south. All measured groups remain in the
workload. The initial wider, 1,200-second clock-window experiment exceeded the
existing 20,000-association budget before scoring; these narrower workloads are
explicit development settings.

The reference region was historically filtered to exclude known jets. Its
observed coordinate/time extrema do not establish complete source selection
coverage. The fixture preserves that limitation in `index_coverage`. The receiver
and clock are source-informed hypotheses, not independent truth. The offset is a
workload control, not a second labeled location.

## Restore the observations

Install the project as described in [SETUP.md](../SETUP.md). Restore the historical
derived aircraft bundle with the existing artifact utility:

```bash
python scripts/restore_artifacts.py --bundle data-adsb-derived
```

The benchmark uses the committed measured proposals. It does not require another
audio scan. To inspect or regenerate those proposals separately, restore
`data-source` and use the full reference recording. The fixture records the
release, recording URL, historical receiver report, and terrain provenance.

Build the index using the exact incomplete-coverage declaration in the fixture:

```bash
PYTHONPATH=src python - <<'PY'
import json
from pathlib import Path
from dopplergeist.data_access import FlightIndex

fixture = json.loads(Path('tests/data/real-search-workloads.json').read_text())
index_path = Path('results/search-batch-input/reference-region.sqlite')
index_path.parent.mkdir(parents=True, exist_ok=True)
index = FlightIndex.from_parquet(
    index_path,
    'data/adsb/2026-09-08/reference-region.parquet',
    coverage=fixture['index_coverage'],
)
print(index.report['rows'], index.report['segments'])
PY
```

The restored input used here contains 717,735 observations in 4,694 segments.
Use a new index path when comparing different source data or normalization code.

## Run the paired comparison

Create a separate baseline checkout so the original search and batch-fitter
modules remain available:

```bash
git worktree add --detach ../DOPPLERGEIST-search-baseline 7a8dd27979bd9a984c8675c38a00dfbf98a5b01e
```

Run from the optimized repository root with one BLAS thread. `taskset` is optional
and Linux-specific; choose one allowed CPU and use the same CPU for both arms.
Use a new output directory for every run.

```bash
taskset -c 2 env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src \
  python scripts/benchmark_real_search_batch.py \
  --case previous-fit \
  --index results/search-batch-input/reference-region.sqlite \
  --baseline-repository ../DOPPLERGEIST-search-baseline \
  --output results/search-batch-previous-fit \
  --repeats 3

taskset -c 2 env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src \
  python scripts/benchmark_real_search_batch.py \
  --case offset \
  --index results/search-batch-input/reference-region.sqlite \
  --baseline-repository ../DOPPLERGEIST-search-baseline \
  --output results/search-batch-offset \
  --repeats 3
```

The script alternates baseline/current order. Each arm gets a fresh score-cache
context and ledger. It times CPA generation, association enumeration, complete
scoring, ranking, and ledger writes. Index loading is excluded, and deterministic
motion-support caches are warmed equally before either arm. Report process CPU
and wall time separately. Shared-host contention can change wall time.

This is a source-fit batching ablation. The baseline imports its original
`search.py` and `batch_ridge.py`; both arms share the current matching and geometry
implementations, whose numerical behavior is unchanged in this change set.
Use separate interpreters and full source checkouts when comparing unrelated
matching or geometry changes. This script must not be used to attribute their
costs to search batching.

The script fails if the declared workload counts change or if any compared
output differs. `comparison.json` records individual timings, operation counts,
and median speedups. SQLite ledgers remain available for inspection. A failed
comparison retains the differing payloads; it does not produce a success report.

## Regression checks

The small committed arithmetic fixture needs no restored index:

```bash
PYTHONPATH=src python -m pytest -q tests/test_real_all_event_batch.py -k 'cache or rounding'
```

The complete real-input gate uses the shared workload fixture and an explicit
local index path:

```bash
taskset -c 2 env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src \
  DOPPLERGEIST_REAL_INDEX=results/search-batch-input/reference-region.sqlite \
  python -m pytest -q tests/test_real_all_event_batch.py
```

Set `DOPPLERGEIST_REAL_CPA_CASE=offset` to select the offset workload. An existing
single-case fixture remains supported through `DOPPLERGEIST_REAL_CPA_FIXTURE`.
The gate checks complete diagnostics, supported rows at two sound speeds, actual
track-endpoint support loss, zero-drift fallback, independent returned results,
and the fixed-size cache keys and row limit.

## Numerical compatibility

The original first-event batch fitter used NumPy array powers, while its scalar
counterpart used Python float powers. Those operations differ by one unit in the
last place on a recorded row. Three representative scalar checks did not detect
that row. A global arithmetic correction changed a discarded candidate's ledger
diagnostic even though the retained top 100 modes were unchanged.

This implementation preserves the original first-event arithmetic and requests
scalar-power arithmetic only for newly batched paths that previously ran scalar
fits. The compact recorded-row fixture pins both behaviors explicitly. The
claimed stage comparisons require exact compatibility with the original ledger;
they do not silently substitute a corrected baseline.

Later-event batching gives a useful gain on both cases. The bounded exact-row
cache further helps the denser case, while its hashing overhead costs time in
the sparse case. Report both workloads and that tradeoff. The cache retains at
most 4,096 additional rows, each with fixed-size digest keys and scalar-valued
diagnostics; input arrays are not retained by this cache.
