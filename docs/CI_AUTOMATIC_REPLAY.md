# Automatic synthetic CI replay

The [runner](../scripts/ci_automatic_replay.py) uses the actual automatic CLI with the complete generated synthetic fixture. This document does not report a successful automatic run.

## Usage

Use a checkout with all automatic producer modules and `scripts/ci_checkpoint_replay.py`. When a required module is absent, the runner fails explicitly.

Use Linux with Python 3.11 or later and FFmpeg with the `libmp3lame` encoder. Keep `ffmpeg` and `ffprobe` on `PATH`.

From the repository root, install the project dependencies:

```bash
python -m pip install -e . pytest
```

Use a new output directory for each run:

```bash
python scripts/ci_automatic_replay.py --output results/ci-automatic --timeout-s 1800
```

The runner refuses existing output directories. Acceptance returns `0`. Failures return `1`, and invalid arguments return `2`.

For the stdlib control tests, run:

```bash
python -m unittest discover -s tests -p test_ci_automatic_replay.py -q
```

These controls do not establish localization success.

## Fixture and request

The unchanged generator creates the full 1,180-second recording and all seven trajectories. Every sample, distractor, and aircraft class remains, including jets.

The runner assigns random opaque flight IDs and randomizes trajectory order. An exact row-multiset comparison verifies that all other values remain unchanged. The labeled CSV and identity mapping reside in `evaluation/`.

The request contains the MP3, CONUS coverage, and generator clock: epoch `1790000000`, or `2026-09-21T14:13:20Z`. It contains no manual events, bands, selected flights, or recorder coordinates.

The receiver scope is `[-125, 24, -66, 50]`. The synthetic source envelope `[-126, 23, -65, 51]` includes the acoustic border margin. Completeness applies only to the seven-track simulation.

The operator configuration uses absolute index paths, offline data, 120 m terrain, 343 m/s sound speed, and 20,000 m acoustic range. The search manifest records the actual `SearchBudget` defaults.

## Actual stages and truth separation

The runner performs these stages:

1. Freeze source files and import actual producers in a separate process.
2. Run the independent generator.
3. Relocate truth and manual configuration files without parsing them.
4. Assign opaque IDs and convert every trajectory to indexed Parquet.
5. Verify that `FlightIndex` returns all seven complete trajectories.
6. Encode the full WAV to MP3 at 8 kHz and 32 kbit/s.
7. Run `aircraft_geoloc.cli analyze` and its actual job worker.
8. Collect intake, discovery, national search, refinement, and decision artifacts.
9. After clean CLI termination and terminal job status, read truth and map expected flight IDs.
10. Evaluate candidate errors and write the acceptance receipt.

Forced exits and nonterminal results prevent evaluation. The identity transformation does not read `truth.json` or select trajectories by their labels.

Truth separation is procedural. Generator source and evaluation files remain accessible without operating system isolation.

## Acceptance

Every condition must pass:

- The CLI exits without a timeout or error, and JobResult reports `succeeded`.
- The leading candidate has horizontal WGS84 geodesic error strictly less than 100 m and correct distinct flight IDs.
- The leading candidate matches at least two independent event groups. Harmonics count once. Unknown or duplicate event IDs fail.
- Synthetic coverage is complete, with available data and consistent search counts.
- The request, uploaded bytes, operator configuration, and frozen implementation pass provenance checks.
- Required artifacts exist, and decision and search artifacts agree with the result.
- A reported success does not contradict explicit `alternative_modes_exhaustively_assessed: false` evidence.

The last condition guards a known integration contradiction. A completed top-k search does not establish exhaustive assessment of alternative modes.

`supported_decision` preserves the reported status. `candidate_evaluations` records location errors separately. Close inconclusive candidates and reported successes with contradictory evidence fail acceptance.

## Budgets and retained evidence

The default total budget is 1,800 seconds, including preparation. Preflight has a 90-second cap. Generation, indexing, and encoding each have a 240-second cap within that budget.

The worker receives the remaining budget minus 30 seconds. The outer CLI timeout permits another 10 seconds for cleanup. The [workflow](../.github/workflows/automatic-replay.yml) permits a 32-minute replay step within a 40-minute job.

The runner preserves completed and partial artifacts after failures:

| Output | Contents |
|---|---|
| `acceptance.json` | Stage status, execution records, errors, limits, checks, and acceptance outcome |
| `artifact-manifest.json` | File hashes, with explicit evaluation-file inclusion status |
| `implementation/` | Frozen source files and the generator |
| `preflight.json`, `indexing.json`, `logs/` | Producer interfaces, complete trajectory inventory, index evidence, and subprocess logs |
| `generated/` | Generated audio, opaque trajectories, Parquet, and the flight index |
| `jobs/` | Actual requests, source provenance, stage artifacts, decision, result, and worker log |
| `evaluation/` | Truth, labeled source trajectories, identity mapping, and unused manual configuration |
| `job-status-history.jsonl` | Observed job transitions at 0.2-second intervals. Short stages can escape observation. |

Without evaluation, the manifest excludes evaluation files and `truth.json`. Missing stage artifacts remain explicit failures.

Actions uploads available evidence after ordinary failures, but excludes WAV and MP3 files. Local output retains both audio files and hashes. Failed repository tests prevent the replay step.

## Limits

This synthetic replay does not establish independent real-recording accuracy or nationwide real-data completeness. The clock, terrain, and aircraft universe come from the generator.

The replay does not exercise HTTP upload, browser behavior, live flight acquisition, or live terrain acquisition. Source hashes support inspection but do not establish scientific success.

## Recorded execution and threshold context

This harness preserves the original strict 100 m replay criterion. Current project instructions accept up to 1,000 m, with 100–500 m preferred; the [2026-11-03 evidence note](../evidence/verification/ci-automatic-20261103/README.md) reports the observed recording at all three thresholds without changing the historical decision or receipt.

The actual integrated run returned inconclusive because competing flight associations remained. A correct-pair candidate at rank four does not pass the leading-result gate. The note records exact source revisions, all candidate evaluations, and the resource-measurement limitation of that historical run.
