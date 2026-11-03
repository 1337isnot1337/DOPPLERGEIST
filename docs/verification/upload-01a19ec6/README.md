# Independent upload verification checkpoint

This checkpoint does **not** establish automatic 100 m real-audio localization.
The cloned research pipeline and actual browser upload/error handling have been
exercised. Full automatic indexed search and uncertainty evidence remain under
integration. Every inconclusive/failed result remains visible.

## Research replay

A new clone at `68f700e932a904348900116d1e02cf7dc80de120` was installed into
a fresh Python 3.14.8 virtual environment without system-site packages.
`python -m pytest -q` passed all 11 baseline tests, and `pip check` passed.
The source, derived ADS-B and terrain bundles were SHA256 checked before
extraction; see `restoration.json` and `environment.json`.

The independent synthetic renderer regenerated the input samples. Its truth
file was moved outside the search input directory before the successful runs.
The historical research CLI was then run for all four cases, with new output
directories. Post-search geodesic evaluation is in `legacy-evaluation.json`.

| Case | Error | Recorded runtime | Qualification |
| --- | ---: | ---: | --- |
| Two synthetic events | 15.3956 m | 138.33 s | Correct flights; manually selected event settings |
| Known-time synthetic minute | 40.8744 m | 12.09 s | Correct flight; manually selected event |
| Real regional two-event case | 43.8585 m | 108.00 s | Exact archived winner; source-informed regional bounds/settings |
| Faint real regional event | 357.4687 m | 294.53 s | Correct archived winner; fails the 100 m target |

The regenerated two-event result differs from the archived 21.8855 m result.
Decoded samples and track bytes match the earlier data; archived/current ridge
outputs differ. The historical report lacks an implementation digest. This is
reported as a changed baseline, not an algorithm improvement. A regenerated
FLOAT WAV can also have a different file hash while decoded samples match.

The real reference is a rounded public-platform map coordinate, not surveyed
microphone truth. Its recording clock was inferred from the match. Neither
real result supplies independent national or automatic localization evidence.

## Actual browser and HTTP checks

The integration checkout combined committed intake, discovery, physical matching,
product and acquisition producers. At commit
`69f252898f130823cd5a0d739e39458bbcf3ce60`, the real product service ran on
loopback port 18876 with a fresh persistent job root. No fake coordinates or
mocked scientific stages were used. Earlier integration passed 50 tests;
the new real MP3 product/transport checks passed 8 tests with one acquisition
check skipped because the tiled-search dependency was not yet published.

Playwright used a new headless Chromium instance through
`codex-isolated-desktop`. Its Wayland display and compositor differed from the
physical session, and host X11 was unset. Only browser-page screenshots were
captured. Three actual form submissions and artifact downloads demonstrated:

- Missing time: `needs_input / recording_time_required`.
- Timed stationary audio: `inconclusive / no_supported_events`.
- Corrupt encoded audio: `failed / invalid_media`.

All original download hashes matched the uploaded bytes; no page JavaScript
errors were recorded. Individual receipts and a screenshot are adjacent to
this document. An earlier upload to an incomplete backend correctly ended in
`failed / worker_exit`; it is retained in the local experiment, not counted as
an acceptance success. A first browser harness attempt encountered the site's
CSP; the corrected runner uses locator assertions without changing CSP.

## Reproduce upload checks

Install the project normally. Browser verification additionally needs the
optional `playwright` Python package and `/usr/bin/chromium`; these are verifier
dependencies, not product runtime dependencies.

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python scripts/make_upload_controls.py results/new-upload-controls
.venv/bin/python -m aircraft_geoloc.cli serve --jobs results/new-upload-jobs --port 18876
```

With that service running, in another terminal:

```bash
codex-isolated-desktop run .venv/bin/python scripts/verify_upload_browser.py \
  --url http://127.0.0.1:18876 \
  --audio results/new-upload-controls/stationary.mp3 \
  --request results/new-upload-controls/missing-time.json \
  --output results/new-browser-missing-time
```

Use `timed.json` with `stationary.mp3` for no-events, and with `invalid.mp3`
for decode failure. Each runner refuses an existing output directory. The
browser runner reports the displayed terminal state and verifies the original
download; exit zero means the UI/roundtrip check passed, not location accuracy.

`scripts/verify_upload.py` independently exercises the HTTP API, saves status
transitions, and downloads/hashes every listed artifact. Its optional `--truth`
file is first opened after the job completes and artifacts are downloaded.
`case_passed` additionally requires an actual `succeeded` result, detected
events, complete/available declared coverage and error <=100 m. Without that
evidence it exits nonzero, including for valid required-input/inconclusive
responses. Reference independence and coverage still require review; a passing
case cannot by itself establish a nationwide real holdout benchmark.

## Remaining acceptance work

- Run the actual uploaded MP3 through indexed flight search, physical refinement
  and the confidence producer as their committed dependencies arrive.
- Preserve all misses, alternatives, partial coverage and uncertainty failures.
- Supply independent real recording-start and microphone-coordinate evidence.
- Complete the declared national real-audio evaluation before claiming the full
  repository objective.
