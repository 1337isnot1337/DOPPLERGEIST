# Independent MP3 and product verification

This lane supports DG-12 / issue #13. It complements the independent regional
replay lane and does not replace held-out real national localization evidence.

Run the codec measurement from an installed checkout with ffmpeg/libmp3lame:

```bash
.venv/bin/python -m pytest -q tests/test_methodology_verifier.py
.venv/bin/python scripts/verify_methodology.py codec --output results/mp3-timing-new
```

The output directory must be new. The runner generates a deterministic stereo
signal with three nonperiodic timing pilots, encodes five MP3 variants, and decodes
the WAV and MP3s independently to mono 4 kHz. It measures each pilot by normalized
cross-correlation. Silence, unrelated signals, truncated input and offsets beyond
the measurement range cannot pass. Original/MP3/code hashes, versions, exact
commands, stderr and decoded arrays remain in that directory. `report.json`
records all cases; the command fails if a required encoding fails.

The four gapless encodings must retain pilot timing and decoded duration within
2 ms. The fifth deliberately omits the Xing header and is a diagnostic: an MP3
without gapless metadata need not identify the original recorder's sample zero.
A failed diagnostic measurement still fails the command. A measured delay on this
test signal is not a universal correction that can be applied to other files.

## Local codec measurement, 2026-11-02

Platform: Linux x86-64, CPython 3.12.3, ffmpeg 6.1.1 with libmp3lame. The environment
was created with `uv venv --python 3.12 .venv` and installed with
`uv pip install --python .venv/bin/python -e . pytest`.

| Encoding | Maximum pilot offset | Duration difference | Outcome |
| --- | ---: | ---: | --- |
| Mono 8 kHz / CBR 16 kbps | 0.000966 ms | 0 ms | Pass |
| Mono 16 kHz / CBR 32 kbps | 0.000234 ms | 0 ms | Pass |
| Stereo 44.1 kHz / CBR 96 kbps | 0.000055 ms | 0.75 ms | Pass |
| Stereo 48 kHz / VBR q4 | 0.000014 ms | 0 ms | Pass |
| Mono 16 kHz / CBR 32 kbps, no Xing header | 69.051 ms | 93 ms | Diagnostic |

Subsample offsets are interpolation estimates, not claims of clock precision
beyond the 0.25 ms decoded sample period. Five verifier tests cover planted delays
and rejection controls. The original 11 baseline tests passed in this clean
environment. The checked-in codec receipt is
`evidence/verification/mp3-timing-20261102.json`; full local output is
`results/mp3-timing-20261102/`.

## Automatic workflow acceptance

The `product` command invokes the actual automatic CLI, starts the real local
service, uploads through HTTP, and drives the bundled form in Chromium. It never
intercepts a request or substitutes a scientific stage. It checks the shared
result contract, the expected status/reason, recording hashes, byte-for-byte
original download, browser JavaScript errors, and saved-job reload. It records
requests, responses, progress history, commands, code hashes, screenshots and a
Playwright trace. Each mode submits its own job.

Install the optional browser tooling separately from the scientific environment:

```bash
uv venv --python 3.12 .artifacts/browser-venv
uv pip install --python .artifacts/browser-venv/bin/python playwright
PLAYWRIGHT_BROWSERS_PATH=.artifacts/browser-cache \
  .artifacts/browser-venv/bin/python -m playwright install chromium
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.artifacts/browser-cache"
```

With the producer components installed, check an MP3 whose recording clock is
unknown:

```bash
.venv/bin/python scripts/verify_methodology.py product \
  --audio recording.mp3 --output results/upload-untimed-new \
  --browser-python .artifacts/browser-venv/bin/python \
  --expect-status needs_input --expect-reason recording_time_required
```

