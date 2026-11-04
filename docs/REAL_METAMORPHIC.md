# Real recording representation checks

Issue [#61](https://github.com/1337isnot1337/DOPPLERGEIST/issues/61) requires fresh
end-to-end runs for equivalent representations of actual recordings.
The runner in `scripts/run_real_metamorphic.py` executes these runs through the
local HTTP upload service. It accepts a recorded source, a recording-start UTC
window, and an offline operator configuration.

Each arm starts a new service and job. Intake, discovery, selection, matching,
search, refinement, decision and serialization run from the uploaded bytes.
The runner shares only frozen historical indexes and terrain. It does not
resume audio or search checkpoints. The HTTP verifier checks the actual stage
artifacts and the persisted terminal result.

## Frozen protocol

The versioned protocol is
[`verification/metamorphic_protocol_v1.json`](verification/metamorphic_protocol_v1.json).
It was committed before the development matrix ran. It has nine sequential arms:

| Arm | Change from the baseline |
| --- | --- |
| Baseline | MP3, 128 kb/s, 48 kHz, mono |
| Low bitrate | 64 kb/s |
| High bitrate | 192 kb/s |
| Sample rate | 44.1 kHz |
| Gain | −6 dB |
| Channels | Two identical channels |
| Leading silence | 17.25 seconds |
| Short discovery chunks | 60-second chunks, 30-second overlap |
| Long discovery chunks | 180-second chunks, 60-second overlap |

All encodings start from the complete source recording's arithmetic channel
mean at 48 kHz. No arm is encoded from another MP3 arm. The baseline keeps the
operator's discovery settings. The current defaults are 120/60 seconds.

Only `operator.discovery.chunk_s` and `overlap_s` are exposed chunk controls.
The protocol explicitly lists unsupported upload, decoder and detector controls.
It does not insert hooks into the source algorithms.

Each job has a 240-second runtime limit and a 300-second client deadline.
The encoding/decode command limit is 300 seconds. Pipeline time is at most
45 minutes across nine client deadlines, plus preparation and cleanup.
Different budgets can be declared at preparation, before any outcomes exist.

Tolerances are fixed in the protocol: 2 ms for duration and residual alignment,
1 second for mapped event edges and fitted clocks, 2 Hz for median ridge
frequency, and 0.05 per matched group for comparable normalized scores.
Usability also requires nonclipping decoded peaks and gain-corrected PCM
NRMSE at most 0.15. Group counts, flight associations and score units must agree.
The runner reports displacement thresholds at 100, 500 and 1,000 metres.
Accepted locations that move over 1,000 metres receive a separate serious flag.

The PCM calculation reads bounded blocks. Lag checks use twelve fixed short
windows, not full-hour correlations. A measured lag is reported; it does not
shift samples to improve the result. Native-rate decoded peaks and identical
stereo channels are checked separately from the 4 kHz analysis PCM.

## Clock mapping

If leading silence is Δ seconds, subtract Δ from **both** sample-zero UTC
window endpoints. Subtract Δ from detected audio-relative times for comparison.
Add Δ to the fitted sample-zero UTC to recover the original recording clock.

For example, 20:17:20–20:17:40 UTC becomes 20:17:02.750–20:17:22.750 UTC
after 17.25 seconds of padding. The physical time of each recorded sound stays
the same. The runner retains codec skip/discard metadata, decoded sample counts,
and residual lag checks. Container start time is not a recording clock.

## Run

Use an installed checkout with FFmpeg and the repository's dependencies.
The request must have a defensible time window. Use absolute local paths for
historical indexes and terrain, or run preparation where relative paths resolve.
Use a stopped, immutable data cache. Active job directories are not data inputs.

```bash
PYTHONPATH=src python scripts/run_real_metamorphic.py prepare \
  --audio /absolute/path/actual-recording.wav \
  --request /absolute/path/request.json \
  --operator /absolute/path/operator.json \
  --source-note 'Identify the actual recorded source and its permission/provenance' \
  --scope-note 'Describe the search scope, clock evidence and evaluation limits' \
  --output /absolute/path/new-frozen-plan

PYTHONPATH=src python scripts/run_real_metamorphic.py run \
  --plan /absolute/path/new-frozen-plan/plan.json \
  --output /absolute/path/new-matrix-run
```

Preparation writes an immutable plan before encoding. It pins source bytes,
configuration, historical inputs, terrain, source code, native binaries,
dependencies, backend environment and FFmpeg version. Runs refuse changed
inputs. Use `--frozen-input PATH` for an additional immutable local dependency.
Every output directory must be new.

The runner preserves encoded inputs, exact transformation commands, actual
job artifacts and observations for every arm. It continues after an ordinary
arm failure. It preserves pending arms on interruption or changed inputs.
An unusable encoded arm still reaches the HTTP pipeline. Encoding failures
remain explicit failures.

`report.json` contains all pairwise comparisons. `report.md` gives a short
case table. Event matching uses a one-to-one assignment based on mapped time
overlap and ridge frequency. It reports unmatched ridges/groups, group splits,
group merges, and ambiguous alternatives. IDs and row positions do not define
correspondence. Retained distant modes are compared separately.

Each case includes a one-arm reproducer command. The `--case` option creates
a fresh job and records the other arms as not selected. It cannot pass the
full-matrix requirement. The `report` command compares preserved observations;
it never counts as another end-to-end run.

Exit zero requires all nine usable arms to reach the full pipeline and remain
within the declared comparison tolerances. Exit one preserves incomplete runs
or observed differences. An inconclusive scientific decision is not itself a
runner failure when the complete pipeline ran. It remains an inconclusive
location result.

The full-path count uses the verifier's stronger requirement: every stage must
be verified and at least one diagnostic candidate must survive. Empty outcomes
remain in the report. A separate count records all observed stage sequences.
Neither count requires a supported location decision.

## Scope of the development run

The affordable development control uses the whole released reference recording,
a source-informed regional box, a narrow source-informed UTC window, and
incomplete historical flight coverage. It cannot satisfy national acceptance.
It does not establish independent location accuracy.

No eligible independent truth is supplied in this protocol. Truth errors at
100/500/1,000 metres remain explicitly unevaluated. Pairwise displacement is
reported separately. A future eligible national evaluation needs its own
predeclared request, data, budgets and evaluation-only truth protocol.

Focused contract checks use archived real ridge observations and an optional
short actual recording. They do not replace any full-recording arm:

```bash
DOPPLERGEIST_REAL_METAMORPHIC_AUDIO=/absolute/path/actual-short-recording.mp3 \
  PYTHONPATH=src pytest -q tests/test_real_metamorphic_runner.py
```
