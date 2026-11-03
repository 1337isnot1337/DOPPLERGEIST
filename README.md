<p align="center">
  <img src="assets/dopplergeist-banner.svg" alt="DOPPLERGEIST — Acoustic geolocation through Doppler analysis" width="100%">
</p>

DOPPLERGEIST investigates **where an audio recording was made** by comparing the Doppler patterns of passing aircraft with historical flight trajectories. It combines acoustic measurements, aircraft motion, sound travel time and terrain to rank possible recording locations.

![Spectrogram and scored search grid for a real Livermore aircraft flyover](assets/livermore-real-demo.png)

<sub>From a real aircraft flyover, DOPPLERGEIST’s highest-scoring point landed **481 m from a reference derived from other flight tracks**. This demonstration uses the known aircraft and a bounded time and area; [see the full results and limitations](docs/LIVERMORE_DEMO.md).</sub>

**This is experimental software, still in a very early beta. Contributors welcome.** The local upload application and automatic audio-to-decision pipeline are available on `main`, alongside configured research replays. Independent nationwide accuracy on real recordings has not (YET) been established. I am currently collecting a swath on audio recordings to benchmark this software.

[Current status](#current-status) · [Quickstart](#quickstart) · [How it works](#how-it-works) · [Results](#experimental-results) · [Documentation](#documentation-and-references)

## Current status

| Area | Available now | Entry point or remaining work |
| --- | --- | --- |
| Configured localization | Event measurement, flight ranking and physical refinement | `dopplergeist run` and `dopplergeist measure` on `main` |
| Automatic acoustic discovery | Whole-recording decoding, frequency-track discovery and harmonic grouping without supplied event windows or bands | `scripts/discover_audio.py`; produces event proposals and diagnostics |
| Historical inputs | Reusable flight indexes, gap-aware trajectory queries and cached terrain/geoid data | [Data acquisition and search APIs](docs/DATA_AND_SCALE.md) on `main` |
| Geographic search | Parallel, resumable tiles, joint matching across independent flyovers and disk-backed accounting of candidates discarded by ranking limits | [Search](docs/DATA_AND_SCALE.md#search) and [finite-search evidence](docs/FINITE_SEARCH_PRODUCER.md) on `main` |
| Local upload application | CLI/API orchestration, persistent jobs and inspectable browser results on `main` | `dopplergeist analyze`, `dopplergeist serve` and `dopplergeist job`; see [Local upload workflow](docs/PRODUCT.md) |
| Independent location validation | Real-audio discovery, browser upload and measured-session experiments; no accepted blind real localization | [Real-data verification](#real-data-verification-2026-11-03); [acceptance #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) and [field recordings #53](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53) remain open |

## Quickstart

Requires **Python 3.11+**, **FFmpeg** (`ffmpeg` and `ffprobe` on `PATH`) and Git. Install FFmpeg through your operating system's package manager, then run from a shell on Linux or macOS:

```bash
git clone https://github.com/1337isnot1337/DOPPLERGEIST.git
cd DOPPLERGEIST
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/dopplergeist --version
```

To install the CLI without keeping a checkout, create a virtual environment and run `.venv/bin/python -m pip install "git+https://github.com/1337isnot1337/DOPPLERGEIST.git"`.

Native Windows execution is unverified.

### Analyze from the command line

```bash
.venv/bin/dopplergeist analyze path/to/recording.mp3 --jobs jobs
```

This scans the complete recording and saves an inspectable job. To permit historical search, add `--start-utc` and `--end-utc` for a defensible recording-start window, `--time-source` describing its evidence, and `--online` for public data acquisition. Missing clock evidence returns `needs_input`. 

Initial data acquisition can take hours and tens of gigabytes; [the workflow guide](docs/PRODUCT.md) covers caching, runtime limits and resuming stopped jobs.

The command prints a job ID when queued. In another terminal, run
`.venv/bin/dopplergeist job JOB_ID --jobs jobs --watch` to follow reported
progress, checkpoint rate, and the age of the latest tile and job status update.
Stop a running service-managed job with `.venv/bin/dopplergeist cancel JOB_ID`;
pass `--server-url` when the service uses a non-default port.

### Discover events in a recording

Automatic discovery scans an entire recording for moving acoustic frequency patterns **without hand-selecting event windows or frequency bands**. Replace `path/to/recording.mp3` with your real recording; this step needs no flight-data download or data-service credentials:

```bash
.venv/bin/python scripts/discover_audio.py \
  path/to/recording.mp3 \
  --output results/my-discovery
```

Read `results/my-discovery/summary.json` and the diagnostics under `discovery/`. See [Audio discovery](docs/AUDIO_DISCOVERY.md) for settings, evidence and failure modes.

### Run the local upload application

Start the browser application:

```bash
.venv/bin/dopplergeist serve --jobs jobs --online --max-runtime 14400 --port 8765
```

Open `http://127.0.0.1:8765` and upload a recording. Supply a defensible UTC window for the **first audio sample** to permit historical flight search. The `--online` option can download aircraft and terrain data; archives and indexes can require tens of gigabytes or more and hours, and there is no automatic disk-space limit. See [Local upload workflow](docs/PRODUCT.md) for request fields, runtime limits and CLI alternatives.

## How it works

1. **Measure the audio.** Decode the recording, identify frequency tracks, and group harmonics that belong to the same flyover.
2. **Collect trajectories.** Retrieve aircraft positions for a justified recording-time window and track available data coverage. The default source is the appropriate yearly ADSB.lol historical flight archive, such as [2026](https://github.com/adsblol/globe_history_2026); see [acquisition and cache details](docs/DATA_AND_SCALE.md#acquisition).
3. **Model the sound.** Predict Doppler frequency and arrival time from aircraft trajectories, receiver geometry, and sound propagation.
4. **Compare locations.** Search candidate receiver positions, reconcile independent flyovers, and retain competing explanations rather than forcing an answer.

For more detail please see [Methodology](docs/METHODOLOGY.md).

## Search and scientific limits

The target is a supported location estimate within **1,000 m**, preferably **100–500 m or better**, using real recordings without truth-informed event selection or geographic bounds. Evaluation reports 100/500/1,000 m thresholds without rewriting historical experiments' original thresholds.

Recording-time evidence matters: audio-relative seconds do not identify which day's flights to search. A defensible start time or bounded UTC window is needed; file modification and upload times do not establish the recording clock. The robust search considers all prepared independent flyover groups under one shared clock, with no default two- or three-event cap. Harmonics count once and unconfirmed proposals may remain unmatched. Explicit event, tile or candidate budgets can leave a search incomplete.

The automatic search uses conservative score ceilings before completing every fit: incompatible residuals and an established Top-K cutoff can stop further group fitting at a shared clock. It batches eligible clock fits, reuses exact acoustic calculations in dense tiles, and divides overloaded areas or single-cell clock ranges into checkpointed pieces. [Search screening and real-data timing](docs/DATA_AND_SCALE.md#search) describe the bounds and their measured limits.

At one source-informed receiver point, median scoring time fell from **68.92 to 25.59 CPU seconds**, a **2.69×** speedup. All 3,905 associations across 16 event groups matched the scalar-corrected baseline in three alternating pairs. The [performance report](docs/PERFORMANCE.md) describes this bounded test, which does not establish nationwide runtime or independent location accuracy.

Recent search work makes omitted alternatives and failed model evaluations visible. For more detail see [finite-search evidence](docs/FINITE_SEARCH_PRODUCER.md) and [clock-trial accounting](docs/SCORING_ASSESSMENT.md).

Missing events, incomplete flight coverage, competing locations or inadequate sensitivity evidence can require an **inconclusive** outcome. See [Decision rules](docs/CONFIDENCE.md).

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

The [Eclipse Soundscapes field-audio collection](docs/ECLIPSE_FIELD_CORPUS.md) records scanner results for 100 public-site sources, including failures and clips without proposals. Moving tones are not yet verified aircraft or accepted location benchmarks.

| Test and input | Observed result | Qualification |
| --- | --- | --- |
| Configured reference replay, installed package and fresh checkout | **43.8585 m** from the public reference; 3,587 trajectory segments, 2,525 coarse grid points and 283 ranked rows | Real audio and flight data, but source-informed event windows, frequency bands and regional bounds. The reference coordinate is not surveyed. `accepted_location=false` and model support remains incomplete. |
| Complete one-hour reference MP3 in actual Chromium | 42,085,293-byte upload, 16 acoustic proposals, persistent job and loaded diagnostics, and zero location cards | `needs_input / recording_time_required`. The original sample-zero UTC is unknown, so geographic search did not run. |
| Complete reference MP3 through HTTP, with source-informed clock | 16 independent groups, 18 ridge records and 23 hypotheses; intake through decision verified, followed by browser display and reload | `inconclusive / search_incomplete`. Two tiles exhausted the association budget and 86 lacked terrain. The leading diagnostic hypothesis was about 66 km from the public reference. Regional inputs and a fitted clock do not establish independent accuracy. |
| Four original NASA acoustic recordings with measured GPS | Cub107, Edge038 and Edge066: zero proposals. Edge065: one proposal and a **474.0 m** conditional best grid point | The Edge065 event may be a background aircraft, not the measured drone. **568/4,200** grid points lack support and another mode is 1,899 m from the microphone. No validated localization. |
| Original 246.8-second WSU recording with measured drone telemetry | Four automatic proposals; zero supported fits in 4,992 attempts | Every proposal extends before the published trajectory support. No coordinate or accepted location; supplied trajectory and uncertain relative timing. |
| 40 real smartphone aircraft recordings (automatic MP3 discovery) | Proposals in **36/40** recordings, with 136 groups total | All 40 jobs required recording-time evidence. Groups are not confirmed aircraft detections, and none returned a location. |


Automatic discovery and integration experiments are separate from those configured replays. Integration results below describe their recorded source revisions, including code that remains outside `main`:

- **Event discovery:** frozen synthetic fixtures with three, four and six flyovers yielded **13/13** discovered events with unchanged settings. See [multi-event fixtures](docs/MULTI_EVENT_FIXTURES.md).
- **Full synthetic national searches:** one product-integration run processed **4,940** coarse tiles and ranked a hypothesis **1,046,023 m** from truth first; the correct flight pair was fourth at **6.16 m**. A separate browser/API upload on another integration revision led with a candidate **0.65 m** from truth. **Both ended inconclusive** because alternatives remained unresolved. See [integration evidence](docs/verification/INTEGRATION.md), [product run](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19) and [upload replay](https://github.com/1337isnot1337/DOPPLERGEIST/pull/32).
- **Real acoustic benchmarks:** the [annotation-assisted feature benchmark](docs/PROGRESS.md) detected **33/40** passages, with median speed/slant errors of **6.85% / 15.37%** among detections. Separate automatic discovery produced **102 proposals across 28/40 recordings**. Corrected 300-second Times Square and Statue of Liberty webcam clips each yielded **zero supported proposals** under frozen settings. These datasets lack the established recorder clock and microphone-coordinate evidence needed for location-accuracy validation. See [discovery results](docs/AUDIO_DISCOVERY.md), [timing audit](docs/verification/REAL_DATA_TIMING.md) and [public-camera benchmark](docs/verification/PUBLIC_CAMERA_BENCHMARK.md).

### Reproduce the NASA real-recording benchmark

The four NASA inputs are public original MAT files. The experiment uses their measured aircraft trajectories. Use a fresh output directory for each run.

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

## License

DOPPLERGEIST code is licensed under the [MIT License](LICENSE). External
recordings, flight and terrain data, and other third-party materials retain
their own rights and terms.

## Notes

Vibecoded with love by Cinna Davis, Henrik Lied, and YOU if you contribute to this repo... which you should do!

Follow me on [X](https://x.com/1337isnot1337) and on [LinkedIn](https://www.linkedin.com/in/cinna-davis/)

## AI Usage

Fully vibecoded if it wasn't obvious. Using a series of 6.1 Sol xhigh and Terra xhigh agent swarms. Once we get a working end to end version I'll go through and desloppify to speed things up.

## Documentation and references

- [Methodology](docs/METHODOLOGY.md) — geometry, Doppler and acoustic propagation
- [Installation and reproducibility](docs/SETUP.md) — environments, verification, restoration
- [Pipeline performance measurements](docs/PIPELINE_PERFORMANCE_2026-11-03.md) — real-input timings, comparison controls, and reproduction commands
- [Automatic event discovery](docs/AUDIO_DISCOVERY.md) — detector design and known failure modes
- [Confidence and decision rules](docs/CONFIDENCE.md) — ambiguity, abstention, incomplete coverage
- [Finite-search evidence](docs/FINITE_SEARCH_PRODUCER.md) and [clock-trial accounting](docs/SCORING_ASSESSMENT.md) — retained/discarded candidates and unknown model work
- [Integration verification](docs/verification/INTEGRATION.md) and [2026-11-03 real-data verification](docs/verification/WORKER_E2E_2026-11-03.md) — end-to-end results and caveats
- [Data and search contracts](docs/DATA_AND_SCALE.md) — trajectory indexing, coverage and geographic search
- [Implementation handoff](docs/HANDOFF.md), [acceptance issue](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) and [development discussion](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39) — ongoing work; the handoff includes historical context and is not a current feature inventory

DOPPLERGEIST is an **independent reconstruction** of the approach described in [colsto's video](https://www.youtube.com/watch?v=UytYrhYLOKI), with independently written code. It is not a release by or affiliation with the video's author. External recordings, ADS-B and terrain assets retain their own rights and attribution requirements; see [data provenance](docs/DATA_SOURCES.md). The banner's outlined typography and illustrative model are documented in [asset notes](assets/README.md).

