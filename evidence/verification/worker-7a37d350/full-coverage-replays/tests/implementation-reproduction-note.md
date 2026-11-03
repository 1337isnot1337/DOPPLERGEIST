# Implementation and reproduction handoff

The actual local MP3 upload replay passed strict acceptance on the reviewed
`full-coverage` synthetic fixture. The service completed intake, event discovery,
input acquisition, finite search, refinement, and its evidence-based decision.
All 18 runner cross-checks and the seven-stage scientific gate passed.

The leading prediction was 0.07932759465 m from the synthetic reference, with all
four aircraft correctly associated and zero clock error. The clock was supplied
as an exact sample-zero time; the system did not infer it. The returned sensitivity
union radius was 117.195703249 m. This is an uncalibrated engineering envelope,
not a confidence probability. The 100/500/1000 m tiers refer to observed reference
error, and all passed.

## Source and implementation

Published source: `e33e2f38068c704a1d9e5a8a76c41d73b8020f92` on
`worker/end-to-end-7a37d350` / PR 86. It has the same tree as tested local commit
`b6413a6fcb4abc43816ab439931af6433296032e`:
`69169d71301576b15f859879df8f5bf7165c7613`.

The integration adds conservative classification of every scheduled clock trial,
verified finite-retention evidence, a strict HTTP replay harness, and an optional
fixture with complete sampled trajectory support. The default fixture remains
`local-segments`; successful reproduction requires the explicit variant below.
Historical inconclusive runs remain unchanged.

The new fixture preserves all original observations, aircraft, distractors,
uploaded MP3, and labels. WAV PCM and all non-timestamp container bytes also
match; libsndfile's PEAK creation timestamp varies between generations. Its
analytic support certificate is limited to nominal range-gated CPA receivers.
Refinement and profile support still pass the existing runtime checks.

## Reproduce

Use Python 3.12 and an installed `ffmpeg`/`ffprobe`. From the checked-out commit:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python scripts/ci_http_replay.py \
  --output results/http-full-coverage-reproduction \
  --events 4 --seed 20261103 \
  --fixture-variant full-coverage \
  --expect-status succeeded --timeout-s 1800
```

Choose a new output directory for each run. The documentation and hosted workflow
use these same event, seed, variant, expectation, and time-budget values. The
default expected status remains `succeeded`; an expected abstention never passes
the runner's localization acceptance.

## Verification record

The complete suite passed 550 tests and 25 subtests. One live process-tree RSS
check was skipped because `/proc` exposes a different PID namespace. Source
preflight and both independent terminal/fixture audits passed. The local replay
took 329.7745 s, searched 97,280 coarse and 1,681 fine points across 4,940 tiles,
and left zero unclassified candidates. Its ledger recorded 6,801 distinct modes,
100 retained and 6,701 discarded, with no competitive discarded mode.

The source is clean. The replay and verifier processes were reaped, the service
exited normally after SIGINT, its listener is closed, and its manager lock is
released. The audited manager lifecycle waits for the analysis child before
shutdown. No unreliable `/proc` process-list inference was used.

The run and its complete manifest are preserved at
`results/http-full-coverage-7a37d350/`. Acceptance SHA256:
`fa43bb2301386ec45059061afe9506488421226a1cbfaa59117fc0bb6ffc8d13`.
Artifact-manifest SHA256:
`65b25b76c609e208c0502324246904c13cf7cb9fc5bc29723261d4eed0f7f67a`.

This verifies the finite synthetic end-to-end pipeline. It does not establish
real-recording accuracy, live acquisition, national archive completeness, or
continuous-space uniqueness.
