# Implementation handoff

## Current owner priority: optimization (November 3)

Strengthen the cheap-to-expensive search hierarchy before further large national
searches. Do not copy manually selected speed/distance bands into automatic
discovery, or silently remove jets, single-event hypotheses or missing data.

Two exploratory optimizations were tested and **not landed**, because the existing
batch fit cache changed their performance benefit. On real automatic associations,
early residual rejection reduced an uncached replay from about8.0–8.3s to5.75s,
but a production-cache comparison was slower. Bounded acoustic-sample reuse cut
101,955 retarded-time sample evaluations to4,259 and preserved all70 result rows
exactly, but still made602 rather than609 acoustic calls and did not improve
runtime consistently. Candidate elimination alone is not a measured speedup.
The next concrete experiment is batching the shared-clock sample union before
fitting, reducing function calls as well as sample count. Another available task
is processing larger matched subsets first and pruning below Top-K using the
certified score ceiling of one unit per matched group, while preserving finite
mode bounds. No experimental screening/cache change was applied to production.

The parallel [real-audio collection](REAL_AUDIO_CORPUS.md) has392 source records
and18 completed scans; the requested20-known/5-unknown usable benchmark is still
unmet. Its source table retains failures and negatives. No new corpus recordings
were matched to flights or localized.

The [swarm task plan](AGENT_TASKS.md) provides 12 actionable GitHub issues,
dependencies, suggested agent allocation and a copyable assignment prompt.

## Read first

The user wants a full MP3-upload-to-location pipeline with automatic Doppler-event
detection. Up to **1,000 m** error is acceptable; **100–500 m or better** is
preferred. Report all three thresholds. Whole-recording intake, automatic discovery
and bounded tiled search are connected to the local upload application on `main`;
the configured research CLI also remains available with manually selected events.
Independent real-recording acceptance remains open. Check the
[README](../README.md), [pinned verification note](VERIFICATION_2026-11-03.md) and
current PR state before making a present-tense feature assessment. Do not treat a
regional reference case or a synthetic result as nationwide real-audio validation.

The original implementation was not released. This repository contains our
independent implementation and the accumulated evidence, including unsuccessful
cases. [PROGRESS.md](PROGRESS.md) lists the verified results and limits.

## Original work-area split

This table preserves the initial planning split. It is not an inventory of missing
features or a new assignment; use current issues and the discussion board for those.

| Area | Main files | Concrete next result |
| --- | --- | --- |
| Event discovery | `audio.py`, new discovery module | Full-file event proposals without supplied windows/bands; harmonic deduplication; noise-only rejection; saved diagnostic evidence |
| Upload/orchestration | `cli.py`, `pipeline.py`, new interface | MP3 input, explicit recording date/time uncertainty, detection-to-search orchestration, progress and inconclusive results |
| Search scale | `search.py`, `terrain.py`, `tracks.py` | Bounded-memory tiled national search with preserved global timing and comparable ranking |
| Validation | `scripts/`, `tests/`, separate output directories | Independent real cases with withheld location, known audio clock, and reported misses/false matches |

These are suggested boundaries, not assignments. Coordinate before changing
shared files. Preserve existing evidence; write new runs to new directories and
record the implementation commit, input hashes, configuration and evaluation scope.

## Replay

Install as in the README and restore release assets using [ARTIFACTS.md](ARTIFACTS.md).
The real regional replay requires source, ADS-B-derived and terrain bundles:

```bash
.venv/bin/dopplergeist run data/source/reproduce-local.json --output results/replay-reference
.venv/bin/dopplergeist run data/source/reproduce-faint-alltypes-local.json --output results/replay-faint
.venv/bin/python scripts/benchmark_real_features.py
```

The benchmark script currently uses its fixed `results/real-feature-benchmark`
output path. Preserve/move that restored directory before rerunning the benchmark.
The full raw ADS-B archive is optional for these replays; the derived Parquet
files are sufficient. The original source MP4 is not uploaded, at the user's request.

## Important pitfalls

- The high-quality two-event case uses source-informed speed, slant and frequency
  bounds. Ridge extraction within selected bands is not event discovery.
- The faint event's best matching track is a CRJ9 jet. Removing every jet prevents
  this case from succeeding. Unknown aircraft types must also be retained.
- Its straight-pass fit suggests about 1 km slant, while the matching real track
  passes at about 4.9 km from the public reference. Tight filters derived from a
  straight-flight fit can exclude curved real trajectories.
- The faint-event result remains 357.47 m off. Its clock comes from the other
  two events; it is not an independent known-time success.
- The prominent raw-audio events are near 2156 s and 3076 s; some video interfaces
  display times offset by 3600 s. The faint raw-audio window is 1250–1310 s.
- Readsb traces in the daily tar are gzip compressed even when named `.json`.
  The type dictionary uses dictionaries such as `{"desc":"L2J","wtc":"M"}`.
- Geometric altitude and barometric fallback are labelled separately. Ground DEM
  orthometric height needs the configured geoid conversion for GNSS comparisons.
- `search.cpa_table_dense` is a retained test oracle. The production sparse CPA
  path must retain multiple local approaches and match the reference on small cases.
- Event clocks remain locked together. Independent shifts can manufacture a match.
- The configured research pipeline preserves supported rankings across typed
  acoustic-support failures and reports excluded work. An empty candidate set
  produces a report without a best hypothesis. This research report does not
  establish an accepted automatic location; inspect its explicit coverage limits.
- The 40-passage dataset supplies helpful frequency annotations but lacks the
  explicit recorder-coordinate/audio-clock evidence needed here for location tests.

## Data inventory

- `data/source/`: source captions, transcript, still frames, reference WAV, configs,
  downloaded documentation, metadata and logs. Failed exploratory outputs are kept.
- `data/adsb/2026-09-08/`: raw daily archive parts, provenance, type database,
  27,840,403-row CONUS prop/unknown Parquet, regional Parquet, and a 15-minute
  all-type CONUS Parquet for the faint case.
- `data/terrain/`: geoid, GLO-30 regional tile and cached GLO-90 tiles/catalogue.
- `data/research/`: checksum-verified Zenodo dataset, extracted recordings, tracks,
  annotations and papers.
- `data/synthetic/`: deterministic audio, tracks, configurations and separate truth.
- `results/`: complete successful, failed and exploratory output directories.

The release manifest records every exported file and its hash. Historical reports
retain original local paths; executable configs use relative input paths.
