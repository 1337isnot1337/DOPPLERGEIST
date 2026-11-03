# Four-flyover browser upload replay

This development check sends one complete generated MP3 through the real browser
form, HTTP service, automatic discovery, trajectory index, national search,
physical refinement, confidence decision and result display. It addresses the
upload verification work in [#13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13).
The workflow checks out the complete repository history before installing and
testing the exact source revision.

The generator is the published independent emission-domain fixture from commit
`1f0342594bdc7fc7089a075b6dbf26aca9342711`. For four events it produces a
960-second recording and 12 complete trajectories, with 271 samples each. The
test retains all 3,252 trajectory rows, including jet and unknown-type rows. It
randomizes trajectory identifiers and whole-trajectory order, checks every
non-identifier value, and preserves the original Parquet and mapping separately.

## Run

Use Git and Python 3.11 or newer. The recorded run used Python 3.12.15.
Create a separate clone in a destination that does not exist:

```bash
git clone --no-checkout https://github.com/1337isnot1337/DOPPLERGEIST.git DOPPLERGEIST-upload-e2bb3dce
```

If the clone command fails, stop. After the clone succeeds, select the exact
integration commit that contains the tested producer combination:

```bash
cd DOPPLERGEIST-upload-e2bb3dce
git checkout --detach e2bb3dce63591ff7c92a0f985b40dd6a01a24cec
```

Both `ffmpeg` and `ffprobe` must be available on `PATH`. The tested Ubuntu 24.04
workflow installs FFmpeg with these commands:

```bash
sudo apt-get update -qq
sudo apt-get install -y ffmpeg
ffmpeg -version
ffprobe -version
```

Install the project, test dependencies, and Playwright Chromium. Use a fresh
output path for every attempt:

```bash
python -m pip install -e '.[test]' playwright
python -m playwright install --with-deps chromium
python -m pytest -q
python scripts/ci_upload_replay.py \
  --output results/ci-upload \
  --browser-python "$(command -v python)" \
  --expect-status inconclusive \
  --events 4 \
  --seed 20261103 \
  --timeout-s 1800
```

The expected status is fixed before execution. The current producer explicitly
does not establish exhaustive alternative-mode assessment, so this revision
expects an inconclusive product response. That expectation can pass the browser
transport check, but cannot pass supported localization or the complete replay.
The wrapper exits with code 1 unless both transport and supported localization
pass. An unexpected successful status is retained for investigation, without
changing the expectation after observing the outcome.

The workflow `.github/workflows/multi-event-upload-replay.yml` runs this command
on its isolated integration branch. It uploads the output directory after either
success or failure. The source composition is recorded separately in
`evidence/verification/ci-multievent-upload-20261103/source-manifest.json`.

## Inputs and execution

The ordinary request contains the MP3, the generator's declared sample-zero UTC
and the CONUS search scope. It contains no event times, frequency bands, aircraft
identities, recorder location or receiver bounds derived from the reference.
The operator supplies the complete generated traffic index, the fixture's
constant terrain and zero-geoid rasters, a 343 m/s sound speed and a 20 km
maximum distance. These are synthetic development inputs. Live archive or
terrain acquisition is not exercised by this test.

The runner copies and hashes the source that the subprocesses actually import.
It also checks immutable Git blob identities for the published fixture,
browser verifier, product verifier, process helper and audited service lifecycle.
The PR33 verifier and browser driver run unchanged. A module-local lifecycle
adapter changes only the service's final termination signal from SIGTERM to
SIGINT. The audited service handles SIGINT and closes its job manager, which
joins the analysis-management threads. The receipt records the signal, process
exit and any forced kill. It never substitutes scientific stages or HTTP replies.

Evaluation labels are opened only after a terminal job result and a recorded,
graceful service exit with code 0. A timeout, forced kill or unproven shutdown
leaves labels unopened. A separate browser layout failure may still leave a
completed, stopped analysis available for post-run diagnostics; it cannot pass
the full transport check.

## Predeclared interpretation

The receipt distinguishes these requirements:

| Requirement | Evidence required |
| --- | --- |
| Browser and HTTP transport | Actual submitted upload, identical original-file download, stored-job reload, declared terminal status, JavaScript and layout checks |
| Input and source integrity | Request, operator, upload hash, implementation hashes, index version and full trajectory inventory agree |
| Search coverage | Reported tile counts, data coverage, run hash and all-event coverage agree with the returned result; an explicit event cap cannot count as complete |
| Leading result binding | The internal leading refinement row and returned leading candidate have identical location, clock, score and expanded event-to-flight mapping |
| Joint fit | Each selected independent group has finite recorded residual diagnostics, positive sample counts and support, matching the exported diagnostics |
| All four flyovers | All four true flights appear in valid independent groups; at least 90% of each group's unique ridge times fall in its mapped true arrival interval, with no competing true interval meeting that fraction |
| Recording clock | The returned sample-zero UTC lies within the exact supplied request window, without an added evaluation tolerance |
| Supported localization | The producer actually returns `succeeded`, all preceding checks hold, and the leading candidate is within the evaluated distance limit |

The arrival-interval check is evaluation only. Its edge allowance is half the
actual discovery STFT window, and each group must contain at least three unique
ridge times. Labels and their intervals never enter the product request.

The primary distance limit is **less than or equal to 1,000 m**. Outcomes at
100 and 500 m, and a strict-under-100 m diagnostic, are also reported. A close
lower-ranked candidate cannot replace the leading prediction. Multiple retained
candidates and multiple thresholds are not independent trials.

The receipt records frequency perturbation scenarios for every selected group,
altitude perturbations for every selected flight, and the producer's completion,
boundary and failure flags. These show reported participation under the pinned
joint refinement. They do not establish an empirical leave-one-out effect,
calibrated uncertainty, a probability of correctness or continuous-space
uniqueness. No additional uncertainty threshold is introduced by the wrapper.

## Preserved evidence and limits

`acceptance.json` retains the execution stages, runtime, sampled process-tree
memory, browser report, lifecycle, source identities, input inventory, stage
consistency checks, fit/profile participation and every candidate's post-run
error. `artifact-manifest.json` hashes the retained files. The complete receipt
is also printed between fixed markers in the workflow log. Failures remain
failures; missing evidence is not filled with expected values.

This is one finite synthetic development scene with a known generated clock.
Its recorder location is not an independent location holdout from the earlier
synthetic development work. Reference separation is procedural; this runner
does not claim an operating-system boundary that makes truth inaccessible to
the backend. Sampled RSS can miss short peaks. The browser audit does not turn
these conditions into independent real-audio or national-coverage validation.

Independent field recordings with established microphone coordinates and
sample-zero UTC, and a sealed holdout, remain the separate requirements in
[#53](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53). A future finite-grid
search certificate must state its resolution, retained modes, discarded-score
evidence and work limits. It must not be represented as proof of continuous
uniqueness or calibrated confidence.
