# Independent finite-evidence boundary review

At W4 prototype `4bdc1fd144ad37b416faa216e78ac88652c3922d`, the independently
specified equality controls fail for both retained and discarded competitors.
For scores 1.8 and 1.4 over two independent groups, the declared gap is 0.2.
Binary floating-point subtraction returns `0.20000000000000007`. The strict
comparison incorrectly treats the competitor as separated and permits success.

The focused repair uses the same conservative comparison for retained alternatives
and discarded-score bounds. `math.isclose` with relative and absolute tolerances
of `1e-12` keeps equality within roundoff competitive. It can only change a
numerically marginal acceptance to an inconclusive outcome. The policy margins,
returned-radius containment, score units and evidence requirements are unchanged.
A bound of 1.399999 remains distinguishable and passes the margin check.

Seven independent controls cover both equality cases, a separated positive
control, genuine refinement improvement without rewriting seed evidence, loss of
a better original seed, a distant same-association mode, and the conservative
group bound for a potentially larger discarded subset. These are decision
contract controls, not an end-to-end or physical-accuracy benchmark.

## Measured checks

| Frozen source | Checks | Outcome |
| --- | --- | --- |
| `4bdc1fd144ad37b416faa216e78ac88652c3922d` | Existing confidence tests plus exact final independent test file | 39 passed, 2 failed, zero skips, 0.125 s JUnit time |
| `fd7f63e5f4d7d133a721b57bab4de91c90911878` | Complete repository suite | 176 passed, zero failures/errors/skips, 20.829 s JUnit time |

The full suite reports one existing pandas future-dtype warning in
`data_access.py`. Native logs and JUnit are retained. `receipt.json` records the
source tree and SHA256 of the production/test files. The baseline check uses the
exact final independent test file against the untouched prototype worktree.

The commands used an absolute `PYTHONPATH` to the chosen worktree's `src` and
`/workspace/scratch/4cfe67e9d1bc/DOPPLERGEIST/.venv/bin/python -m pytest -q`.
The baseline selected `tests/test_confidence.py` plus the independent test file;
the fixed check ran the full suite. Full-suite execution allowed actual loopback
tests where present. No mocked result replaces a scientific stage in this claim.

This is a narrow stacked repair for W4's finite-evidence proposal, with no change
to another worker's branch. Producer retention accounting, stable mode mappings,
integrated execution and the independent field-data gate remain separate work.
Historical inconclusive runs, including the four-event CI replay, remain unchanged.
