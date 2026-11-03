# Independent scoring-assessment controls

`tests/test_scoring_assessment_independent.py` uses the real propagation model,
bounded robust source fit and association score. It does not mock scoring or
inject completion metadata. Four cases distinguish supported evaluations,
unsupported clock trials, and a supported acoustic-loss rejection.

The source tracks each span 300 seconds. Their central clock fits both observed
ridges with total support score `1.9999999999999967`. A sweep through -200, 0 and
+200 seconds retains that finite winner while the outer trials lack trajectory
support. A fixed +200-second clock has no supported trial. Separately, positive
alternating frequency offsets create an acoustic mismatch within supported
geometry, which the actual association loss rejects.

At the first published ledger source `5459461d1db4dc574ba5cb8be966a26ab96c68c7`,
all four physical preconditions are met. All four tests then fail because the
scorer has no `scoring_assessment` field. These are expected readiness failures,
with zero errors or skips; no localization claim follows. The native command,
test hash, log and JUnit are preserved here.

The controls require the agreed typed counters and completion status. They use
lower bounds on trial counts so a future explicit removal of duplicate zero
clock shifts does not change the required scientific behavior. A finite winner
must not hide unsupported trials, and an all-negative-infinity score must not by
itself establish whether the trials were admissibly rejected or unknown.

The existing physical retention oracle remains unchanged. This branch is a
test/evidence handoff, not a merge-ready pull request while the production
classification dependency is absent. Run these controls against the exact
published W1/W3 classification source with its `src` and `tests` on `PYTHONPATH`.
