<p align="center">
  <img src="assets/dopplergeist-banner.svg" alt="DOPPLERGEIST — Acoustic geolocation through Doppler analysis" width="100%">
</p>

DOPPLERGEIST investigates **where an audio recording was made** by comparing the Doppler patterns of passing aircraft with historical flight trajectories. It combines acoustic measurements, aircraft motion, sound travel time and terrain to rank possible recording locations. The application runs locally; there are no plans for a hosted service.

**Experimental software.** The local upload application and automatic audio-to-decision pipeline are available on `main`, alongside configured research replays. Independent nationwide accuracy on real recordings has not been established.

[Current status](#current-status) · [Quickstart](#quickstart) · [How it works](#how-it-works) · [Results](#experimental-results) · [Documentation](#documentation-and-references)

## Current status

| Area | Available now | Entry point or remaining work |
| --- | --- | --- |
| Configured localization | Event measurement, flight ranking and physical refinement | `dopplergeist run` and `dopplergeist measure` on `main` |
| Automatic acoustic discovery | Whole-recording decoding, frequency-track discovery and harmonic grouping without supplied event windows or bands | `scripts/discover_audio.py`; produces event proposals and diagnostics |
| Historical inputs | Reusable flight indexes, gap-aware trajectory queries and cached terrain/geoid data | [Data acquisition and search APIs](docs/DATA_AND_SCALE.md) on `main` |
| Geographic search | Resumable bounded-memory tiles, joint matching across independent flyovers and disk-backed accounting of candidates discarded by ranking limits | [Search](docs/DATA_AND_SCALE.md#search) and [finite-search evidence](docs/FINITE_SEARCH_PRODUCER.md) on `main` |
| Local upload application | CLI/API orchestration, persistent jobs and inspectable browser results on `main` | `dopplergeist analyze`, `dopplergeist serve` and `dopplergeist job`; see [Local upload workflow](docs/PRODUCT.md) |
| Independent location validation | Real-audio discovery, browser upload and measured-session experiments; no accepted blind real localization | [Real-data verification](#real-data-verification-2026-11-03); [acceptance #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) and [field recordings #53](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53) remain open |

Start with automatic discovery on a real recording below. The upload application contains intake, discovery, acquisition, geographic search and decision stages. The verified one-hour real MP3 upload stopped before geographic search because no defensible UTC recording start time was available. Current validation uses real recordings and measured trajectories. New synthetic experiments are stopped. Historical results remain documented.

## Quickstart

Requires **Python 3.11+**, **FFmpeg** (`ffmpeg` and `ffprobe` on `PATH`) and Git. Install FFmpeg through your operating system's package manager, then run from a shell on Linux or macOS:

```bash
git clone https://github.com/1337isnot1337/DOPPLERGEIST.git
cd DOPPLERGEIST
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

Use a new output directory for each experiment. Automatic CI checks installation, source compilation, CLI help and packaged assets without generated data. The [real-world data policy](AGENTS.md#real-world-data-only) supersedes older blanket pytest instructions. For pinned environments and historical clean-install evidence, see [Setup](docs/SETUP.md). Native Windows execution remains unverified.

### Discover events in a recording

Automatic discovery scans an entire recording for moving acoustic frequency patterns **without hand-selecting event windows or frequency bands**. Replace `path/to/recording.mp3` with your real recording; this step needs no flight-data download or data-service credentials:

```bash
.venv/bin/python scripts/discover_audio.py \
  path/to/recording.mp3 \
  --output results/my-discovery
```

Read `results/my-discovery/summary.json` and the diagnostics under `discovery/`. **These are acoustic event proposals, not coordinates or certified aircraft detections.** See [Audio discovery](docs/AUDIO_DISCOVERY.md) for settings, evidence and failure modes.

### Run the local upload application

Start the browser application:

```bash
.venv/bin/dopplergeist serve --jobs jobs --online --max-runtime 14400 --port 8765
```

Open `http://127.0.0.1:8765` and upload a recording. Supply a defensible UTC window for the **first audio sample** to permit historical flight search. Without that time evidence, the application returns `needs_input / recording_time_required`. It does not estimate a location. The `--online` option can download large aircraft and terrain datasets. See [Local upload workflow](docs/PRODUCT.md) for request fields, runtime limits and CLI alternatives.

## How it works

1. **Measure the audio.** Decode the recording, identify frequency tracks, and group harmonics that belong to the same flyover.
2. **Collect trajectories.** Retrieve aircraft positions for a justified recording-time window and track available data coverage. The default source is [ADSB.lol's 2026 historical flight archive](https://github.com/adsblol/globe_history_2026); see [acquisition and cache details](docs/DATA_AND_SCALE.md#acquisition).
3. **Model the sound.** Predict Doppler frequency and arrival time from aircraft trajectories, receiver geometry, and sound propagation.
4. **Compare locations.** Search candidate receiver positions, reconcile independent flyovers, and retain competing explanations rather than forcing an answer.

The central complication is that the plane **moves while its sound travels**. DOPPLERGEIST models emission time separately from reception time. See [Methodology](docs/METHODOLOGY.md) for equations, assumptions, and implementation details.

## Search and scientific limits

The target is a supported location estimate within **1,000 m**, preferably **100–500 m or better**, using real recordings without truth-informed event selection or geographic bounds. Evaluation reports 100/500/1,000 m thresholds without rewriting historical experiments' original thresholds.

Recording-time evidence matters: audio-relative seconds do not identify which day's flights to search. A defensible start time or bounded UTC window is needed; file modification and upload times do not establish the recording clock. The robust search considers all prepared independent flyover groups under one shared clock, with no default two- or three-event cap. Harmonics count once and unconfirmed proposals may remain unmatched. Explicit event, tile or candidate budgets can leave a search incomplete.

Recent search work makes omitted alternatives and failed model evaluations visible. A disk-backed ledger records scored candidates before ranking limits discard them, including the best discarded score. Robust clock trials distinguish evaluated fits and known poor fits from missing or unsupported work; one finite winning score cannot hide unknown competing trials. This accounts for the **evaluated finite grid**. It does not prove that a better location cannot exist between grid points. See [finite-search evidence](docs/FINITE_SEARCH_PRODUCER.md) and [clock-trial accounting](docs/SCORING_ASSESSMENT.md).

Missing events, incomplete flight coverage, competing locations or inadequate sensitivity evidence can require an **inconclusive** outcome. Ranking scores and sensitivity envelopes are not calibrated probabilities. The configured research CLI emits ranked hypotheses; it does not execute the complete upload acceptance workflow. See [Decision rules](docs/CONFIDENCE.md).

Remaining reliability work includes [unsupported trajectory motion and coverage #64](https://github.com/1337isnot1337/DOPPLERGEIST/issues/64), complete measurement/model sensitivity, and independent field evaluation with recorder coordinates and a justified recording clock. The [trajectory investigation](research/trajectory-motion/README.md) documents input-motion failures. Neither a close synthetic candidate nor passing software tests establishes nationwide real-recording accuracy or a calibrated false-localization rate.

## Experimental results

The published project artifacts preserve both successful fits and cases where the system could not justify a location. The following are **historical configured replays**, with their original settings and thresholds:

| Experiment | Reported finding | Important qualification |
| --- | --- | --- |
| Independent synthetic, two events | **21.89 m** error, correct flight pair | Original configured checkpoint; unknown start time, three candidate regions, truth withheld from search |
| Clean synthetic two-event replay | **15.40 m** error | Ridge measurements and winner changed; cause unresolved, not an exact reproduction |
| Known-time synthetic flyover | **40.87 m** error, correct flight | Manually configured 60-second event |
| Original real recording, two flyovers | **43.86 m** from a public reference coordinate | Source-informed regional bounds and event windows; reference coordinate is **not surveyed ground truth** |
| Original faint real flyover | **357.47 m** from the same reference | Clock inherited from the two-event fit; missed its original 100 m target |

The two real-regional winners reproduce in a clean environment. See the [clean replay report](docs/verification/CLEAN_REPLAY.md) and [CI replay evidence](docs/CI_VERIFICATION_2026-11-02.md) for measurements and provenance.

### Real-data verification (2026-11-03)

These experiments used real recordings. The reference replay also used historical flight trajectories and terrain. The NASA tests used measured audio and GPS trajectories. **None established an independently accepted automatic location.**

| Test and input | Observed result | Qualification |
| --- | --- | --- |
| Configured reference replay, installed package and fresh checkout | **43.8585 m** from the public reference; 3,587 trajectory segments, 2,525 coarse grid points and 283 ranked rows | Real audio and flight data, but source-informed event windows, frequency bands and regional bounds. The reference coordinate is not surveyed. `accepted_location=false` and model support remains incomplete. |
| Complete one-hour reference MP3 in actual Chromium | 42,085,293-byte upload, 16 acoustic proposals, persistent job and loaded diagnostics, and zero location cards | `needs_input / recording_time_required`. The original sample-zero UTC is unknown, so geographic search did not run. |
| Four original NASA acoustic recordings with measured GPS | Cub107, Edge038 and Edge066: zero proposals. Edge065: one proposal and a **474.0 m** conditional best grid point | The Edge065 event may be a background aircraft, not the measured drone. **568/4,200** grid points lack support and another mode is 1,899 m from the microphone. No validated localization. |
| 40 real smartphone aircraft recordings (automatic MP3 discovery) | Proposals in **36/40** recordings, with 136 groups total | All 40 jobs required recording-time evidence. Groups are not confirmed aircraft detections, and none returned a location. |

The reference replay and browser upload test different paths. The replay performs a geographic ranking with supplied research settings. The browser test starts with an unconfigured MP3 upload but stops at the missing recording-time gate. The NASA tests use supplied aircraft trajectories and a restricted footprint. They do not test automatic historical flight association.

The [worker report](docs/verification/WORKER_E2E_2026-11-03.md) records inputs, source revisions, outcomes and limits. See the [configured replay workflow](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41580126694), [passing real Chromium job](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41580605939/job/125734292619), [passing NASA job](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41580450522/job/125733788989) and [40-recording result table](benchmarks/real-discovery-20261103.csv). The configured replay *step* passed in the first workflow, but that workflow ended in failure due to separate verifier and downloader defects. Both utility defects were fixed and their own jobs passed.

Automatic discovery and integration experiments are separate from those configured replays. Integration results below describe their recorded source revisions, including code that remains outside `main`:

- **Event discovery:** frozen synthetic fixtures with three, four and six flyovers yielded **13/13** discovered events with unchanged settings. This establishes detection on those fixtures, not accepted localization. See [multi-event fixtures](docs/MULTI_EVENT_FIXTURES.md).
- **Full synthetic national searches:** one product-integration run processed **4,940** coarse tiles and ranked a hypothesis **1,046,023 m** from truth first; the correct flight pair was fourth at **6.16 m**. A separate browser/API upload on another integration revision led with a candidate **0.65 m** from truth. **Both ended inconclusive** because alternatives remained unresolved. Neither is an accepted automatic location. See [integration evidence](docs/verification/INTEGRATION.md), [product run](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19) and [upload replay](https://github.com/1337isnot1337/DOPPLERGEIST/pull/32).
- **Real acoustic benchmarks:** the [annotation-assisted feature benchmark](docs/PROGRESS.md) detected **33/40** passages, with median speed/slant errors of **6.85% / 15.37%** among detections. Separate automatic discovery produced **102 proposals across 28/40 recordings**; these are not certified aircraft detections. Corrected 300-second Times Square and Statue of Liberty webcam clips each yielded **zero supported proposals** under frozen settings. These datasets lack the established recorder clock and microphone-coordinate evidence needed for location-accuracy validation. See [discovery results](docs/AUDIO_DISCOVERY.md), [timing audit](docs/verification/REAL_DATA_TIMING.md) and [public-camera benchmark](docs/verification/PUBLIC_CAMERA_BENCHMARK.md).

### Reproduce the NASA real-recording benchmark

The four NASA inputs are public original MAT files. The experiment uses their measured aircraft trajectories. It is a supplied-track search, not an automatic aircraft-identification test. Use a fresh output directory for each run.

```bash
.venv/bin/python scripts/download_nasa_cases.py --output data/nasa-originals

PYTHONPATH=src .venv/bin/python scripts/benchmark_nasa_session.py prepare \
  --source-directory data/nasa-originals \
  --case-manifest benchmarks/nasa-session-cases-20261103.json \
  --output results/nasa-replay/prepared

PYTHONPATH=src .venv/bin/python scripts/benchmark_nasa_session.py search \
  --inputs results/nasa-replay/prepared/search-inputs.json \
  --domain results/nasa-replay/prepared/search-domain.json \
  --output results/nasa-replay/search

PYTHONPATH=src .venv/bin/python scripts/benchmark_nasa_session.py evaluate \
  --search-directory results/nasa-replay/search \
  --truth results/nasa-replay/prepared/evaluation-truth.json \
  --output results/nasa-replay/evaluation.json
```

See [NASA benchmark setup and results](benchmarks/README.md#real-nasa-supplied-trajectory-session-benchmark) for input checks, the shorter-window comparison and why the 474 m conditional fit is inconclusive. The source recording-time axis lacks an established calendar date.

### Replay the historical reference case

Large research inputs live in checksummed release assets. With an authenticated GitHub CLI (`gh`) that can access the release, restore only the regional replay's required bundles:

```bash
.venv/bin/python scripts/restore_artifacts.py \
  --bundle data-source --bundle data-adsb-derived --bundle data-terrain
.venv/bin/dopplergeist run \
  data/source/reproduce-local.json \
  --output results/my-reference-replay
```

The restorer checks hashes and preserves conflicting local files. The original source YouTube MP4 is not redistributed. See [artifact restoration](docs/ARTIFACTS.md) and the [checkpoint release](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/checkpoint-2026-11-02).

## License

DOPPLERGEIST code is licensed under the [MIT License](LICENSE). External
recordings, flight and terrain data, and other third-party materials retain
their own rights and terms.

## Documentation and references

- [Methodology](docs/METHODOLOGY.md) — geometry, Doppler and acoustic propagation
- [Installation and reproducibility](docs/SETUP.md) — environments, verification, restoration
- [Automatic event discovery](docs/AUDIO_DISCOVERY.md) — detector design and known failure modes
- [Confidence and decision rules](docs/CONFIDENCE.md) — ambiguity, abstention, incomplete coverage
- [Finite-search evidence](docs/FINITE_SEARCH_PRODUCER.md) and [clock-trial accounting](docs/SCORING_ASSESSMENT.md) — retained/discarded candidates and unknown model work
- [Integration verification](docs/verification/INTEGRATION.md) and [2026-11-03 real-data verification](docs/verification/WORKER_E2E_2026-11-03.md) — end-to-end results and caveats
- [Data and search contracts](docs/DATA_AND_SCALE.md) — trajectory indexing, coverage and geographic search
- [Implementation handoff](docs/HANDOFF.md), [acceptance issue](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) and [development discussion](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39) — ongoing work; the handoff includes historical context and is not a current feature inventory

DOPPLERGEIST is an **independent reconstruction** of the approach described in [colsto's video](https://www.youtube.com/watch?v=UytYrhYLOKI), with independently written code. It is not a release by or affiliation with the video's author. External recordings, ADS-B and terrain assets retain their own rights and attribution requirements; see [data provenance](docs/DATA_SOURCES.md). The banner's outlined typography and illustrative model are documented in [asset notes](assets/README.md).
