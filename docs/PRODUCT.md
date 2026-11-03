# Local upload workflow

The current location goal accepts up to **1,000 m error**, with **100–500 m or better preferred**. True benchmark error and uncalibrated model sensitivity remain separate. Historical reports below retain their original 100 m thresholds.

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

The automatic path always uses one shared clock inside the supplied start window
and robust ridge loss. Its default association path considers every proposed
independent group; harmonics count once and unsupported acoustic proposals remain
explicitly unmatched. A smaller operator event cap is incomplete work and is shown
in coverage limitations, rather than silently keeping an initial subset. Every discovered event remains in the diagnostics. A
location requires the confidence producer's evidence checks, including independent
events, alternative hypotheses, complete coverage, residuals and measurement/model
sensitivity. A small altitude-only profile is insufficient. The final decision
and full candidate/refinement diagnostics are saved as downloadable JSON.

## Verified integration and current limits

Worker 5 ran the full 1180-second independent-renderer synthetic recording as an
MP3, using all seven flight segments with opaque IDs, the generator's stated
recording start, and declared CONUS coverage. Neither truth JSON, selected flight
IDs, manual event bands/windows nor receiver bounds entered analysis. Truth was
opened only in a separate evaluation after the job terminated. This is a known
development fixture, not an independently held-out real recording.

| Run | Actual outcome |
| --- | --- |
| 10 km coarse integration | Two automatic events; all 819 tiles processed; five hypotheses; leading position error 1790.86 m; inconclusive because source coverage lacks the audible border halo. Search 17.53 s; full job 72.12 s; peak RSS 284.80 MiB. |
| Normal 2 km / 100 m refinement | Two events; all 4940 tiles processed; 106 hypotheses. **The leading hypothesis is wrong by 1,046,023 m.** The true pair appears fourth, 6.16 m away, at a nearly tied score. The result remains inconclusive. Search 317.54 s; full job 341.24 s; peak RSS 304.41 MiB. |
| Actual HTTP upload, closed synthetic world | The same full MP3 and all seven opaque tracks, with the simulation's complete world coverage explicitly declared, return `inconclusive / ambiguous_flight_match`. Upload/poll/readback and byte-identical original download pass. This tests real stage orchestration and abstention, not a real-world location success. |

The close fourth-place candidate is **not** a successful location result. All
returned candidate errors are retained in
[`evidence/product-20261102/automatic-conus/`](../evidence/product-20261102/automatic-conus/).
The frozen real API ambiguity result and diagnostic images are in
[`ambiguity-job/`](../evidence/product-20261102/ambiguity-job/README.md).
No source MP3, decoded cache, flight index or environment is committed there.
The normal-grid run pins every recorded Python module hash to `1863d89`; the earlier dirty
coarse snapshot has a verified base commit plus exact patch.

Real encoded MP3 HTTP tests cover missing time, corrupt media, stationary/no-event
input, and missing configured data. A real discovery process was cancelled through
the API in 0.08 s with metadata/original bytes preserved and its process reaped.
Completed-job restart and six artifact downloads matched their stored SHA256.
The built wheel includes the browser assets and scientific modules; its actual
full-MP3 CLI run returns the required-time result with the original hash preserved.
Independent browser checks cover nine CLI/API/browser control combinations, saved
job reload, no JavaScript errors, and desktop/mobile layouts; see
[verification PR #33](https://github.com/1337isnot1337/DOPPLERGEIST/pull/33).
Its later installed-wheel readback of the unchanged 106-hypothesis job verifies
five initial cards, expansion to all 106, a 390 px document before/after expansion,
14 byte-identical artifact downloads, six radius/method cards and zero JavaScript
errors. This checks the actual candidate layout and preserves the inconclusive
outcome; it does not exercise the newer finite-envelope decision.

A supported unique location through the actual automatic API, independently
established real recording truth/time, and nationwide real accuracy at the current 1,000 m acceptance target (100–500 m preferred)
remain unverified. The measured ambiguity and partial-coverage outcomes must not
be promoted to that acceptance claim. The historical manually configured regional
result remains separate.

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
