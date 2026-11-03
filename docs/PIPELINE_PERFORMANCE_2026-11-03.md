# Pipeline performance: 2026-11-03

The core changes in [PR #222](https://github.com/1337isnot1337/DOPPLERGEIST/pull/222) reduce repeated audio work, trajectory construction, coordinate transforms, and database commits. They preserve the scientific search rules. The committed [component evidence](../benchmarks/results/pipeline-components-20261103.json) contains individual timings, input hashes, runtime versions, and comparison results.

## Source and measurement scope

| Revision | Role |
| --- | --- |
| `7a8dd27979bd9a984c8675c38a00dfbf98a5b01e` | Unmodified source baseline |
| Core `a2236ac`, tested with main as `fa19b594` | Core changes described here; public commit `1d045b3664648060071fa6e0799738a3fe74b19a` has the same source tree |
| `931b1bd` | Separate scoring alternative that preserves the original numerical results exactly |
| `3725e9d` from [PR #212](https://github.com/1337isnot1337/DOPPLERGEIST/pull/212), combined as `00727d4` | Separate scoring implementation used in the combined HTTP evaluation |

All workloads use actual recordings and observed trajectories. The full WAV produces 18 ridges in 16 independent groups. The common HTTP MP3 produces 17 ridges in 15 groups. Each comparison uses identical input bytes within its pair. These development workloads measure runtime and result consistency. They do not establish location accuracy.

## Core changes

- **Audio:** discovery uses scalar medians from upstream [PR #221](https://github.com/1337isnot1337/DOPPLERGEIST/pull/221). PR #222 adds reusable transition slices, penalties, and predecessor indices for ridge tracing. Window lengths and strict tie comparisons stay unchanged.
- **Flight decoding:** an index reuses decoded-track snapshots. Every read still checks the stored payload hash. Each return contains independent objects. Admission protection stops large repeated queries from evicting entries they just used.
- **Duplicate tracks:** canonical binary geometry replaces float-to-JSON conversion for private duplicate detection. Persisted evidence hashes retain their original representation.
- **Terrain:** a bounded cache reuses up to 32 coordinate transforms. DEM and geoid samples remain exactly equal.
- **Retention:** serial search commits at most 32 empty tiles together. Coarse stages, global stages, checksums, bounds, and checkpoint files remain present. Normal stage validation rejects checkpoints from an interrupted, uncommitted transaction.

The track cache holds at most 32 MiB of serialized, uncompressed snapshots and 2,048 entries per index instance. These limits exclude returned objects and temporary allocations. `track_cache_bytes=0` disables reuse. The transaction benchmark compares ordinary commits with `--batch-size 32`. It measures the same implementation in both arms.

The discovery measurement below used the equivalent local scalar-median implementation before PR #221 merged. The final integration adopts that upstream implementation.

## Component timings

Times below are wall seconds. Audio, helper, and empty-tile rows use medians from three alternating pairs. Warm-cache rows use three queries after an initial query. The [evidence file](../benchmarks/results/pipeline-components-20261103.json) preserves CPU timings where measured.

| Workload | Control | Before | After | Speedup |
| --- | --- | ---: | ---: | ---: |
| Full WAV discovery, intake and plots excluded | Old/new source | 7.357 | 6.044 | 1.22× |
| Two recorded ridge windows | Old/new source | 0.183 / 0.0736 | 0.0607 / 0.0256 | 3.02× / 2.87× |
| 441 tracks, 89,504 samples, warm query | Cache disabled/enabled | 1.568 | 0.101 | 15.53× |
| 1,183 tracks, 287,491 samples, warm query | Cache disabled/enabled | 4.725 | 2.745 | 1.72× |
| Geometry identities for 214 tracks | Old/new helper | 0.712 | 0.0107 | 66.50× |
| Duplicate-index query, track cache disabled | Old/new helper | 2.970 | 1.490 | 1.99× |
| 283 scalar DEM and geoid queries | Old/new helper | 0.482 | 0.151 | 3.20× |
| 256 recorded empty tiles | Ordinary/batched commits | 2.169 | 0.765 | 2.84× |

The helper query contains 71,571 samples. Terrain sampling covers 274 distinct candidate coordinates. Empty-tile timing includes real index queries, geometry, checkpoint writes, and all 512 ledger stages. It excludes progress updates, resume reads, and nonempty scoring.

Audio, helper, and scoring measurements use Python 3.12.14. Cache, transaction, configured-worker, and HTTP controls use Python 3.12.3 with SQLite 3.45.1. Each pair uses the same interpreter and numerical packages. Cross-runtime ratios are not controlled comparisons.

### Cold and warm cache behavior

Cold means an empty decoded-track cache. Warm means reuse after an earlier query. Neither term establishes a cold operating-system file cache. The dense query costs 4.041 seconds without caching and 4.936 seconds with caching on its first pass: approximately **22% slower**. Across one cold and three warm passes, it improves by 1.35×. The regional workload improves by 3.43× across all four passes. Its 15.53× result applies only to warm queries.

## Separate scoring implementations

The four-arm comparison loads each frozen variant in a separate process. Each cell below is **one process CPU measurement**, not a median. Input loading is excluded. Both workloads use the same 16 observed groups, receiver hypothesis, clock range, and budgets across variants.

| Workload | Original baseline | Arithmetic-corrected baseline | Exact alternative `931b1bd` | PR #212 `3725e9d` |
| --- | ---: | ---: | ---: | ---: |
| Dense: 1,927 associations | 35.878 s | 36.826 s | 19.256 s | 16.091 s |
| Offset: 206 associations | 3.130 s | 3.683 s | 2.679 s | 2.030 s |

PR #212 is 2.23× and 1.54× faster than the original on these cases. It exactly matches the corrected baseline, including discarded candidates and ledger contents. Retained candidates and accounting also match the original baseline. A separate power-arithmetic correction changes one discarded dense candidate's total score by two units in the last place. Related diagnostics and its ledger checksum also change. The comparison preserves those differences without treating them as exact equivalence.

The exact alternative matches the original results and remains available separately. Its portable scoring workload and paired benchmark are preserved at `931b1bd`, in `docs/verification/REAL_SEARCH_BATCH_PERFORMANCE.md`. Those scoring changes are separate from the core changes here.

## Reproduce the core comparisons

Follow [installation instructions](SETUP.md), then run from the repository root. Select the same interpreter and package versions for both arms. Limit numerical threads. Optional Linux CPU affinity can reduce interference. Use a new output path for every run.

```bash
. .venv/bin/activate
export PYTHONPATH=src
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python scripts/restore_artifacts.py \
  --bundle data-source --bundle data-adsb-derived --bundle data-terrain
git worktree add --detach ../DOPPLERGEIST-perf-baseline \
  7a8dd27979bd9a984c8675c38a00dfbf98a5b01e
PERF_BASELINE=../DOPPLERGEIST-perf-baseline
PERF_INDEX=results/perf-input/reference-region.sqlite

python - <<'PY'
import json
from pathlib import Path
from dopplergeist.data_access import FlightIndex
fixture = json.loads(Path('tests/data/real-empty-tile-workload.json').read_text())
FlightIndex.from_parquet(
    'results/perf-input/reference-region.sqlite',
    'data/adsb/2026-09-08/reference-region.parquet',
    coverage=fixture['index_inputs'][0]['coverage'],
)
PY

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

For the dense cache case, substitute bounds `-74.05 40.55 -73.55 41.05`, times `1788825600 1788912000`, and limits `--max-tracks 5000 --max-samples 750000`. The portable empty-tile fixture contains completed checkpoints from a failed baseline run. It compares all scientific index inputs and source byte hashes, allowing only local source paths to change after restoration.

## Verification and complete workflows

The merged core revision passed **23 focused real-input checks in 2.47 seconds**, plus CLI help. No synthetic suite ran. Component gates require exact measured arrays, diagnostics, accounting, and logical ledger contents. Numeric differences fail these gates. Event thresholds, harmonic grouping, clock domains, coverage requirements, and unknown-support rules remain unchanged. The regional archive excludes known jets and cannot establish complete coverage. Historical receiver and clock hypotheses do not provide independent accuracy evidence.

Configured scoring with one versus four workers took **63.08 versus 50.86 seconds**, a 1.24× improvement in one sequential pair. This uses upstream [PR #210](https://github.com/1337isnot1337/DOPPLERGEIST/pull/210) from `adbfb3e`, with the same local changes in both arms. All 16 scientific JSON artifacts, three CSV files, and 283 ranked rows match after explicit metadata exclusions. The source-informed configured replay remains unaccepted, with incomplete model support.

The complete automatic HTTP comparison is pending. Two original baseline attempts stopped with retention database errors. Their cause is unestablished. The system-runtime baseline reached its 900-second HTTP timeout. Its original receipt remains failed. A separate continuation preserves the baseline source and inputs and records restart/replay costs explicitly.

After both workers stop, the comparator requires full-workflow evidence and compares discovery, candidates, clocks, associations, diagnostics, decisions, and logical retention ledgers. It ignores only enumerated implementation and run metadata. Use the explicit continuation report:

```bash
python scripts/compare_real_upload_performance.py \
  --baseline path/to/baseline --current path/to/current \
  --baseline-continuation path/to/baseline/continuation.json \
  --output results/new-upload-comparison.json
```

A resumed baseline can establish scientific parity. Its cumulative active-time ratio is reported separately and cannot establish an uninterrupted fresh-run speedup. Stage history has polling uncertainty. Failed or incomplete workflows do not qualify for an overall speedup claim.
