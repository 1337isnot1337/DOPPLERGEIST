# Independent finite-envelope integration verification

The combined product and confidence source passes **284 tests and six subtests**.
There are no failures or errors. One process-memory control is skipped because
this environment lacks `/proc/thread-self/children`. Real loopback service tests
ran. These results establish software compatibility; no scientific analysis job
was submitted for this checkpoint.

## Frozen sources and outcomes

| Check | Exact executed source | Outcome | Native evidence |
| --- | --- | --- | --- |
| V5 initial collection | `26eec2334c76d37486d1358e67f0146538c65104` | Exit 2: duplicate module collection; no tests ran | `v5/` |
| V5 corrected collection | Same source | 268 passed, six subtests passed, one environmental skip; 46.816 s JUnit | `v5/corrected-collection/` |
| Published W4 consumer plus independent controls | `ef1c6ea2c9b36ea46365386e2a9ff57d248bd715` | 52 passed; the external product-dependent legacy module was skipped because this source has no `automatic.py` | `confidence-only/` |
| V6 combined source plus independent union controls | `392ff442f38b41a93060728bcf81915f7f916eb8` | 284 passed, six subtests passed, one environmental skip; 49.000 s JUnit, 49.704 s wall time | `v6/` |

The initial V5 command selected the repository tests and an external copy of
`test_decision_invariants.py`. The exact same file was already in the checkout.
The corrected command collects it once. Both native outcomes remain preserved.
The V6 run executes all four legacy decision controls and all four independent
finite-envelope controls. Their case names and results are recorded in
`source-and-scope.json`; none of these eight controls is skipped.

The executed V5 tree is published unchanged at
[03beb2c](https://github.com/1337isnot1337/DOPPLERGEIST/commit/03beb2c9f6b3a3bf01c848dd139cb133bcf19ef5).
The executed V6 tree is published unchanged at
[6b078f7](https://github.com/1337isnot1337/DOPPLERGEIST/commit/6b078f7336f4c1b9b8d5cacef6a12b315d260ca7).
Publication commits have different ancestry metadata from the locally executed
merges; the complete tree IDs match. V6 combines main `8cdb7ae`, product
`a6726f3`, and confidence `ef1c6ea`. No production file was edited by this audit.

## What the independent controls establish

The predeclared controls were published at `37f5c61` before the consumer was
available. A reported 300 m envelope around a near-tied point 600 m from the
unchanged result requires a 900 m union. The same envelope at 800 m requires
abstention at the 1,000 m target. Raw and refined states sharing a stable seed
identifier both contribute their actual positions. An unprofiled competitor
contributes its finite point without borrowing the leading profile.

Successful controls also require a copied output, unchanged input data, fixed
fitted position, clock, score, association and order, unchanged non-leading rows,
and no calibration claim. The numerical equality guards from #74 and the legacy
no-finite-object safeguards pass in the combined source.

`controls/test_finite_union_independent.py` is a byte-preserved copy of the
external control. The native receipts retain the exact commands, absolute
source paths, component commits and source hashes. To reproduce with the
published V6 tree, set `PYTHONPATH` to that checkout's `src` and `tests`, then run
its `tests` directory and this external control once. The independent fixture
module is included in that source's `tests` directory.

## Remaining acceptance gates

This checkpoint does not include W2's disk-backed distinct-retention ledger,
W3's classification of every bounded scoring trial, or W5's subsequently
announced `core_assessed_mode_ids` requirement. A supported winning fit alone
does not establish that all trials were assessed. Those interfaces still need
combined verification before a fresh qualifying replay.

No actual accepted finite-mode API/browser result, national real-recording
accuracy, calibrated coverage probability, or continuous-space uniqueness is
established here. The original four-event decision remains inconclusive. No
historical result was changed. The independent GPS/sample-zero UTC corpus in
#53 remains a separate unmet requirement for #13.

The memory skip is an environment limitation, not a passed memory test. The
confidence-only module skip is resolved by running those four controls in V6.
Native logs and JUnit are preserved byte for byte, including the initial
collection error and any diagnostic whitespace.