Supply `--start-utc`, `--end-utc`, `--time-source` and `--operator-config` for a
timed localization run. `--via cli`, `--via api` and `--via browser` can select
individual routes when repeating all three would be expensive. The default is
all three. The browser currently accepts whole-second UTC field values.
`--expect-status succeeded` additionally requires recording/event evidence and
complete declared coverage; it still does not measure location error. Ground
truth belongs in the separate evaluation runner, never in this request.

Three actual negative-path controls pass all three routes on the isolated
integration of main intake, W1 discovery `4a49646` and W5 product `bda6c91`:

| Real encoded input | Expected actual outcome |
| --- | --- |
| 45 s Gaussian-noise MP3, date tag, no recording clock | `needs_input / recording_time_required` |
| Same noise MP3, explicit 2026-09-08 20:00–20:05 UTC start window | `inconclusive / no_supported_events` |
| Deliberately invalid `.mp3` bytes | `failed / invalid_media` |

The noise source is deterministic: NumPy `default_rng(60721).normal(0, 0.05,
4000*45)`, SoundFile float WAV at 4 kHz, ffmpeg/libmp3lame at mono 16 kHz / 32 kbps.
The tagged variant adds `-metadata date=2026-09-08T20:00:00Z`; the ordinary variant
strips source metadata with `-map_metadata -1`. The invalid bytes are
`DOPPLERGEIST intentionally invalid media acceptance control` plus newline.
Original hashes and full result receipts are preserved with each run.
The reviewable summaries, full result receipts and actual desktop/mobile renders
are in `evidence/verification/upload-controls-20261102/`. All nine route/control
combinations passed on integration commit `e39bdc84`; a separate real browser
submission at `a5ebbb61` additionally passed the 390 px mobile overflow check.
Both integration commits are retained on the `verify/upload-acceptance` branch.

These controls exercise real intake/discovery and product persistence. Positive
search/association/decision acceptance depends on the remaining producer
integration. Manual event windows/bands, true flight IDs and truth-derived bounds
are not normal automatic inputs.

No automatic location or national validation is established by the codec or
negative-path results above. Final acceptance remains open until supported
localization passes the integrated upload path and the real benchmark outcomes,
time/location uncertainty and searched coverage are reported.

## Full real-recording MP3 upload

The restored one-hour reference WAV was encoded to mono 16 kHz / 32 kbps MP3
with libmp3lame, without supplying event windows, frequency bands, flight IDs,
receiver coordinates or a recording clock. At integration `b953d74d`, all three
routes produced the same nine acoustic proposals (identical event JSON hashes)
and `needs_input / recording_time_required`. The complete check took 41.24 s.
The browser displayed actual discovery plots and restored the saved job on reload;
its 390 px mobile page had no horizontal overflow or JavaScript errors.

These are acoustic proposals, not nine verified aircraft. The frozen WAV detector
had eight proposals; the MP3 adds a short proposal near 495 s and changes some
fragment boundaries. Proposals cover the source's two prominent passes but remain
fragmented; the known faint 1250–1310 s event remains missed. These observations
are post-run comparisons and never enter the automatic request.

Independent post-run comparison of the actual intake samples with ffmpeg-decoded
WAV snippets at 120, 2156 and 3076 s has correlations 0.9982–0.9991. Interpolated
offsets are at most 0.00168 ms; decoded sample resolution is 0.25 ms. The 3600.18425 s
MP3 intake differs from the decoded WAV reference by one 4 kHz sample. This tests
relative codec timing and does not establish recorder UTC.

The input/code-hashed result, timing comparison, mobile render and test log are in
`evidence/verification/reference-hour-upload-20261102/`. Full local artifacts are
`/home/cinna/DOPPLERGEIST-upload-acceptance/results/reference-hour-upload-v1/`.
The combined producer snapshot passed 98 tests with one skipped automatic-search
test: its national-search module was not part of this snapshot. There was one
pandas future-dtype warning. Historical and failed harness-development outputs
remain preserved separately. Positive localization acceptance remains open.
