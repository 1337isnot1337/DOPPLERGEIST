# Combined finite-producer integration and trial classification

Source `7897f5cb38f966576b2ee40517ea46b9648a7117` combines main `8cdb7ae`,
published W5 `f2aa5ec` (including W4 finite-union and W1 decoder changes), and
W2 finite-ledger `5459461`. The only merge conflict was independently appended
tiled tests: the grid-union control was byte-identical, retained once, and all
three new W2 controls were preserved. No shared contract was replaced.

The baseline integration at `4e11bd4` passed 300 tests plus six subtests in
131.41 s. The first six independent clock-classification controls reproduced five
failures and one existing passing generic-error control before the fix. All seven
final controls pass, including an actual typed `Track` failure. The scorer,
finite-ledger and tiled controls passed 29 tests before the final Track control
was added. The full fixed source passed 307 tests plus six subtests in 110.20 s.
Native logs/JUnit and source digests are preserved here.

Commands from the isolated worktree:

```bash
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --junitxml=results/w1-combined-finite-20261103/tests.xml
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_scoring_assessment.py
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_scoring_assessment.py tests/test_finite_search.py tests/test_tiled_search.py
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --junitxml=results/w1-classified-trials-20261103/tests.xml
```

The first command ran before the new control file existed. The second command
ran both before and after the classifier. A finite best cannot hide unknown
clock trials; completed acoustic rejection is classified separately. Generic
configuration/programming errors propagate. Existing fit values and clock
domains are unchanged. See [the interface note](../../docs/SCORING_ASSESSMENT.md)
for semantics (the repository-relative path is `docs/SCORING_ASSESSMENT.md`).

This is software integration evidence. No new full scientific replay, accepted
location, real-clock binding, continuous-speed guarantee or calibration is
claimed. Original failures and old jobs remain unchanged. W2 owns the outer
partial-coverage adapter; W3 is independently verifying support behavior.
