# W4 finite-ledger integration boundary controls

Frozen runtime `c845c48bc0c2bcf0b17da7ac5d5abfa6b3bffc98` combines W5 product, W2 retention producer, W1 classified scorer and W4 `ef1c6ea` consumer. The production producer modules match W2 `2893f9c`; scoring/geometry match W1 `cc3286c`. No production file was edited for these checks.

The four new independent controls exercise the actual SQLite ledger, top-k merging, product adapter, strict wire conversion and decision consumer. They check the enlarged uncertainty is returned unchanged, and that a missing core assessment, near-tied discarded mode or corrupted ledger each remains inconclusive. The full suite passed **311 tests + 6 subtests**, zero skips/failures, in90.95s. Native logs/JUnit and source hashes are retained. An initial new-test assertion used an invented success reason; it was corrected to the existing reason before this frozen passing run. No production behavior was changed.

```sh
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q tests/test_finite_bridge_independent.py
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python evidence/verification/w4-finite-bridge-20261103/check_http_readback.py results/NEW-UNUSED-DIRECTORY
```

The separate HTTP control computes the existing near-finite-points fixture, starts the real loopback JobManager/JobServer, reads result and decision-artifact endpoints, verifies exact JSON equality, and closes the service. The70m base radius becomes159.99999999972488m with method `finite_mode_and_tested_profile_union`. Source/module/harness hashes are in `http-receipt.json`; no media, job cache or environment is committed. The prior live-peer readback has weaker source provenance; this source-frozen receipt supersedes it only as transport evidence.

These are implementation boundary controls. Full-profile inputs are synthetic; neither acoustic search, physical profile generation, browser rendering nor location accuracy is tested here. No historical scientific result is revised, and compatible nested-subset policy remains unchanged. The canonical national replay owners and independent real recording gate still need their own evidence.
