# Independent physical retention-accounting oracles

These controls are prepared for W2's agreed finite-search producer follow-up.
They are intentionally not ready to merge before that producer exists. No
production code is changed here. The current producer retains its conservative
old exhaustion flag, so these missing fields are not described as new accepted
localization failures.

The tests use actual indexed trajectories, CPA proposals and robust acoustic
scores on small declared regional grids. They compare a high-retention run with
a top-three run over the same inputs. They do not replace the scorer or use a
fabricated completion object. The regional fixture is an accounting control,
not independent real or national accuracy evidence.

At frozen `5adc13e6138a0c926cc453ec475fa7d4dbddbd25`, all four new tests fail as
expected: three encounter the not-yet-produced `finite_search_evidence`; the
fourth shows that the old rounded identity key merges four distinct seeds into
one. Native failure logs and JUnit are retained. The final tests are published on
main base `605af6e`, after its all-event driver integration, without altering the
earlier receipt.

The coarse oracle retains all 9 scored modes with a large budget. A top-three
run omits 6; its required discarded-score bound is at least
`0.9999999999999978`. The fine-grid oracle retains all 43 scored modes. Its
top-three counterpart omits 40, with maximum omitted score
`1.5158507056568205`. Both fine runs select the same single coarse seed, so they
evaluate the same refinement region. Exact source reports and hashes are saved.

The controls require that mode IDs survive tile repartitioning and checkpoint
resume; per-mode scores/groups agree; event caps and unfinished tile work cannot
claim finite completion; and distinct exact position/clock/pass seeds are not
silently treated as exact duplicates. The high-retention physical oracle checks
the score bound without assuming a particular ledger implementation.

Run from the producer worktree with its source and tests on `PYTHONPATH`:

```bash
PYTHONPATH="$PWD/src:$PWD/tests" python -m pytest -q \
  /path/to/tests/test_finite_retention_oracle.py
```

The test module reuses only the existing deterministic trajectory fixture in
`test_tiled_search.py`. W2 owns the disk-backed ledger and producer changes;
this verifier will run these controls on the exact published handoff. Ledger
corruption and unsupported-core controls will be added only once its actual
persisted schema is available. No pending check is counted as passed.
