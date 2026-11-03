# Actual motion-support boundary integration

Frozen combined source `c69ac12` contains the unchanged W1 classified-trial adapter
and W3 continuous-motion, time-local support and emission-convergence guards, each
consumed with provenance. The full gate passed **252 tests + 6 subtests**, zero
failures/skips, 69.82 s. [receipt.json](receipt.json) preserves the exact commands,
native XML/log and hashes, including the expected before failure.

The new outer regression uses an actual indexed three-observation source with
zero measured knot velocities but a >700 m/s interior Hermite peak. It does not
inject a typed exception. Before the guard, search incorrectly reported complete
because the CPA speed filter hid the source. With the real validator connected,
all unchanged clean candidate scores/identities survive, source availability
remains separate, original malformed observations remain in the index, and
model/search/finite coverage stays partial. Reported native bad intervals are
retained without narrowing the conservative whole-track/stage loss envelope.

The same three historical traffic-fixture tiles were replayed in a new directory:

| Tile | Finite retained rows | Unsupported source/stage evaluations |
| --- | --- | --- |
| 9_9 | 6 | 5 |
| 5_13 | 9 | 7 |
| 7_15 | 1 | 11 |

All 16 retained rows exactly match the per-track guarded oracle. Every row from
the preceding 17-row replay whose track remains physically supported is preserved
with an identical score; the one removed row belongs to a now explicitly
unsupported source. The 23 counts are track/stage evaluations, not necessarily
distinct aircraft. Each source ID and every reported native emission interval is
preserved in the [replay reports](historical-tile-replay/report.json) and support
files. No interrupted candidate work is hidden: the validator catches these
sources before CPA pairing, so the model-support loss is explicit even though
reported unknown clock trials are zero.

These diagnostic grids use the unchanged historical legacy index, analytic ridge
and constant ground. They do not demonstrate national source completeness,
normalized raw-source repair, independent real localization accuracy or a new
supported end-to-end result. The old 855/858 run and initial 17-row replay remain
frozen alongside this separate physical-support checkpoint.
