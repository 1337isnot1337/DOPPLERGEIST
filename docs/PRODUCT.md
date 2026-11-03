# Local upload workflow

The current location goal accepts up to **1,000 m error**, with **100–500 m or better preferred**. True benchmark error and uncalibrated model sensitivity remain separate. Historical reports below retain their original 100 m thresholds.

The automatic product path is separate from the historical research `run` and
`measure` commands. Uploads supply audio, an optional defensible UTC window for
**sample zero**, and declared CONUS search coverage. Event windows, frequency
bands, flight IDs and ground-truth coordinates are not upload inputs.

Launch the local interface after installing the project:

```bash
dopplergeist serve --jobs jobs --config operator.json --port 8765
```

Open `http://127.0.0.1:8765`. The same persistent directory must be supplied after
restarting. Each upload gets a new job ID and its own original file, normalized
request, provenance, intermediate diagnostics, result and worker log. Completed
jobs are read back without rerunning. Interrupted jobs are explicitly failed;
they are never silently replayed. Cancelling preserves partial artifacts.

The server binds to loopback. It runs one analysis process at a time, accepts up
to four pending jobs, limits uploads to 100 MiB by default, and limits analysis
to one hour by default. Set `--max-upload-mb` and `--max-runtime` to change these
operator limits. Cancellation terminates the analysis process group, including
decoders. No API credentials or paid service are required by the local service.
Flight/terrain provider configuration and scientific integration are described
below; an unconfigured backend must report
missing data rather than invent a location.

CLI equivalents:

```bash
dopplergeist analyze recording.mp3 --jobs jobs --config operator.json \
  --start-utc 2026-09-08T20:00:00Z --end-utc 2026-09-08T20:05:00Z \
  --time-source 'Recorder clock and recording log'
dopplergeist job JOB_ID --jobs jobs
dopplergeist resume JOB_ID --jobs jobs --max-runtime 3600
```

`resume` applies only to a job stopped by its wall-time limit after search
checkpoints were written. It creates a new job, retaining the old result and
copying its original recording, request, operator configuration and search
checkpoints. Intake and discovery run again; the search checks the recorded
inputs, settings, implementation and individual tile records before reuse. A
changed implementation or input fails the checkpoint check rather than mixing
results. A fixed `max_tiles` limit is not extended by resuming. Resume is
currently available from the CLI, not the upload interface.

The UTC window bounds the recording start, not the event occurrence or upload.
Missing time is a required-input result. Scores are ranking statistics, not
probabilities. Sensitivity radii must not be described as calibrated confidence.
An inconclusive result may retain candidate hypotheses for inspection.

## HTTP surface

- `GET /api/capabilities`: declared coverage and upload/work limits.
- `POST /api/jobs`: raw audio bytes with `Content-Type: application/octet-stream`,
  `Content-Length`, optional `X-Filename`, and `X-Dopplergeist-Request` containing
  the shared request JSON **without** `audio_path`. The server saves the upload
  and sets that path. Returns HTTP 202 and a shared queued `JobResult`.
- `GET /api/jobs/{id}`: the current shared `JobResult`.
- `POST /api/jobs/{id}/cancel`: cancel a queued/running job; terminal jobs remain.
- `GET /api/jobs/{id}/artifacts`: relative file paths and byte counts.
- `GET /api/jobs/{id}/artifacts/{path}`: download one artifact. Private operator
  configuration is excluded. Paths cannot escape the job directory.

Upload example (header metadata uses actual JSON, not a string-encoded file):

```bash
curl -H 'Content-Type: application/octet-stream' \
  -H 'X-Dopplergeist-Request: {"schema_version":1,"search":{"coverage":"conus"}}' \
  --data-binary @recording.mp3 http://127.0.0.1:8765/api/jobs
```

`tests/test_service.py` checks HTTP transport, original preservation, state
readback, cancellation, interrupted jobs, path restrictions and input validation.
These transport tests do not establish scientific localization accuracy.

## Provider and search configuration

An operator configures data once; users upload audio without choosing trajectory
files. The normal acquisition path delegates to `data_access.acquire_inputs`:

```json
{
  "cache_root": "/absolute/path/to/dopplergeist-cache",
  "offline": false,
  "terrain": {},
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
No hidden account credentials or paid fallback are used. The default acquisition
budget is three UTC archive dates, including propagation guards and the full recording (`max_acquisition_days`); wider recording windows need
a narrower defensible input or an explicit operator budget change. Do not put
credentials in this configuration.

For existing offline data, supply `flight_indexes` (paths to Worker 2 FlightIndex
SQLite files). Terrain may use the cached provider options (`geoid_path`,
`adopt_existing`) or a declared local override: `{"rasters":["/dem.tif"],
"geoid_raster":"/geoid.tif"}`. A `{"constant_m":0}` terrain override exists for
synthetic/flat-ground experiments and is labelled as a limitation in the result.
Local overrides require prebuilt indexes and retain their actual coverage.

`search_budget.max_tiles` bounds tile work. Reaching a tile, memory, data or wall
time limit leaves incomplete coverage and cannot produce a supported national
location. Full search completion does not prove the archive captured every real
aircraft. Grid finalists undergo jointly constrained position/clock refinement;
`refine_finalists` (default 5) limits physical sensitivity refinement. Unassessed
retained approaches prevent an affirmative confidence decision.

For reproducible chunk-boundary checks, an operator may set
`"discovery": {"chunk_s": 120.0, "overlap_s": 60.0}` in this private configuration.
These are the only discovery overrides supported by the product adapter. The
existing detector validates the overlap and chunk constraints; spectral bands,
acceptance thresholds and other scientific settings keep their defaults. The
actual settings and analyzed chunks are saved in `discovery/discovery.json`, and
the operator configuration hash is retained in provenance. This configuration is
not an upload-request field. A chunk-size comparison must rerun detection and the
pipeline; it cannot reuse final candidates as if discovery had run again.

Search reports with `model_support_complete` also supply explicit `model_support`
work counters. Unsupported CPA trajectories, unclassified score candidates or
unknown clock trials keep product search coverage incomplete. Unreported trial
envelopes are counted explicitly; zero reported unknown trials cannot establish
completion when some trial accounting is absent. Missing/malformed
counters cannot become zero work. Source spatial/time availability remains a
separate `data_status`; an available archive can still have unassessed trajectory
models. Coverage limitations expose the work counts, and per-stage support
artifacts retain affected IDs/reasons and conservative lost-coverage envelopes.
These counts describe work evaluations, not distinct aircraft.

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
inconclusive. Producer computation, consumer agreement and an actual integrated
run are required before this optional path is considered deployed.
