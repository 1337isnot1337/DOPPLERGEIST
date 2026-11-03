# Integration verification, 2026-11-03 UTC

The primary integration agent reviewed and combined the worker branches in an
isolated worktree, then ran the repository suite against the actual combined
source in a clean Python 3.14 environment. No system site packages were enabled.

| Combined increment | Tests | Runtime | Tested commit |
| --- | --- | --- | --- |
| Evaluation, discovery, repaired index, independent index regressions, partial association | 94 passed | 113.85 s | `5e40a563956a304c0acecfa5b39a322a0a93197e` |
| Fragment discovery, national tiled driver, full perturbation profiles | 104 passed | 57.49 s | `afec84d2526c1eeaf016b94e466bc4b510908e37` |
| Per-flight altitude profiles, codec/replay verifiers, benchmark-clock regressions | 121 passed | 62.24 s | `1d74fcd880ce5a9873b5661428575e2954064b76` |
| All-event matcher, canonical renderer, refinement-grid union, confidence/evaluation and preserved real/synthetic evidence | 175 passed | 66.39 s | `e3d1952b497e16d3d5066e6bbbe5ff05c8e0310f` |

The command was `PYTHONPATH=src <clean-venv>/bin/python -m pytest -q
--junitxml=<receipt>`. The final run also set `OPENBLAS_NUM_THREADS=1` and
`OMP_NUM_THREADS=1`. Each run emitted one pandas future-dtype warning from the
index aircraft-class fallback; there were no failures or skips. Machine-readable
[receipts and JUnit reports](../../evidence/verification/integration-20261103/receipt.json)
record the exact source objects and environment. The [175-test receipt](../../evidence/verification/integration-20261103/all-events-receipt.json)
and JUnit XML preserve the latest frozen combination. The published W4 follow-up
changes fixture altitude metadata/documentation; production source and tests are
identical to that tested combination. Test counts cover integration
behavior; they do not establish real-world location accuracy.

The user's updated acceptance target is at most 1,000 m error, with 100–500 m or
better preferred. Future evaluations report 100/500/1,000 m thresholds and must
exercise three, four and more independent flyovers without a fixed event cap.
Older runs retain their original settings and thresholds; changing the target
does not repair missing reference coordinates, clock evidence or flight coverage.

Current real-data evidence is deliberately narrower:

- The [clean configured replay](CLEAN_REPLAY.md) preserves both the regional
  two-event success and the faint-event result outside the 100 m target.
- The [metadata audit](REAL_DATA_TIMING.md) does not establish independent
  recorder coordinates or sample-zero UTC for the separate 40-passage dataset.
- The [automatic synthetic execution and context diagnostic](../../evidence/verification/physical-20261103/)
  retains the inconclusive result and its competing associations. The extra
  spectral-context experiment is development evidence, not a calibrated decision
  rule or a replacement for the frozen run.
- [Corrected Times Square and Liberty recordings](PUBLIC_CAMERA_BENCHMARK.md)
  each decode to 300 seconds and yield no proposals under unchanged discovery.
  Neither establishes microphone sample-zero UTC or surveyed coordinates, so
  neither is eligible for location-error acceptance at any threshold.
- [Canonical independent 3/4/6-flyover fixtures](../MULTI_EVENT_FIXTURES.md)
  produced 13/13 detected events with frozen settings. Their code, complete
  discovery evidence and checksummed media are published. Flight association,
  multi-event location acceptance and the finite-search alternative assessment
  still require the subsequent actual product replays.

The source YouTube MP4 is excluded. Earlier experiments and failed outcomes have
not been overwritten. See [the coordination board](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39)
for active integration dependencies and worker replies.
