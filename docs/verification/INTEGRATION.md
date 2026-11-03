# Integration verification, 2026-11-03 UTC

The primary integration agent reviewed and combined the worker branches in an
isolated worktree, then ran the repository suite against the actual combined
source in a clean Python 3.14 environment. No system site packages were enabled.

| Combined increment | Tests | Runtime | Tested commit |
| --- | --- | --- | --- |
| Evaluation, discovery, repaired index, independent index regressions, partial association | 94 passed | 113.85 s | `5e40a563956a304c0acecfa5b39a322a0a93197e` |
| Fragment discovery, national tiled driver, full perturbation profiles | 104 passed | 57.49 s | `afec84d2526c1eeaf016b94e466bc4b510908e37` |
| Per-flight altitude profiles, codec/replay verifiers, benchmark-clock regressions | 121 passed | 62.24 s | `1d74fcd880ce5a9873b5661428575e2954064b76` |

The command was `PYTHONPATH=src <clean-venv>/bin/python -m pytest -q
--junitxml=<receipt>`. The final run also set `OPENBLAS_NUM_THREADS=1` and
`OMP_NUM_THREADS=1`. Each run emitted one pandas future-dtype warning from the
index aircraft-class fallback; there were no failures or skips. Machine-readable
[receipts and JUnit reports](../../evidence/verification/integration-20261103/receipt.json)
record the exact source objects and environment. Test counts cover integration
behavior; they do not establish real-world location accuracy.

Current real-data evidence is deliberately narrower:

- The [clean configured replay](CLEAN_REPLAY.md) preserves both the regional
  two-event success and the faint-event result outside the 100 m target.
- The [metadata audit](REAL_DATA_TIMING.md) does not establish independent
  recorder coordinates or sample-zero UTC for the separate 40-passage dataset.
- The [automatic synthetic execution and context diagnostic](../../evidence/verification/physical-20261103/)
  retains the inconclusive result and its competing associations. The extra
  spectral-context experiment is development evidence, not a calibrated decision
  rule or a replacement for the frozen run.
- Public webcam recordings are being collected for fresh tests. Capture time,
  microphone sample-zero time and a provider's map marker are distinct evidence.
  Clips without established clock/location references can exercise discovery and
  the upload workflow but cannot certify a 100 m location error.

The source YouTube MP4 is excluded. Earlier experiments and failed outcomes have
not been overwritten. See [the coordination board](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39)
for active integration dependencies and worker replies.
