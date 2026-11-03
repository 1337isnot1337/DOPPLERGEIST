# Historical inputs and bounded search

Worker 2 owns `data_access.py` and `tiled_search.py`. These are adapters around
the shared `contracts.py` shapes and existing physical scorer; the legacy manual
research workflow remains reproducible.

## Acquisition

`acquire_inputs(request, recording, cache_root=..., offline=False)` validates the
shared request/recording dictionaries. A defensible recording-start UTC window
is required. Acquisition covers that window plus the complete recording and
sound propagation guard, including adjacent UTC days. `FlightCache.acquire_day`
obtains ADSB.lol release metadata, resumes split archive parts using checked HTTP
ranges, checks provider size/SHA-256, and streams gzip readsb traces into an index.
All aircraft types remain eligible. The archive is downloaded once per day/provider;
later uploads reuse the derived index without opening/downloading the archive.

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
cells exactly once; expanded queries retain boundary flight segments. Only the
receiver grid is partitioned. Original flight geometry, emission-time propagation,
event offsets and score units are identical in every tile. One shared clock is
constrained to the supplied recording-start window. Sequential execution and hard
limits on grid cells, tracks, samples, CPA rows and candidate combinations bound
working allocations. An overloaded tile is reported as missing work. Reducing
`tile_cells` trades scheduling overhead for smaller working sets.

Candidate scores are merged deterministically with approach identities, then
global finalists are refined on the same global grid in bounded subtiles. The
coarse spacing is a computational budget, not a proof that an isolated minimum
could not be missed between cells. Keep this limitation visible in confidence
decisions. `top_k` limits retained candidates; raw scores are not probabilities.

Manifest and tile receipts hash configuration, input index files, event
measurements, implementation and terrain files. Interrupted jobs reuse completed
tiles with the same identity. Changed inputs require a new output directory.
Failed tiles are retried on resume; `max_tiles` is a fixed configuration budget.
Reports distinguish complete/partial computation, source scope, missing tiles,
refinement failure, runtime and Linux process peak RSS. A complete tile is never
labelled a complete national search. The product/confidence workers translate
this internal report to the shared coverage and result contracts.

Source completeness includes an acoustic halo outside observer bounds: a
CONUS-cropped flight table cannot establish complete border coverage.
`filters={"association": "subsets"}` delegates bounded event/group subset
association to the matching worker and preserves unmatched proposals.
`alternative_modes_exhaustively_assessed` remains false because coarse-grid and
top-k retention do not establish exhaustive alternative-mode recall.

## Checks

```bash
PYTHONPATH=src /path/to/python -m pytest -q tests/test_data_access.py tests/test_tiled_search.py
```

Tests include split archive streaming, byte-range/checksum failures, explicit
offline errors, jets/unknowns, gap/no-extrapolation behavior, whole-segment queries,
datum conversion, tiled/untiled agreement at a boundary, deterministic repeated
approach preservation, checkpoint reuse, and visible partial/budget failures.
Scaling experiments and location-accuracy evidence must be labelled separately.
