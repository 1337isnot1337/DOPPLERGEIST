# Worker 2 implementation and measured verification

Issues: [#6](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6),
[#7](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7).
Implementation: acquisition/index [#22](https://github.com/1337isnot1337/DOPPLERGEIST/pull/22)
and outer search [#31](https://github.com/1337isnot1337/DOPPLERGEIST/pull/31).
These receipts preserve unsuccessful and inconclusive outcomes. No source video,
environment, flight/terrain cache, or ephemeral media URL is included.

These runs retain their original 100 m acceptance wording. The subsequent user
requirement allows up to 1,000 m, with 100-500 m or closer preferred, and asks for
every supported independent flyover. Historical measurements/decisions are not
relabeled. A near-truth diagnostic candidate still does not establish a supported
location when coverage, competing modes or uncertainty remain insufficient.

## Current data and search checks

Final source `3d8f30c` passes **100 tests with zero failures/skips** in 24.62 s.
`final-tests.xml`, `final-tests.log` and `receipt.json` preserve the command,
dependency versions and checksums. This includes the independent index invariants,
component-wise derivatives, complete-segment queries, subset scoring and bounded
work/checkpoint checks.

`index-v2-report.json` records the repaired index build from the existing
all-type CONUS 15-minute Parquet: **938,158 rows, 10,868 gap-split segments,
zero invalid rows, 516.300 seconds, 486.512 MiB process peak RSS**. Its full source
hash, normalizer hash and declared ingestion scope are included. The historical
Parquet already replaced some missing derivatives with zero. Version-two indexing
cannot recover that information; raw re-ingestion is required for corrected
measurements. The build ran under concurrent host load; timings are observations,
not a controlled before/after speed comparison.

`regional-query-v2.json` records a cache-only acceptance query: **269 whole
segments**, the expected `a38237` flight, and ellipsoidal, interpolated and
barometric labels. One extra conservative hit versus version one is expected
after bounding continuous Hermite geometry. This regional query is not a
location-accuracy evaluation.

`scale-v2-report.json` and `scale-v2-manifest.json` pin the final measured
traffic scale fixture to implementation `f0b8ba7` and input/configuration/code
hashes. The driver searched the declared **entire CONUS rectangle**, without a
receiver-coordinate prior or known flight ID:

| Measurement | Result |
| --- | --- |
| Tile configuration | 8 by 8 receiver cells; 20,000 m spacing; concurrency 1 |
| Tiles attempted | 858 |
| Completed / failed | 855 / 3 |
| Grid points processed | 31,094 |
| Runtime | 584.320 s |
| Process peak RSS | 274.016 MiB |
| Final status | **partial** |
| Missing source scope | Acoustic border halo extends outside CONUS-cropped input |

All three failures report `Acoustic model requires a subsonic source`; no failed
tile is counted as complete. The fixture uses a deterministic analytic ridge and
constant ground, with no localization truth. It measures bounded work on real
traffic, not automatic audio detection, narrow-mode recall, DEM accuracy or
100 m national localization. The 20 km coarse spacing deliberately limits the
resource trial and is insufficient to certify a precision target.

`model-failure-audit.json` and its exact runner inspect those failed tiles. Four
source segments have severe disagreement between supplied velocity at sample
knots and modeled between-sample motion, including a C172 segment with a sampled
14,600 m/s Hermite speed. This does not imply actual supersonic aircraft.
Position jumps, motion/identity defects and historical null-to-zero conversion
need fresh raw-source investigation. The follow-up is
[issue #64](https://github.com/1337isnot1337/DOPPLERGEIST/issues/64); the existing
partial outcome remains unchanged.

`scale-v1-*` and `index-v1-report.json` preserve the earlier development run:
3,188 of 3,192 tiles completed, four explicit model failures, 1,341.626 s and
259.0 MiB peak RSS. It used obsolete sample-only bounds and predates the corrected
border-coverage accounting. Its hashes are retained for audit; it is superseded
by the version-two run and must not establish complete model coverage.

The current driver also counts huge work queues arithmetically. A CONUS grid with
1 m spacing and `max_tiles=1` terminates after one bounded tile rather than
enumerating billions of unsearched tiles. Exact trusted clocks override
approximate CPA-derived anchors. A three-proposal integration regression retains
the two supported events after an unmatched leading proposal and preserves
original event indices and one common recording clock.

## Terrain

The first network sample failed at an exact latitude-degree boundary; its log is
preserved in `terrain-first-failure.log`. The corrected COG lookup uses published
half-pixel tile extents. `terrain-boundary-network.json` contains provider URLs,
file hashes and actual GLO-90 plus EGM2008 samples. `terrain-offline-replay.json`
verifies identical cached results without network access.

`terrain-window-offline.json` verifies the same samples after local raster-window
sampling: **0.764 s, 251.379 MiB process peak RSS**, compared with materializing
the global geoid on each call in the earlier implementation. Returned heights
were 331.2636966705322 m and 385.92816734313965 m ellipsoidal at the recorded
test coordinates. These are sampling checks, not independently surveyed terrain
accuracy measurements.

## User-supplied Hermes reference and actual MP3 HTTP path

Reference: [Hermes aircraft Doppler geolocation](https://github.com/mojomast/hermes-aircraft-doppler-geolocation),
pinned at `2c3ed20577bcce29058d73422dd4f85392d04c24`, MIT, Kyle Durepos.
No donor code was copied. Its six tests pass (`hermes-reference-unit-tests.log`).
Its own narrow-band synthetic self-test returns zero supplied-grid error,
109.9977 Hz, 80.3740 m/s and 1,039.30 m slant (`hermes-reference-selftest.json`).
It still requires manual bands/windows and prepared candidate/flight inputs.

Our separate real HTTP check uses its generated waveform and trajectory only.
Search receives an MP3, the declared recording-start UTC, a synthetic flight
index, constant terrain and **CONUS coverage**. It receives no true coordinates,
true flight ID or truth-derived bounding box. Generator truth is evaluated only
after the job is terminal. The standalone runner is retained as
`hermes-http-run.py`; its local paths and required reference checkout are explicit.

Verification source is pushed as `swarm/w2-integration-check` at
`f580b3da3d758c02a374877b5fb0b144fec56f2a`. This is a pinned producer-integration
verification snapshot, not a replacement integration branch. Its full combined
suite passed **124 tests, zero skips**, in 174.39 s.

| Actual stage/result | Observation |
| --- | --- |
| Upload | HTTP POST of encoded MP3; download SHA-256 matches submitted bytes |
| Discovery | One automatic event, with no supplied time/frequency windows |
| National grid | All 3,116 tiles completed; no failed tiles |
| Search runtime / peak RSS | 110.586 s / 286.547 MiB |
| Total job runtime | 139.954 s |
| Top candidate, post-search evaluation | 11.461 m from independent synthetic truth |
| Final job decision | **inconclusive / search_incomplete** |

The supplied synthetic trajectory interval does not cover the conservative
acquisition query guards. The decision correctly preserves partial coverage;
constant orthometric ground and incomplete sensitivity are additional limits.
**The 11.461 m candidate is not a supported localization success.** The complete
request, search report, decision, provenance and evaluation receipts are included.
This verifies actual upload → automatic discovery → indexed data query → national
search → refinement → explicit decision, without claiming independent real-audio
national accuracy. The existing regional real result remains a separate baseline.

## Reproduction commands and remaining limits

```bash
PYTHONPATH=src /path/to/python -m pytest -q tests/test_data_access.py tests/test_tiled_search.py tests/test_index_geometry_invariants.py tests/test_association.py
PYTHONPATH=src /path/to/python scripts/index_flights.py INPUT.parquet NEW.sqlite --bounds -125 24 -66 50 --time-range 2026-09-08T20:30:00Z 2026-09-08T20:45:00Z --all-aircraft --source-note 'Historical all-type input; legacy velocity imputation remains' --report NEW-index-report.json
PYTHONPATH=src /path/to/python scripts/benchmark_national_search.py NEW.sqlite NEW_OUTPUT --tile-cells 8
```

Never overwrite old outputs. Use the exact pinned code and restore the checksummed
source Parquet for an exact resource-fixture replay. Producer and dependency
versions affect runtime. All archive downloads are external to this evidence.
Remaining limits include missing receivers/tracks, unmatched proposals, border
coverage, unsupported/supersonic model segments, altitude datums, separate daily
segments, coarse-grid misses, bounded candidate retention, and uncalibrated
sensitivity. None of these receipts establishes the final independent national
real-recording 100 m acceptance target.
