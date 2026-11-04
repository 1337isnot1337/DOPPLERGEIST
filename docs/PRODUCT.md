# Local upload workflow

The current location goal accepts up to **1,000 m error**, with **100–500 m or better preferred**. True benchmark error and uncalibrated model sensitivity remain separate. Historical reports below retain their original 100 m thresholds.

The [real-world data policy](../AGENTS.md#real-world-data-only) stops new synthetic
data generation, tests, benchmarks, and replays. New validation uses real
recordings and measured trajectories. Historical results retain their original
scope and limitations.

The automatic product path is separate from the historical research `run` and
`measure` commands. Uploads supply audio, an optional defensible UTC window for
**sample zero**, and declared CONUS search coverage. Event windows, frequency
bands, flight IDs and ground-truth coordinates are not upload inputs.

Launch the local interface after installing the project:

```bash
dopplergeist serve --jobs jobs --online --max-runtime 14400 --port 8765
```

Open `http://127.0.0.1:8765`. The same persistent directory must be supplied after
restarting. Each upload gets a new job ID and its own original file, normalized
request, provenance, intermediate diagnostics, result and worker log. Completed
jobs are read back without rerunning. Interrupted jobs are explicitly failed;
they are never silently replayed. Stopping preserves partial artifacts. After
whole-recording discovery finishes, the job writes an atomic `resume.json`.
Use **Resume job** to continue a stopped job with that checkpoint. Completed
audio discovery is reused, as are valid completed search tiles; a partially
processed stage or tile is repeated. Input, detector and checkpoint integrity
are checked before reuse; incompatible search checkpoints fail explicitly.
Stopping before discovery completes cannot resume from that stage.
Completed scored fine-grid pieces are also saved and reused when their scoring and
retention evidence match. Fine-stage checkpoint reuse currently requires the
same effective search worker count; use a new output directory if that count
must change after fine checkpoints have been written.

To back up or move a complete job, stop it, wait for its terminal status and
worker exit, then copy its entire job directory. If a service owns the store and
you cannot confirm the worker has exited, stop the service cleanly after its other
jobs finish before copying. Do not copy a live retention SQLite file with `cp`
or `rsync`: the database and its journal can change during the copy. SQLite's
online backup can produce a consistent database snapshot, but it does not also
freeze the job's independently changing JSON and tile files, so it is not by
itself a consistent full-job backup.

Saved searches from the November 3 `225bf6b` scorer have a compatible upgrade
path to the faster staged scorer. Resume retains their completed scores and
tile files, archives the previous search and identities, and processes only
unfinished work. Input, event, runtime and model checks still reject unsupported
transitions; the upgrade does not make an inconclusive result conclusive.

The server binds to loopback by default. For Docker bridge networking, use
`--host 0.0.0.0` and publish the same port on the host's loopback address; see
[Docker setup](DOCKER.md). The local Host/Origin checks remain enabled.
It runs one analysis process at a time, accepts up
to four pending jobs, limits uploads to 100 MiB by default, and limits analysis
to one hour by default. Set `--max-upload-mb` and `--max-runtime` to change these
operator limits. Cancellation terminates the analysis process group, including
decoders. No API credentials or paid service are required by the local service.
`--online` enables public flight and terrain downloads into `~/.cache/dopplergeist`
when a job has a defensible recording time. Archives and indexes can take tens of gigabytes or more and hours; no automatic
disk-space limit is currently enforced. The example gives each job four hours; adjust `--max-runtime`
for your system. Omit `--online` and supply `--config operator.json` to use
preconfigured offline data. An unconfigured backend reports missing data.

CLI equivalents:

```bash
dopplergeist analyze recording.mp3 --jobs jobs --online --max-runtime 14400 \
  --start-utc "$RECORDING_START_UTC_MIN" --end-utc "$RECORDING_START_UTC_MAX" \
  --time-source 'Your evidence for this recording time'
dopplergeist job JOB_ID --jobs jobs
dopplergeist job JOB_ID --jobs jobs --watch --interval 10
dopplergeist cancel JOB_ID
dopplergeist cancel JOB_ID --jobs jobs
dopplergeist resume JOB_ID --jobs jobs
# If the upload service still owns the job store:
dopplergeist resume JOB_ID --server-url http://127.0.0.1:8765
dopplergeist job JOB_ID --jobs jobs --watch
```

`analyze` prints the job ID and a monitor command to standard error as soon as
the upload is queued. `job --watch` reports the status-file progress field, the
count/rate of matching coarse and fine search filenames, the newest matching
file modification age, and the job status-file age on standard error. These are
unverified filesystem indicators: the watcher does not validate payload hashes
or retention evidence, and the file-count rate is not a completed-work rate or
ETA. Remotely staged work appears after it is imported. Pressing Ctrl-C stops
the watcher without cancelling the analysis.

Direct `analyze` accepts up to 100 MiB by default. Set `--max-upload-mb 250`,
for example, to allow a larger local recording. The `serve` command has its own
`--max-upload-mb` setting for uploads through the local web interface.

`cancel` sends the cancellation request to the local service at
`http://127.0.0.1:8765`. If `serve` uses a different port, pass its base URL with
`--server-url`. The service must be running and managing the job directory.
For a job started by direct `analyze` or `resume --jobs`, use
`cancel JOB_ID --jobs PATH`. It writes the cooperative cancellation marker
without opening a second manager; the active worker stops at its next
cancellation check, so it may finish its current tile first. This path requires
an active manager to own the job directory. The service API path instead stops
the worker process group promptly and returns the terminal job result.
When `serve` owns the job-store lock, use the same `--server-url` option with
`resume`; it prints the queued result after the service accepts the request.
Monitor it with `job --watch` and the service's `--jobs` directory. Without
`--server-url`, `resume --jobs` runs directly against a job store and requires
that no service currently owns its lock.

The UTC window bounds the recording start, not the event occurrence or upload.
Missing time is a required-input result. Scores are ranking statistics, not
probabilities. Sensitivity radii must not be described as calibrated confidence.
An inconclusive result may retain candidate hypotheses for inspection.

## HTTP surface

- `GET /api/capabilities`: declared coverage, upload/work limits, and whether a flight provider and online acquisition are configured.
- `POST /api/jobs`: raw audio bytes with `Content-Type: application/octet-stream`,
  `Content-Length`, optional `X-Filename`, and `X-Dopplergeist-Request` containing
  the shared request JSON **without** `audio_path`. The server saves the upload
  and sets that path. Returns HTTP 202 and a shared queued `JobResult`.
- `GET /api/jobs/{id}`: the current shared `JobResult`.
- `POST /api/jobs/{id}/cancel`: cancel a queued/running job; terminal jobs remain.
- `POST /api/jobs/{id}/resume`: explicitly continue a stopped job with a valid completed audio checkpoint.
- `GET /api/jobs/{id}/artifacts`: relative file paths and byte counts.
- `GET /api/jobs/{id}/artifacts/{path}`: download one artifact. Private operator
  configuration is excluded. Paths cannot escape the job directory.

Upload example (header metadata uses actual JSON, not a string-encoded file):

```bash
curl -H 'Content-Type: application/octet-stream' \
  -H 'X-Dopplergeist-Request: {"schema_version":1,"search":{"coverage":"conus"}}' \
  --data-binary @recording.mp3 http://127.0.0.1:8765/api/jobs
```

The historical checks in `tests/test_service.py` cover HTTP transport, original
preservation, state readback, cancellation, interrupted jobs, path restrictions,
and input validation. They do not establish scientific localization accuracy.
Automatic CI checks installation, source compilation, CLI help, and packaged
assets without generated data.

### Verify the complete HTTP pipeline

`scripts/verify_upload_http.py` submits a real recording to a local service and
checks the saved inputs, stage outputs, terminal decision and persisted result.
Use `--require-full-pipeline` to require acquisition, search, refinement and
decision evidence as well as intake/discovery, with at least one returned
candidate. A correctly handled missing clock or empty search cannot pass this
stronger operational check.

```bash
python scripts/verify_upload_http.py \
  --audio path/to/real-recording.mp3 \
  --operator-config operator.json \
  --start-utc "$RECORDING_START_UTC_MIN" \
  --end-utc "$RECORDING_START_UTC_MAX" \
  --time-source 'Evidence establishing the recording-start interval' \
  --expect-status inconclusive --require-full-pipeline \
  --output results/new-real-http-run
```

Declare the expected outcome before running. An expected `inconclusive` result
can verify that every stage ran; it does not establish a supported location.
It can pass with incomplete search coverage; the result retains those limitations.
Use `--expect-status succeeded` when testing that acceptance requirement, then
evaluate location error against an independent reference after the run. The
verifier reports operational verification and `supported_decision` separately.
It counts independent harmonic groups separately from their ridge records.

## Provider and search configuration

`--online` requires no JSON configuration: it uses the per-user cache and public
providers automatically. For a different cache location, existing indexes, or
custom budgets, provide an operator config with `--config`; `--online` enables
network acquisition while retaining the configured cache path. Users upload
audio without choosing trajectory files. The acquisition path delegates to
`data_access.acquire_inputs`:

```json
{
  "cache_root": "/absolute/path/to/dopplergeist-cache",
  "offline": false,
  "terrain": {},
  "search_workers": 12,
  "search_budget": {
    "spacing_m": 2000,
    "tile_cells": 32,
    "top_k": 100,
    "refine_spacing_m": 100
  }
}
```

This acquires public ADSB.lol all-type daily archives and Copernicus terrain/geoid
inputs, then reuses their indexed cache. It can require substantial disk space and
time. `offline` defaults to true; online retrieval is an explicit operator choice.
`search_workers` is an optional positive integer for coarse-search processes;
omit it to use one fewer than the available logical CPUs. More workers increase
memory use. Custom terrain providers currently search serially.
No hidden account credentials or paid fallback are used. The default acquisition
budget is three UTC archive dates, including propagation guards and the full recording (`max_acquisition_days`); wider recording windows need
a narrower defensible input or an explicit operator budget change. Do not put
credentials in this configuration.

For existing offline data, supply `flight_indexes` (paths to Worker 2 FlightIndex
SQLite files). Terrain may use the cached provider options (`geoid_path`,
`adopt_existing`) or a declared local override: `{"rasters":["/dem.tif"],
"geoid_raster":"/geoid.tif"}`. The historical `{"constant_m":0}` terrain override
does not establish real terrain or altitude-datum accuracy. Its result retains
that limitation for real recordings.
Local overrides require prebuilt indexes and retain their actual coverage.

`search_budget.max_tiles` bounds tile work. Reaching a tile, memory, data or wall
time limit leaves incomplete coverage and cannot produce a supported national
location. Full search completion does not prove the archive captured every real
aircraft. Grid finalists undergo jointly constrained position/clock refinement;
`refine_finalists` (default 5) limits physical sensitivity refinement. Unassessed
retained approaches prevent an affirmative confidence decision.

For chunk-boundary checks on real recordings, an operator can set
`"discovery": {"chunk_s": 120.0, "overlap_s": 60.0}` in this private configuration.
These are the only discovery overrides supported by the product adapter. The
existing detector validates the overlap and chunk constraints; spectral bands,
acceptance thresholds and other scientific settings keep their defaults. The
actual settings and analyzed chunks are saved in `discovery/discovery.json`, and
the operator configuration hash is retained in provenance. This configuration is
not an upload-request field. A chunk-size comparison must rerun detection and the
pipeline; it cannot reuse final candidates as if discovery had run again.

An operator can add `"spectral_comparison": {}` to save a separate
`spectral-comparison.json` artifact after refinement. This optional stage reads
the actual decoded recording and named native flight segments. It compares
constant source frequencies with one shared clock, using the reference band of
each prepared flyover group. The existing ridge decision and its uncertainty
remain unchanged. Spectral scores only compare supplied modes with identical
event sets; mixed sets have separate `rankings_by_event_set` lists and an empty
top-level `ranked` list. Each event-set ranking also contains `sample_sum_ranked`,
a separate ranking summing contrast over the sampled time bins and optimizing the
same shared clock. Unlike the event-mean statistic, it weights longer spectral
windows more heavily. It depends on the window, hop and contrast normalization;
the source video does not specify its exact brightness scaling. The comparator
chooses a clock that maximizes the combined score; the video describes choosing
the first event's alignment before locking later events to it. Neither ranking
establishes a national optimum or location acceptance, and ridge retention
bounds do not apply to these scores.

The spectral configuration accepts work limits and grid settings, including
`max_modes`, `max_spectrogram_bins`, `max_event_clock_trials`,
`max_curve_samples`, `time_sweep_s`, `time_step_s`, and `frequency_step_hz`.
Track loading uses `search_budget.max_tracks_per_tile` and
`search_budget.max_track_samples_per_tile` as total limits for this comparison.
Missing trajectories, ambiguous segment IDs and exhausted budgets remain
explicit in the artifact. These controls are private operator settings.

Search reports distinguish raw model support from finite assessment. If any
trajectory or scoring envelope lacks support, `model_support_complete` stays false.
`model_support` retains the raw work counts, unknown trials, and reasons. Missing
or malformed counters cannot become zero work. These counts describe work
evaluations, not distinct aircraft.
Unreported trial envelopes are explicit: zero reported unknown trials cannot
establish completion when any trial accounting is absent, including the legacy
fully supported path.

If every unknown finite scoring envelope has a validated ceiling or rejection,
`model_assessment_complete` can be true. An unavailable event fit contributes at
most one unit to the normalized support score. A fully validated event that
exceeds its residual limit rejects that association at that clock. The producer
retains the greatest ceiling across all scheduled clock trials in the retention
ledger. This accounting does not create a measured fit or restore missing support.

The product requires agreement between raw counters, persisted bounds, completion
flags, and finite discard accounting. The confidence decision compares the combined
discard bound with the leading score under the existing margin. Unsupported CPA
trajectories, unreported trials, and unbounded alternatives keep assessment
incomplete. Missing tiles, data gaps, event caps, and incomplete sensitivity
evidence still prevent a supported location.

Source availability remains a separate `data_status`. An available archive can
still have unassessed trajectory models. Per-stage artifacts retain affected IDs,
reasons, and conservative coverage envelopes. See
[model-support coverage](MODEL_SUPPORT_COVERAGE.md) for the complete contract.

The automatic path always uses one shared clock inside the supplied start window
and robust ridge loss. Its default association path considers every proposed
independent group; harmonics count once and unsupported acoustic proposals remain
explicitly unmatched. A smaller operator event cap is incomplete work and is shown
in coverage limitations, rather than silently keeping an initial subset. Every discovered event remains in the diagnostics. A
location requires the confidence producer's evidence checks, including independent
events, alternative hypotheses, complete coverage, residuals and measurement/model
sensitivity. A small altitude-only profile is insufficient. The final decision
and full candidate/refinement diagnostics are saved as downloadable JSON.

## Current limits

The application is available on `main` and remains experimental. Automatic
synthetic runs have produced accurate hypotheses and inconclusive decisions;
those are different outcomes. See the [README](../README.md#experimental-results)
for the reported results.

Independent real recordings with established recording time and location,
reliable global hypothesis discrimination, and calibrated false-localization
rates remain open. The acceptance goal is within 1,000 m, preferably 100–500 m;
landing the application does not establish that goal.

## Accounted finite-search evidence

The current integration consumes the optional artifact-only producer/decision
contract in [FINITE_SEARCH_DECISION.md](FINITE_SEARCH_DECISION.md). The search
producer assigns stable seed `mode_id` values including position, clock, event
indices and flight/pass association, and records every lossy retention bound.
The product relays `finite_search_evidence` unchanged, preserves seed IDs through
refinement, and supplies `candidate_mode_ids` parallel to the wire candidates.

For the explicitly declared evaluated-finite-grid scope, `assessed_mode_ids`
requires the producer's explicit `core_assessed_mode_ids` mapping plus an actually
completed finite core score with full measured-trajectory support at the original
seed/model and a valid trusted clock. A returned fit alone does not establish
classification of every bounded clock/optimizer trial; missing/malformed mappings
or producer-omitted IDs remain unassessed. It does not require
jointly optimizing every retained point. Failed, missing or unsupported core
records are unassessed. Raw and refined representations retain their original
mode ID and original-or-improved score; no association-only deduplication is used.
The accepted leading estimate still needs successful full sensitivity, datum,
optimizer, clock, actual-radius and competing-mode checks.

Unperformed refinements and continuous locations are outside that conditional
finite claim. Their limitations are displayed in coverage and saved in the
artifacts. The old `alternatives_evaluated` flag keeps its older meaning and is
not flipped to force success. An absent finite object preserves old outcomes;
missing mappings, incomplete work or an unaccounted near-tied discard remain
inconclusive. Validated bounds account for unknown discarded trials without adding
them to `assessed_mode_ids`. The adapter and decision code consume this finite
contract. An accepted real-recording location through this path remains unverified.
