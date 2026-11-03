# Historical inputs and bounded search

`data_access.py` and `tiled_search.py` connect the shared request contracts to the
physical scorer; the legacy manual research workflow remains reproducible.

## Acquisition

`acquire_inputs(request, recording, cache_root=..., offline=False)` validates the
shared request/recording dictionaries. A defensible recording-start UTC window
is required. Acquisition covers that window plus the complete recording and
sound propagation guard, including adjacent UTC days. `FlightCache.acquire_day`
obtains ADSB.lol release metadata, resumes split archive parts using checked HTTP
ranges, checks provider size/SHA-256, and streams gzip readsb traces into an index.
All aircraft types remain eligible. The archive is downloaded once per day/provider;
later uploads reuse the derived index without opening/downloading the archive.

New daily archive indexes prepare traces and compute flight-segment geometry in
separate processes, using the available CPU cores minus one for the SQLite writer
(and at least one worker). Queued work is bounded and results are written in
source order. SQLite writes and finalization still run in the writer process; a
stopped partial index must be rebuilt.

The on-disk SQLite index has spatial and time indexes, source hashes, explicit
source scope, per-payload checksums and altitude/classification labels. Disk staging supports
arbitrary input order. Query predicates select whole gap-split segments; they
never clip geometry or extrapolate across a gap. Daily release namespaces prevent
ID collisions. Segments on separate days are not joined across midnight; a ridge
requiring unsupported geometry is rejected by the physical model.

Version-two bounds enclose complete Hermite curves using ECEF cubic Bezier
control hulls, including excursions beyond measured latitudes/longitudes. The
normalizer hash versions raw caches and derived bounds. Legacy sample-bounds
indexes disable spatial pruning; oversized queries fail visibly under the search
budgets. Rebuild those indexes for efficient queries. Missing velocity components
use the shared segment-local inference helper, preserving finite measurements
including zeros. Legacy Parquets that already replaced missing velocities with
zero require raw re-ingestion before claiming corrected motion.

`scripts/index_flights.py` restores an index from a supplied Parquet. Its required
bounds, UTC interval and source note describe ingestion coverage. Use
`--all-aircraft` only for sources that retained jets and unknown types. The
historical prop/unknown table must be declared incomplete. Corrupt/truncated
inputs raise `DataUnavailable`; this is distinct from no acoustic events.

