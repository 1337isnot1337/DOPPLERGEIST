# Partial model support preserves valid tile evidence

Frozen source `c97242e`, consuming W1's classified-trial adapter `7897f5c` with
provenance. The full gate passed **241 tests + 6 subtests**, zero failures/skips,
79.98 s. Exact commands, native log/XML and artifact hashes are in
[receipt.json](receipt.json).

Six outer-driver controls cover mixed valid/unsupported legacy candidates,
unchanged clean scores, original source retention, resume counts, partial CPA
chunks, all-unsupported sources, generic error propagation, refinement-only loss,
and a positive actual classified robust-scorer/finite-ID integration. The CPA
failure controls here inject the agreed typed boundary. A real bad-Track CPA test
awaits W3's explicit continuous-motion validator at that production call site;
the old CPA implementation never calls acoustic propagation itself.

The bounded replay uses the **unchanged** historical v2 index, analytic ridge,
20 km grid and constant-ground scale fixture. Only the three original failed
tiles are revisited. An independent per-track enumeration oracle scores every
candidate, catches the typed source failures separately, and compares every
retained clean score/identity against the production tile scorer.

| Historical failed tile | Queried tracks | Points | Retained clean rows | Typed candidate failures |
| --- | --- | --- | --- | --- |
| 9_9 | 253 | 64 | 7 | 2 |
| 5_13 | 324 | 64 | 9 | 1 |
| 7_15 | 131 | 64 | 1 | 1 |

All 17 retained clean rows exactly match the oracle, with four unsupported
candidate envelopes retained as unknown work. Total replay elapsed 8.60 s.
Full assignments, reasons, receiver/pass state and unchanged source hashes are in
[historical-tile-replay/report.json](historical-tile-replay/report.json) and its
per-tile/support files. Interrupted legacy envelopes have unknown trial counts;
their explicit `unreported_trial_envelopes` count is four, rather than an invented
zero-unknown classification.

This is a fault-isolation regression, not a new national search or a localization
benchmark. It preserves the old 855/858 partial result. It does not repair the
legacy normalized source, establish continuous motion/convergence support,
certify source completeness, or close real-data correctness issue #64. No recorder
coordinates, audio truth or flight whitelist are supplied to a location search.
See [MODEL_SUPPORT_COVERAGE.md](../../docs/MODEL_SUPPORT_COVERAGE.md) for the exact
additive report and conservative lost-coverage semantics.
