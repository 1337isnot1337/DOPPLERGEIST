# Checkpoint: 2026-11-02

The implementation campaign is paused at this handoff. Publishing the existing
code and artifacts does not mark the automatic-upload objective complete.

## Acceptance target

Upload an MP3, discover its usable Doppler events automatically, match historical
aircraft trajectories, and return a supported recording-location estimate. The
user accepts approximately 100 m error. Missing evidence must produce an explicit
inconclusive result rather than an unsupported precise coordinate.

## Implemented

- Audio/video decoding through ffmpeg; spectrogram contrast, bounded-slope Viterbi
  ridge extraction, straight-pass fitting, and noise/detection checks.
- CSV, Parquet, KML and readsb trajectory import; type classification, geometric
  altitude handling with labelled fallbacks, and track-gap splitting.
- WGS84 ECEF geometry, cubic Hermite trajectories, emission-time sound propagation,
  actual radial-velocity Doppler modelling, and no extrapolation.
- Terrain/geoid raster sampling, cached Copernicus GLO-90 coverage, corridor grids,
  sparse CPA search, event-offset and silence filters, locked multi-event scoring,
  refinement, and inspectable JSON/CSV/NPZ/PNG outputs.
- Download/ingestion scripts, an independent synthetic audio generator, and a
  40-recording real feature benchmark.

## Evidence

| Artifact directory | Finding |
| --- | --- |
| `results/synthetic-two-events/` | Correct pair, 21.8855 m position error, -0.3426 s clock error |
| `results/synthetic-known-minute/` | Correct flight, 40.8744 m position error |
| `results/reference-local/` | PC12 `a1dfeb:1` + B350 `ace391:3`; 43.8585 m from mapped public-platform coordinate |
| `results/reference-local-fast/` | Same winning position and score as the preceding run; 46.26 s versus 103.09 s recorded runtime |
| `results/reference-faint-alltypes-local/` | CRJ9 `a38237`; 357.47 m error; fails the 100 m target |
| `results/real-feature-benchmark/` | 33/40 detections, zero processing errors; detected-case median absolute speed/slant errors 6.85%/15.37% |

The real two-event winning point is 40.8769317589, -73.5249822950. The comparison
point is the public nest-platform listing at 40.8766, -73.5247, whose precision and
physical accuracy are limited. The search used a regional box informed by the
source video. It is not a blind country-wide localization result.

The inferred recording start is 2026-09-08 20:17:29.662 UTC. The faint-event
configuration rounds that result to 20:17:30 UTC; it is not an independently
known recording clock. The video's stated 20:37 UTC and its various displayed
timelines have not been fully reconciled.

The feature benchmark uses supplied harmonic-band annotations and contains
substantial outliers. It validates acoustic measurements only. The synthetic
renderer does not call the search propagation model, and its truth is read only
for evaluation after search.

Fresh publication check: **11 tests passed**, covering analytic retarded-time
physics, full Unix timestamps, no extrapolation, repeated approaches, sparse/dense
CPA agreement, filters, shared event timing, noise rejection, altitude decoding,
and terrain/geoid sampling. These tests do not establish automatic discovery or
national-scale localization.

## Remaining work

1. Automatic full-recording event discovery and harmonic grouping, replacing manual
   event windows and frequency bands.
2. An MP3 upload interface and orchestration, including recording-date/time-window
   input when metadata do not establish it.
3. Reliable candidate selection under curved flight paths, source-frequency drift,
   low SNR, altitude uncertainty and missing flight data.
4. Scalable national search and independent real tests with withheld location and
   independently established recording times.
5. Confidence/ambiguity reporting and negative controls.

See [HANDOFF.md](HANDOFF.md) for suggested separable work and exact replay commands.
