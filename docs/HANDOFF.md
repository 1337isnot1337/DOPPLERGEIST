# Implementation handoff

## Optimization priority: merged improvements (November 3)

The requested cheap-to-expensive screening work is now on `main`: PR #158 added
the conservative broad-window measured-ridge screen; PR #169 added a fixed-clock
event/flight precheck; PR #170 batches compatible clock fits; PRs #173–174 advance
fit pruning and adaptive tile handling. On one real regional development point,
#158 preserved the same 92 retained rows while reducing full nonlinear fits from
30,361 to 17,202 and process CPU from 48.27 to 30.04 seconds. That is a measured
local improvement, not a nationwide runtime or localization-accuracy result. The
manually estimated narrow speed/range bands from the reference video were not
copied into automatic rejection rules.

PR #175 corrects acoustic-bound provenance, #180 screens later event clocks,
#181 reports completed parallel checkpoints, and #182 retries overloaded track
queries with the existing conservative distance sieve. A real overloaded cell
retained 614 of 1,929 queried tracks, including all 200 unsupported tracks;
full and filtered scoring had identical results and retention checksums. The
unsupported motion remains a limitation, not a verified absence of aircraft.
PR #188 adds resumable clock partitions for single cells that exceed the
association-count limit. The full-day overloaded cell's 23,136 associations
were preserved across eight partitions; 142 tracks remained unsupported. See
[DATA_AND_SCALE](DATA_AND_SCALE.md) for the scope of these checks.
PR #191 excludes unsupported trajectories only when their entire spline is
provably outside the search radius. PR #193 adds bounded exact-input acoustic
reuse for dense tiles and an explicit upload-search worker setting. A complete
3,795-association partition preserved its full payload and retention checksum;
its CPU time changed from 76.05 to 74.60 seconds. A complete 19,341-association
partition also preserved its payload and checksum, with CPU time changing from
276.99 to 250.88 seconds. Neither measurement predicts nationwide runtime or
establishes a location.
PR #196 removes the automatic CPA filter's unsupported minimum speed and
near-sonic maximum. On one real cell, five passes below 1 m/s admitted 1,166
additional associations while retaining all 23,136 earlier associations. The
finite emitted-frequency range remains a separate modeling prior.

The full-day reference upload and independent real-world evidence remain open. The
[real-audio collection](REAL_AUDIO_CORPUS.md) now includes a 314-video scanner
survey, a 155-clip licensed AeroSonicDB scanner-only sample, and a 25-row reviewed
candidate index. In the AeroSonicDB sample, 51/125 publisher-labeled aircraft
clips and 0/30 ambient clips produced scanner proposals; publisher coordinates
are nearby-place references, not exact microphone locations. The requested set of
20 known-location usable aircraft recordings plus five unknown-location usable
aircraft recordings is still unmet: publisher site coordinates do not establish
microphone accuracy, and moving-tone review does not confirm aircraft identity.
No new corpus recordings were matched to flights or localized.

The [swarm task plan](AGENT_TASKS.md) provides 12 actionable GitHub issues,
dependencies, suggested agent allocation and a copyable assignment prompt.

## Full-day reference upload (November 3)

The public source is [the original audio/video](https://www.youtube.com/watch?v=4CxVxuMVkMc);
the separate [method video](https://www.youtube.com/watch?v=UytYrhYLOKI) explains
the analysis. On November 3, the source upload was titled “Unknown location -
raw audio” and its video track was 128×128 pixels. Frames inspected at 0 and 3
seconds were identical and mostly black with a tiny landscape; they did not
establish a precise recording location. The remainder of the video was not
visually inspected. This check is evaluation-only and supplies no search inputs.
The uploaded MP3 has SHA-256
`674df668c25608ef3e9199bf3b48d760642456d679729c9661ac5cb2a22e179c`.
The automatic test uses the whole recording, no supplied flight IDs or selected
location, CONUS coverage, and a broad 2026-09-08 00:00 to 2026-09-09 12:00 UTC
window covering the stated local calendar day without a start time. Audio
discovery produced 17 ridges; the daily ADSB.lol indexes retain all aircraft
types. A video image can help check a result, but is not by itself a precise
recorder GPS measurement.

At this handoff the upload search is still running; no coordinate has been
accepted. On the originating machine, the job, `resume.json`, discovery output,
search checkpoints and archived earlier revisions are under
`/home/cinna/.local/state/dopplergeist-original-upload-20261103/jobs-current/a90452172daf453986cf9bed846b0e2d/`.
The active search uses the code merged at `c259f38` and run hash
`b5f83ebb72f3cf03e4b1d10a9b48f5112800568b5fa1f2181f18418a8c9139c5`;
check its current API/status and source identity before intervening. The separate
homelab stages tiles under the same identity; its coordinator imports verified
results only after pausing the local job. The local search is configured for 12
workers and homelab stages with eight. A monitor resumes only the configured
wall-time timeout after transferring available remote checkpoints; it does not
resume a user cancellation or another failure. Operator-local cross-host helpers
and logs are under `/home/cinna/.local/state/dopplergeist-cross-host-parity-20261103/`;
they are not a portable distributed CLI. The homelab disk guard stops only the
identified staging process group below 15 GiB free; the coordinator then imports
its completed checkpoints. The guard and its log are also in homelab's
`~/.cache/dopplergeist-multicore-20261103/`. A search checkpoint from different
code must not be mixed in without a specifically validated migration. The only such
migration used here accepts strictly empty root tiles after checking both
identities and ledger checksums. On the switch to `c259f38`, 413 such tiles with
zero receiver grid points were migrated; the preceding search is archived locally
as `search-before-motion-c259f38`. Check final coverage, unsupported-motion and
retention evidence before describing any candidate as a localization. Main also
contains a newer harmonic-ambiguity confidence check from PR #192, which is not
in the active search process. Its aligned-sample heuristic flagged no pair when
run over all 17 discovered ridges from this upload; this does not establish that
the groups are independent. Apply current confidence checks to the final
matched evidence before accepting a result.

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
