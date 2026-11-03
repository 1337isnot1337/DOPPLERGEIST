# DOPPLERGEIST

> **WORK IN PROGRESS — NOT COMPLETE.** The automatic MP3-to-location workflow is still under integration and validation. No independently verified nationwide real-audio accuracy claim is available.

DOPPLERGEIST is an independent reconstruction of the aircraft-sound geolocation method described in [colsto's video](https://www.youtube.com/watch?v=UytYrhYLOKI). It measures Doppler curves, matches them against historical ADS-B trajectories, models sound travel time and terrain, and ranks possible recording locations. This is independently written code, not a release from the video author.

**Target:** Analyze an MP3 without manually selected event windows, frequency bands, flight IDs or a truth-derived search region. Up to **1,000 m** location error is acceptable on supported real recordings; **100–500 m or better** is preferred. Report errors at 100, 500 and 1,000 m. A point estimate without adequate evidence must remain **inconclusive**.

## Current status

- **On `main`:** The configured research CLI (`aircraft-geoloc run` and `measure`) works with explicit inputs. Whole-recording MP3 intake and automatic event discovery are available through `scripts/discover_audio.py`. Historical-track indexing, bounded tiled search, multi-event matching, physical refinement and conservative decision logic exist as components. These pieces are not yet exposed as one supported upload command on `main`.
- **In [product PR #19](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19):** The automatic `analyze`, `serve` and `job` commands, persistent jobs, loopback upload interface and result inspection use the real pipeline. **These commands are not in `main` yet.** [Upload verification PR #32](https://github.com/1337isnot1337/DOPPLERGEIST/pull/32) tests the separate product integration through HTTP and browser flows.
- **Still required:** Merge and verify the product integration, establish adequate finite-search and uncertainty evidence, exercise the full four-or-more-event upload path, and evaluate independently timed real recordings with defensible receiver coordinates. The [final acceptance issue #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) remains open.

A defensible recording start time or bounded UTC window is required to select historical aircraft data. File modification or upload time is not proof of the original recording clock. The system must request missing time evidence instead of inventing a timestamp.

The matcher uses all supported independent flyovers, including three, four or more, under one shared clock. Harmonics and fragments of one flyover count once. Unconfirmed acoustic proposals can remain unmatched; work limits and incomplete coverage must be explicit.

## Verification and limitations

### Configured research replays

| Case | Measured result | Limit |
| --- | --- | --- |
| Independent synthetic two-event audio | Original checkpoint: 21.89 m; correct flight pair | Unknown recording start; three candidate regions; truth withheld from search |
| Clean synthetic two-event replay | 15.40 m; correct flight pair | Changed ridge measurements and winner, so not an exact replay of the original checkpoint |
| Independent synthetic known-time event | 40.87 m; correct flight | Manually selected 60-second event |
| Original real two-event recording | 43.86 m from public-platform reference | Source-informed regional bounds and event windows; reference is not surveyed microphone ground truth |
| Original faint real event | 357.47 m from same reference | Clock derived from two-event fit; missed its original 100 m target, despite falling inside the newer 1,000 m distance target |
| Separate 40-passage acoustic benchmark | 33/40 detections; 6.85% median speed error and 15.37% median slant error among detections | Annotation-assisted frequency bands; not location validation |

The original real two-event and faint-event winners reproduce in a clean environment. The synthetic two-event winner changed, and its cause is unresolved. See [clean replay evidence](docs/verification/CLEAN_REPLAY.md) and [CI replay evidence](docs/CI_VERIFICATION_2026-11-02.md). These replays use configured research inputs, not automatic upload.

### Automatic pipeline evidence

- Frozen independent three-, four- and six-flyover MP3 fixtures produced **13/13 discovered events** with unchanged discovery settings. This is event detection, not successful multi-event localization. See [fixtures and receipts](docs/MULTI_EVENT_FIXTURES.md).
- A full 1,180-second synthetic MP3 job in [product PR #19](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19) completed intake, discovery, declared CONUS tiled search, refinement and decision. It processed 4,940 coarse tiles. The leading hypothesis was **1,046,023 m from truth**; the correct pair was fourth at 6.16 m. The result remained **inconclusive**.
- A separate full synthetic browser/API upload in [verification PR #32](https://github.com/1337isnot1337/DOPPLERGEIST/pull/32) returned a leading hypothesis **0.65 m** from truth, but the decision remained **inconclusive / ambiguous_locations**. These are different integration revisions. Neither is an accepted automatic location.
- Corrected 300-second public webcam recordings from Times Square and the Statue of Liberty produced **zero supported event proposals** under frozen settings. Their recorder sample-zero UTC and microphone-location uncertainty were not established, so they cannot validate location error. See [public-camera evidence](docs/verification/PUBLIC_CAMERA_BENCHMARK.md).
- The [historical trajectory audit](research/trajectory-motion/README.md) found input and interpolation artifacts with physically inconsistent modeled motion. Some sequences remain unsupported. The audit does not measure actual aircraft speeds or establish localization accuracy.

Automatic discovery on the separate 40-WAV collection proposed events in 28 recordings and none in 12; it produced 102 proposals overall. These proposals are **not certified aircraft detections**. See [discovery evidence](docs/AUDIO_DISCOVERY.md). The [integration receipts](docs/verification/INTEGRATION.md) distinguish tested `main` revisions from separate product-review combinations. Scores and finite sensitivity envelopes are **not calibrated location probabilities**.

## Install and use the current `main` branch

Requires Python 3.11 or newer, `ffmpeg` and `ffprobe`. Run these commands from the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/make_synthetic_cases.py
.venv/bin/aircraft-geoloc run data/synthetic/two-events.json --output results/replay-two-events
.venv/bin/aircraft-geoloc run data/synthetic/known-time-minute.json --output results/replay-known-minute
```

To run whole-recording **event discovery only**, use a local MP3:

```bash
.venv/bin/python scripts/discover_audio.py path/to/recording.mp3 --output results/new-discovery
```

This script emits acoustic proposals and diagnostics. It **does not** estimate a recording location. For independent multi-event demonstration inputs, see [fixture generation](docs/MULTI_EVENT_FIXTURES.md).

To restore the checksummed regional checkpoint inputs and reproduce the original real case:

```bash
.venv/bin/python scripts/restore_artifacts.py --bundle data-source --bundle data-adsb-derived --bundle data-terrain
.venv/bin/aircraft-geoloc run data/source/reproduce-local.json --output results/new-reference-replay
```

Use a new output directory for each experiment. The restore utility preserves conflicting local files and verifies downloaded hashes. For pinned dependencies, clean installation and selective data restoration, read [SETUP.md](docs/SETUP.md) and [ARTIFACTS.md](docs/ARTIFACTS.md). Large inputs are in the [checkpoint release](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/checkpoint-2026-11-02). The original YouTube MP4 is not redistributed.

## Inputs and physical model

Canonical CSV or Parquet columns are `flight_id,time_s,lat,lon,alt_m,typecode`. Timestamps use Unix seconds or UTC ISO strings. Optional `east_mps,north_mps,up_mps` contain aircraft velocity components. KML `gx:Track` and readsb/ADSB.lol traces have importers. Flight gaps are split, and trajectories are not extrapolated beyond their valid segments. Aircraft-type exclusions are configurable; unknown types and audible jets cannot be discarded unconditionally.

For aircraft position **x** at emission time `tau` and receiver **o**, the research model uses:

```text
t_received = tau + norm(x(tau) - o) / c
frequency = f0 * c / (c + dot(velocity(tau), x(tau)-o)/norm(x(tau)-o))
```

Positive range rate means the aircraft recedes from the receiver. Matching fits a common recording clock and separate source frequencies for each flyover. Scoring uses spectrogram contrast or measured-ridge residuals. Terrain and aircraft altitudes must use a consistent vertical datum; the real configurations include geoid correction.

## Project references

Start with the [methodology](docs/METHODOLOGY.md), [task plan](docs/AGENT_TASKS.md), [implementation handoff](docs/HANDOFF.md) and [decision rules](docs/CONFIDENCE.md). The [issue tracker](https://github.com/1337isnot1337/DOPPLERGEIST/issues/1) and [discussion board](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39) track active integration work. The historical [progress checkpoint](docs/PROGRESS.md) describes an earlier state and is not the current feature inventory.

External audio, ADS-B and terrain assets retain their own licenses and attribution requirements. See [data provenance](docs/DATA_SOURCES.md). This repository does not imply a blanket license for those external assets.
