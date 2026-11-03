# Local upload workflow

The automatic product path is separate from the historical research `run` and
`measure` commands. Uploads supply audio, an optional defensible UTC window for
**sample zero**, and declared CONUS search coverage. Event windows, frequency
bands, flight IDs and ground-truth coordinates are not upload inputs.

Launch the local interface after installing the project:

```bash
aircraft-geoloc serve --jobs jobs --config operator.json --port 8765
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
below as their producing modules land; an unconfigured backend must report
missing data rather than invent a location.

CLI equivalents:

```bash
aircraft-geoloc analyze recording.mp3 --jobs jobs --config operator.json \
  --start-utc 2026-09-08T20:00:00Z --end-utc 2026-09-08T20:05:00Z \
  --time-source 'Recorder clock and recording log'
aircraft-geoloc job JOB_ID --jobs jobs
```

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
window budget is three days (`max_acquisition_days`); wider recording windows need
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

The automatic path always uses one shared clock inside the supplied start window
and robust ridge loss. Every discovered event remains in the diagnostics. A
location requires the confidence producer's evidence checks, including independent
events, alternative hypotheses, complete coverage, residuals and measurement/model
sensitivity. A small altitude-only profile is insufficient. The final decision
and full candidate/refinement diagnostics are saved as downloadable JSON.