`CachedTerrain` acquires the [GLO-90 catalogue and tiles](https://copernicus-dem-90m.s3.amazonaws.com/readme.html)
and the [EGM2008 geoid](https://cdn.proj.org/). Each file has a checksum receipt.
GLO-90 heights are converted to ellipsoidal heights by adding geoid undulation.
Offline mode never fetches missing files. Only catalogue-absent tiles are treated
as ocean; missing downloads and nodata are explicit failures. Existing terrain
caches require the operator's explicit `adopt_existing=True` and format validation
before receipts are created. A caller-supplied geoid must use EGM2008; the old
regional EGM96 approximation is not the default automatic input.

Sampling reads local raster windows, including for the global geoid, and respects
the published half-pixel COG tile shift at exact degree boundaries.

The returned `AcquiredInputs` has `.indexes`, `.terrain`, `.bounds`,
`.time_range_s` (absolute emission window), `.recording_start_window_s`, and
`.coverage`. ADS-B query coverage does not establish receiver completeness or
prove that every audible flight was observed. Copernicus is a surface model,
which also leaves microphone height uncertain.

## Search

Use `matching.prepare_events(detected_events)` to get legacy event settings and
measurements, then call:

```python
report = search_national(
    inputs.indexes, inputs.terrain, events, measurements,
    time_range_s=inputs.time_range_s, output_dir=output / "search",
    bounds=inputs.bounds, budget=SearchBudget(),
    scoring={"mode": "robust_ridge",
             "recording_start_window_s": inputs.recording_start_window_s},
)
```

There is one EPSG:5070 origin and integer grid. Half-open tile cores own receiver
cells exactly once; expanded queries retain boundary flight segments. Original
flight geometry, emission-time propagation,
event offsets and score units are identical in every tile. One shared clock is
constrained to the supplied recording-start window. Coarse tiles use separate
worker processes for the built-in cached-terrain provider, automatically choosing
one fewer worker than the available logical CPUs, with a minimum of one. The
upload operator can override that count with the positive integer `search_workers`.
Custom terrain providers use serial execution. Hard limits on grid cells, tracks, samples,
CPA rows and candidate combinations bound each worker's allocations; total memory
grows with the worker count. An overloaded track query is retried with the same
conservative observer-distance test used by the scorer. Tracks with unsupported
motion remain in the result so their uncertainty is recorded. If a recognized
capacity limit is still exceeded, the search divides the tile into smaller
nonoverlapping grid rectangles and checkpoints each completed piece. Fine search
also divides overloaded rectangles.
If an unknown-clock, robust subset search still exceeds its association-count
limit at one cell, it partitions first-passage clock anchors into checkpointed,
half-open ranges. Each candidate belongs to one range and retains its full fit
interval. Other single-cell capacity failures, missing data, and errors remain
visible as incomplete work. Reducing `tile_cells` trades scheduling overhead for
smaller working sets.

On one overloaded full-day cell from the original recording and historical
traffic, eight clock ranges reproduced all 23,136 unpartitioned associations;
142 tracks had unsupported motion. A separate real-data engineering replay
matched leading scores, resumed saved ranges, rejected a corrupt split marker,
and imported two ranges computed on another host. These checks establish neither
a nationwide runtime nor a location.

Workers retain private score ledgers. The parent verifies their identities and
checksums before importing a completed tile, and merges rankings in deterministic
tile order. Parallel tiles use a conservative per-tile score floor; a checkpoint
with that policy can resume with a different worker count, including one. A
serial run using a global floor has a different checkpoint identity. On one
shared-machine replay of two real grid points from a full-day search, one worker
took 64.93 seconds and two took 38.95 seconds including startup, with identical
payloads and ledgers. This small sample does not predict nationwide runtime.

Before the spline-hull improvement below, one real full-day grid cell's track
retry reduced 1,929 queried tracks to 614 within the configured memory limit,
retaining all 200 tracks with unsupported motion. Complete scoring with the full
and reduced sets produced identical results, support records and retention
checksums. Other overloaded cells may still exceed the limits.

With the spline-hull proof enabled, the same cell retained 426 tracks, including
12 unsupported tracks. Full scoring with the original and filtered sets again
produced identical results and retention checksums; the retry took 40.66 CPU
seconds, compared with about 39.9 CPU seconds before the change.

For a trajectory with unsupported motion, the distance sieve can still exclude
it when the bounding boxes of every cubic-spline control hull are outside the
observer set's search radius. This proof does not assume subsonic motion. In a
different full-day cell, it excluded 122 distant unsupported trajectories
while leaving 20 unsupported trajectories visible; all 23,136 supported
associations were unchanged. One track-query timing was about six CPU seconds
with either version, so this is a coverage-accounting improvement, not a
demonstrated nationwide speedup.

Candidate scores are merged deterministically with approach identities, then
global finalists are refined on the same global grid in bounded subtiles. The
coarse spacing is a computational budget, not a proof that an isolated minimum
could not be missed between cells. Keep this limitation visible in confidence
decisions. `top_k` limits retained candidates; raw scores are not probabilities.

Robust subset scoring visits larger associations first **within each receiver
point**, preserving fit-cache locality. Every accepted group contributes at most
one nonnegative score unit. The current kth score from distinct, fully assessed
modes therefore supplies a safe lower cutoff: an association with too few groups
cannot enter Top-K. While fitting a shared-clock trial, validated residuals can
tighten that ceiling or establish a residual rejection before the remaining
groups are fitted. Comparisons are strict, so ties remain eligible. Acoustic
batches for later groups are deferred until a surviving trial needs them.

At each event group, the scorer fits only the shared-clock trials that survive
earlier groups and the acoustic bound. It reuses validated group contributions
and preserves the order and upward rounding of the conservative score ceiling.
If the product of clock trials and event groups exceeds 4,096, the scorer keeps
the scalar traversal.

Batch arithmetic matches the scalar model and uses Python `float` powers.
Regression tests compare every fitted clock in the recorded-data test batches
with the scalar fitter. Unsupported, nonfinite or degenerate batches use scalar
fitting. The same fallback handles overflowing powers, zero drift bounds and
noncanonical numeric parameters.

Representative batch checks also use the existing bounded scalar-fit cache.
The key includes typed parameters and complete measurement and acoustic contents.
Every representative comparison still runs. Repeated inputs reuse their scalar
result within one scoring context. Changed arrays require a new cache entry.
A last-threshold motion-support cache requires equal parameter types and values.
It returns independent interval arrays and preserves unsupported-motion accounting.

The same scoring context can reuse complete successful batch fits.
The same numerical batch can serve several candidate associations.
Keys include typed fit parameters, complete measured arrays and complete acoustic
arrays, with their shapes and layouts. Only C-contiguous, aligned acoustic matrices
qualify for reuse. Other layouts keep the existing numerical computation.
Before accepting a computed or reused batch, the fitter checks its representative
clocks against the scalar model. A mismatch retains the scalar fallback.
Independent diagnostic copies prevent callers from changing retained cache values.
The cache holds at most 1,024 batches within a 32 MiB estimated storage budget
per scoring context. That budget includes a fixed 512 KiB reserve for container
capacity. Each worker has its own context. This limits cache retention;
it does not cap complete worker memory or allocator fragmentation.

An earlier replay at one source-informed receiver point used 16 event groups and 3,905
associations. Across three alternating pairs, median CPU time fell from 68.9247
to 25.5895 seconds, a 2.6935× speedup. All candidate results, diagnostics, support
records and retention data matched the baseline with the separate correction to
scalar rounding. A narrower clock window had a smaller change: 4.6782 to 4.0092 CPU
seconds. The [performance report](PERFORMANCE.md) gives the inputs, procedure and
limits.

When an event's conservative loss bound alone makes the association unable to
reach the current Top-K floor, the scorer may also skip that clock and retain a
finite score ceiling. This applies only when the other matched groups cannot
make up the deficit even with perfect scores. Strict comparisons preserve ties;
the result verifier distinguishes these finite ceilings from outright acoustic
rejections. On one full-day point with 468 real associations, retained candidates
matched exactly and CPU time changed from 37.77 to 28.23 seconds. The persisted
bound ledger differs because it accounts for additional skipped trials. This
single measurement does not establish nationwide runtime or accuracy. A separate
2,443-association full-day clock partition retained the same candidates, with
CPU time changing from 158.01 to 149.56 seconds in one paired run. Both runs
reported zero unbounded candidate assessments; their ledgers differed as expected
for the additional score ceilings.

For association sets of at least 1,000 candidates, repeated acoustic batches
reuse exact track, receiver, time-array and sound-speed inputs in a per-worker
32 MiB cache. Sparse searches keep the ordinary path. A complete real-data clock
partition with 3,795 associations took 76.05 → 74.60 CPU seconds with identical
payloads and retention checksums. A complete 19,341-association partition took
276.99 → 250.88 CPU seconds, also with identical payloads and retention
checksums. A 5,000-association sample took 90.45 → 74.21 CPU seconds with
identical scored rows. These measurements are specific to those workloads, not
nationwide runtime estimates.

Unperformed trials remain unknown with explicit conservative bounds in the
retention ledger. A competitive candidate receives full evaluation, preserving
its original fitted diagnostics. The initial zero cutoff only rejects trials
that cannot satisfy the existing residual limits. This does not narrow the
automatic speed/range constraints or establish completeness between grid cells.

Real-observation computation replays for PR #152 measured the following; neither
is an independent localization-accuracy test:

| Replay | Source fits, before → after | Acoustic calls, before → after | Retained results |
| --- | --- | --- | --- |
| 169-point refinement neighborhood, 1,859 associations | 14,196 → 14,196 | 3,380 → 1,963 | All 100 identical, including diagnostics and best discarded score |
| 256 evenly spaced associations from 10,549 at one saved receiver point | 30,361 → 19,629 | 879 → 689 | All 92 identical, with conservative omitted-trial bounds |

The first replay took 20.13 → 15.86 seconds in one paired run. The second saved
about 8–28% wall time across paired runs under varying machine load; operation
counts were stable. These measurements do not predict nationwide runtime. The
group-count ceiling alone did not show a reliable speedup on the existing cache.

With the acoustic screen enabled in both runs, one full-day replay of a single
real grid point and 468 associations took 56.28 CPU seconds using scalar
first-event fits and 7.72 seconds when fitting only eligible clocks in batches.
The complete tile payload and retention checksum matched. This is one point,
not a nationwide runtime estimate or an independent location validation.

Manifest and tile receipts hash configuration, input index files, event
measurements, implementation and terrain files. Interrupted jobs reuse completed
tiles with the same identity. Changed inputs require a new output directory.
Failed tiles are retried on resume; `max_tiles` is a fixed configuration budget.
Reports distinguish complete/partial computation, source scope, missing tiles,
refinement failure, runtime and Linux process peak RSS. A complete tile is never
labelled a complete national search. The product/confidence workers translate
this internal report to the shared coverage and result contracts.
On Linux, process peak RSS uses the process's post-exec `VmHWM`; it does not
include worker processes or FFmpeg. Earlier `getrusage` receipts can inherit a
larger pre-exec high-water mark and should not be compared as measured peaks.
Search progress counts grid-cell work, not elapsed time or a guarantee that all
data and model support are complete; dense cells may take much longer to process.

Source completeness includes an acoustic halo outside observer bounds: a
CONUS-cropped flight table cannot establish complete border coverage.
`filters={"association": "subsets"}` delegates bounded event/group subset
association to the matching worker and preserves unmatched proposals.
`alternative_modes_exhaustively_assessed` remains false because coarse-grid and
top-k retention do not establish exhaustive alternative-mode recall.

Automatic CPA proposals retain speeds from zero through the sound speed and
distances from zero through the configured maximum; unsupported motion is still
reported rather than silently treated as valid. In one real full-day cell, five
passes below the former 1 m/s minimum added 1,166 associations, retaining all
23,136 previous associations. These are proposals, not confirmed aircraft sounds.
The separately defined finite emitted-frequency range remains a modeling prior.

The normal `robust_ridge` path defaults to subset association over **all prepared
independent groups**. There is no default maximum of two or three matched events.
Harmonics/fragments are grouped by the audio/matching producers before this
driver. False proposals can remain unmatched while later supported groups enter
the same joint score and refined grid. Legacy `ridge`/`brightness` paths retain
full-event association; `filters={"association": "full"}` also selects it
explicitly. A deliberately smaller `max_events` is a work limitation: the report
sets `all_event_groups_considered=False`, explains the cap and returns partial
status. Candidate/branch budget exhaustion likewise cannot count as completion.

For a supplied time window, shared CPA-consistency intervals are intersected with
the trusted window before scoring. A biased event-center estimate cannot discard
a common clock inside both intervals merely because it lies beyond a five-second
anchor sweep. A trusted exact clock stays exact; events never receive separate
clock adjustments. The current acceptance target is up to 1,000 m error, with
100-500 m or closer preferred. The driver reports physical/data/work limits rather
than converting scores into that accuracy claim.

## Measure scoring throughput

`scripts/benchmark_real_optimization.py` compares source checkouts on actual
recorded ridges and historical aircraft observations. It measures event
preparation, trajectory loading and one complete candidate-scoring stage.
Saved receiver positions and clocks are development hypotheses. This replay
does not measure nationwide search time or location accuracy.

The benchmark uses fresh processes, one numerical-library thread and alternating
run order. Three repetitions give separate CPU and wall-time medians. An optional
profile runs separately and does not enter those medians. Phase timings include
their child calls and must not be added together.

New-run comparisons require identical workloads, runtime versions, ranked rows,
assessment counts and all three retention tables. The script stops at the first
discrepancy. Operation counts distinguish actual scalar computations, scalar
validation requests and clocks fitted in batches. A lower scalar-call count
alone is not a speedup.

### Measured results: 2026-11-03

The final measured source is
[`682a539`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/682a539274d3bd6daf0fee6184001eabe84f5342).
It integrates the optimizer from PR #212 and preserves its scheduling,
prepared-input cache, fused geometry and numerical guards.
Main `f979320`, its integration parent, differs from `aa3dff6` only in the README.

The primary replay used 16 measured proposals, 16 independent groups and one
saved receiver hypothesis. Its aircraft input contained 64,246 observations in
447 trajectory segments. Each version evaluated the same 3,921 associations
within a ±120-second recording-start window and retained 100 rows.

#### Incremental comparison with the merged optimizer

The baseline is
[`aa3dff6`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/aa3dff686c989524daa20c081a816b792d9c8890),
which already contains PR #212.

| Measurement, median of three runs | Main baseline | Final source | Speedup |
| --- | ---: | ---: | ---: |
| Scoring CPU | 29.20 s | 17.63 s | 1.66× |
| Scoring wall time | 29.21 s | 17.69 s | 1.65× |
| Complete benchmark subprocess, wall time | 32.75 s | 21.41 s | 1.53× |

Main CPU times were 31.0323, 28.6455, 29.1982 seconds.
Final-source CPU times were 20.0753, 16.8685, 17.6343 seconds.
Every pair improved. The table reports ratios of medians.

#### Comparison with the corrected original

The original baseline is `89dc912`, before the performance changes.

| Measurement, median of three runs | Corrected original | Final source | Speedup |
| --- | ---: | ---: | ---: |
| Scoring CPU | 70.59 s | 18.00 s | 3.92× |
| Scoring wall time | 70.65 s | 18.01 s | 3.92× |
| Complete benchmark subprocess, wall time | 73.99 s | 21.54 s | 3.43× |

Original CPU times were 86.0219, 70.5917, 69.1955 seconds.
Final-source CPU times were 19.3379, 17.9990, 16.4775 seconds.
All observations remain included. Each pair improved.
The final source was measured independently in each baseline series.


All seven checks passed in every paired and repeat-consistency comparison.
They compare complete ranked rows, assessment counts, workloads, runtime versions
and all three retention tables. Run order was baseline/optimized,
optimized/baseline, baseline/optimized. Profiles run separately and do not enter
these measurements.

The complete subprocess includes imports, preparation, trajectory loading,
scoring and output. It excludes audio discovery, downloads, nationwide search
and refinement. The environment used Python 3.12.14, NumPy 2.5.4, SciPy 1.17.0,
pandas 2.2.3, PyArrow 26.0.1 and pyproj 3.8.0 on Linux x86-64.

#### Work avoided, checks retained

| Operation on the primary workload | Main baseline | Final source |
| --- | ---: | ---: |
| Successful batch requests | 7,343 | 7,343 |
| Clock rows returned by the batch path | 241,101 | 241,101 |
| Representative scalar comparisons | 0 | 22,029 |
| Actual uncached scalar computations | 74 | 2,071 |
| Acoustic calls | 861 | 861 |
| Acoustic samples | 2,121,053 | 2,121,053 |

The final source executes only 1,093 numerical batch solves over 38,986 clock
rows. It reuses all 6,250 repeated complete solves in this workload.
The harness counts numerical solves separately from requests and returned rows.
Older revisions lack that separate numerical-helper counter.

Before accepting a computed or reused batch, the fitter checks its representative
clocks against the scalar model. Scalar-reference caching reduces repeated work
inside those checks. A mismatch retains the ordinary scalar fallback.

#### Additional real-input comparisons

A separate paired control used a ±10-second window against main `aa3dff6`.
It included 1,055 associations, 422 trajectory segments, 60,711 observations and
all 16 groups. All seven checks passed.

Scoring CPU changed from 4.08 to 2.26 seconds (1.81×).
This is one auxiliary pair, not a repeated median.

Two final-source replays also passed all seven checks against saved corrected-original baselines:

| Workload | Saved baseline CPU | Final replay CPU | Observed ratio |
| --- | ---: | ---: | ---: |
| Fresh discovery: 18 ridges, 16 groups, 3,921 associations | 66.82 s | 18.22 s | 3.67× |
| Second receiver: 16 groups, 4,031 associations | 71.18 s | 17.29 s | 4.12× |

These are single replays against saved baselines, not new paired medians.
The fresh replay sets `--recording-duration-s 3600.1845` for the original WAV.
The second receiver uses `--recording-duration-s 3600.0`. Both retain all 16 groups.
Loaded trajectory windows also include clock uncertainty and padding.


#### Development results and limits

A preliminary integration restored cached scalar checks without complete-batch
reuse. It took 29.29 CPU seconds against main's 25.88 seconds in one pair.
That regression motivated complete-batch reuse. A separate profile found 1,093
unique complete keys among 7,343 requests. Its bounded-cache simulation guided
the memory budget; the final tables measure the implemented cache.

The preceding implementation's 2.41× result remains in the
[earlier report](https://github.com/1337isnot1337/DOPPLERGEIST/blob/682a539274d3bd6daf0fee6184001eabe84f5342/docs/DATA_AND_SCALE.md#earlier-measured-version-2026-11-03).
Each report keeps its original source revision and settings.
These regional computation replays do not establish independent localization
accuracy or nationwide wall time.

### Arithmetic correction

The performance baseline is
[`89dc912`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/89dc912737436a5c13504fc06d353dedc8ebc36a).
It adds the scalar/batch arithmetic correction to `7a8dd27`, before the performance
changes. Its only production change is `batch_ridge.py`.

One discarded four-group score differed by `4.44e-16` between the old scalar and
batch paths. The correction makes the batch result equal the scalar result.
Comparisons against unmodified `7a8dd27` preserve all 100 retained rows,
assessment counts and bound tables. The corrected baseline isolates the speed
improvements from that existing numerical defect. The new regression checks
every clock, including the clock that the representative runtime checks omitted.

### Reproduce the comparison

Restore the real source and derived aircraft inputs through [Artifacts](ARTIFACTS.md).
Use one Python dependency environment for all source checkouts.
Create detached worktrees for the measured source and both baselines:

```bash
git fetch origin 682a539274d3bd6daf0fee6184001eabe84f5342 \
  aa3dff686c989524daa20c081a816b792d9c8890 \
  89dc912737436a5c13504fc06d353dedc8ebc36a
git worktree add --detach ../dopplergeist-performance-source 682a539274d3bd6daf0fee6184001eabe84f5342
git worktree add --detach ../dopplergeist-performance-main aa3dff686c989524daa20c081a816b792d9c8890
git worktree add --detach ../dopplergeist-performance-original 89dc912737436a5c13504fc06d353dedc8ebc36a
```

From the repository root, compare the incremental change with main:

```bash
python ../dopplergeist-performance-source/scripts/benchmark_real_optimization.py \
  --source ../dopplergeist-performance-source \
  --baseline ../dopplergeist-performance-main \
  --tracks data/adsb/2026-09-08/reference-region.parquet \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --candidate evidence/results/reference-local/report.json \
  --clock-radius-s 120 --repeats 3 \
  --output results/performance-main-new-run
```

Then compare the complete improvement with the corrected original baseline:

```bash
python ../dopplergeist-performance-source/scripts/benchmark_real_optimization.py \
  --source ../dopplergeist-performance-source \
  --baseline ../dopplergeist-performance-original \
  --tracks data/adsb/2026-09-08/reference-region.parquet \
  --discovery evidence/audio/w1-sensitivity-20261102/reference/discovery.json \
  --candidate evidence/results/reference-local/report.json \
  --clock-radius-s 120 --repeats 3 \
  --output results/performance-original-new-run
```

The output contains `comparison.json`, complete scored results and retention
databases. The script refuses an existing output directory. The default input
window extends through the last measured event, with 120 seconds of padding.
The primary and narrow-window comparisons use that default extent.
`--recording-duration-s` supplies a longer recording extent when required.
`--point-file` accepts multiple saved receiver hypotheses.

For a fresh whole-recording discovery, run:

```bash
PYTHONPATH=../dopplergeist-performance-source/src \
python ../dopplergeist-performance-source/scripts/discover_audio.py \
  data/source/reference-recording.wav \
  --output results/performance-fresh-discovery
```

Then use its `discovery/discovery.json` with the pinned-source comparison command.
The reported fresh replay uses `--recording-duration-s 3600.1845`.
The second-receiver replay uses `--recording-duration-s 3600.0` and the saved
`evidence/results/reference-faint-alltypes-local/report.json` candidate.
Both auxiliary runs load a broader trajectory extent than the primary comparison.
Use a distinct output directory for each workload.
Add `--profile` to identify the remaining dominant stage.

### Continue optimization

1. Freeze the real inputs, search settings and source revisions.
2. Measure the dominant stage before changing its implementation.
3. Reduce repeated work across clocks, events or candidates.
4. Compare complete outputs, including discarded-candidate evidence.
5. Run alternating timing repetitions without competing benchmark processes.
6. Keep a change only after it improves measured time and passes the comparison.

All independent groups and the shared recording clock remain part of the
workload. A narrower clock window is useful only with independent time evidence.
Fewer events, selected flight identities or a truth-derived region change the
search problem and cannot establish an equivalent speedup.

Existing tile workers can use these faster internals without a new setting.
One numerical-library thread per worker avoids nested CPU oversubscription.
Worker count still depends on available CPU, memory and storage throughput.
Changed source code requires a new search identity and output directory.
An active job does not adopt these changes automatically.

## Checks

Use actual recorded observations; do not run the historical generated-data suites.

```bash
DOPPLERGEIST_REAL_CPA_FIXTURE=/path/to/real-cpa-diagnostic.json \
DOPPLERGEIST_REAL_REGION_PARQUET=data/adsb/2026-09-08/reference-region.parquet \
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  PYTHONPATH=src python -m pytest -q \
  tests/test_real_retention_floor.py tests/test_real_score_ceiling_validation.py \
  tests/test_real_batch_ridge.py tests/test_real_acoustic_batch_cache.py \
  tests/test_real_geometry_reuse.py tests/test_real_batch_rounding.py \
  tests/test_real_association_budget.py tests/test_real_association_clock_window.py \
  tests/test_real_index_staging.py tests/test_real_batch_scalar_parity.py \
  tests/test_real_geometry_kinematics.py tests/test_real_prepared_measurements.py

PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python scripts/benchmark_acoustic_sieve.py \
  --fixture /path/to/real-cpa-diagnostic.json --baseline 72cdebb \
  --output results/my-new-sieve-comparison
```

The diagnostic contains measured event ridges, observed `cpa_rows`, one receiver
`point` and the local `real_index` path. The benchmark can override that path with
`--index`; no media or native index is bundled. It compares isolated baseline
matching/scoring modules with the current fitter and requires identical shared
geometry. Timing includes scoring with a bounded fit cache. Scaling experiments
and location-accuracy evidence must be labelled separately.

The final local gate selected 37 distinct real-data tests: 36 passed and one
archived-segment test skipped. That upstream case requires `ab50b9:11`, absent from
the local diagnostic. The independent 39-clock regression on actual segment
`ab50b9:1` passed, including the rounding-sensitive clock.
