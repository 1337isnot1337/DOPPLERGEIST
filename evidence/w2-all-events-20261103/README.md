# All-supported-event driver follow-up

The user's updated target permits up to 1,000 m error, with 100-500 m or closer
preferred, and requests every supported independent flyover. Historical evidence
keeps its original decisions and thresholds.

Executed source `c22e68259774aa3db72ef4abe8f252f32a70ae55` combines W2 driver
`8750e91` and W3 bounded traversal `5657f60` (core `e827f17`). The complete source
suite passed **141 tests, zero failures/skips, in 78.04 s**. Native pytest XML,
console log, command, dependency versions and hashes are retained here.

Final release source `da140cb` also verifies the complete date-to-index provider
adapter, three aircraft families, offline reuse, truncation and wrong-day release
rejection. Its complete suite passes **142 tests, zero failures/skips, in 48.00 s**;
see `release-tests.xml` and the separate release check in `receipt.json`. The
preceding 141-test source check remains preserved rather than overwritten.

Meaningful driver checks use actual trajectories, CPA tables and physical scores:

- Three, four and six supported groups, each with a leading unmatched proposal;
  every supported index reaches the joint score and fine-grid refinement.
- Perturbing only the sixth ridge changes the joint score and final-event
  residual, demonstrating that later evidence is used.
- A deliberately smaller configured event cap produces an explicit partial
  result; the default robust path considers all groups.
- Exact known clocks, a biased first CPA with a broad trusted window, and a
  narrow trusted interval near the declared sweep edge preserve one common clock.
  The constrained interval is passed directly to scoring without re-expansion.
- A 1 m CONUS grid with a one-tile work limit counts its enormous queue
  arithmetically and completes the bounded work rather than enumerating the
  unsearched tiles.
- Prior boundary/untiled equivalence, deterministic merging, checkpoint mismatch,
  source gaps, missing derivatives and continuous-trajectory bounds remain tested.

The combined association tests also exercise W3's iterative bounded traversal,
40 sparse groups and an independent exhaustive small oracle. This proves API and
computation behavior on these fixtures, not an independent national real-audio
location result. The precision policy belongs to confidence/evaluation; raw scores
remain heuristic and incomplete coverage remains visible.

The earlier data, terrain, traffic-scale and actual Hermes-generated MP3 HTTP
receipts are preserved separately in
[the original evidence bundle](../w2-data-scale-20261102/README.md). In particular,
the near-truth candidate there remains inconclusive, and the three real-traffic
scale tile failures remain partial. Their motion-inconsistency audit is tracked
as [issue #64](https://github.com/1337isnot1337/DOPPLERGEIST/issues/64); no source
samples have been silently repaired, dropped or called actual supersonic flight.
