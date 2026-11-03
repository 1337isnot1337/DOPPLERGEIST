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
