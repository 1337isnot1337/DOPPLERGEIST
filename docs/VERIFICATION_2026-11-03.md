# Repository verification checkpoint — 2026-11-03 UTC

This is a source-and-receipt check, not a new localization experiment. The baseline
is [`8cdb7ae357137e7d7255b87b7ff88a4d281f6d7c`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/8cdb7ae357137e7d7255b87b7ff88a4d281f6d7c),
observed as `main` during this check. Later source revisions require their own
assessment. The [snapshot receipt](../evidence/verification/state-20261103/snapshot.json)
records the observation time, sources and artifact hashes.

## Implemented code and remaining integration

| Scope | Evidence at this checkpoint | Limit |
| --- | --- | --- |
| Whole-recording intake, automatic event discovery and bounded tiled search | Source is present on the pinned `main`, including `intake.py`, `discovery.py`, `scripts/discover_audio.py` and `tiled_search.py` | Presence is not independent real-recording accuracy evidence |
| Automatic upload application, jobs and CLI | [PR #19](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19) is open and draft; observed head `211b478d5142af3df3b1ab3da8d606d48e620d4a` | This PR head is separate from the pinned `main`; a previous product integration receipt does not test this newer head |
| Reproducibility infrastructure | `.github/workflows/tests.yml`, `.github/workflows/checkpoint-replay.yml` and `requirements/py314-linux.lock` exist on the pinned `main` | Existence does not establish that every current PR has passed hosted checks |
| End-to-end acceptance | [Issue #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) is open | Do not infer completion from test counts, issue history or an unaccepted candidate |
| Independent field evaluation | [Issue #53](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53) is open | This check adds no eligible independently timed field recording or sealed holdout result |

The current README already distinguishes these scopes. Older handoff text and the
configured research CLI are insufficient grounds for claiming that automatic
intake/discovery/search do not exist. Conversely, an integration branch containing
an application is insufficient grounds for calling that application merged on `main`.

## Existing integration test receipt

The preserved local JUnit artifact records **264 passing tests plus 14 passing
subtests**, zero failures, errors or skips, at source
[`b6de6db5d5c94e08cdcabbe4469fec47cfa81751`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/b6de6db5d5c94e08cdcabbe4469fec47cfa81751),
tree `74cef6f494db32b9950e944a3a9ebbb9c3e58454`, in approximately 133 seconds.
The [receipt](../evidence/verification/state-20261103/integration-tests.json) and
[raw XML](../evidence/verification/state-20261103/integration-pytest.xml) are copied
without changing their original bytes. This check re-parsed the XML and verified
its SHA-256; it did not rerun that historical source.

These counts describe a frozen integration source. They are neither a test count
for `main` nor an accuracy benchmark, and they do not qualify the later PR #19 head.

## Interrupted metamorphic experiment

The primary's three-event synthetic representation-invariance replay was stopped
before its first decision. Its runtime was the `b6de6db` integration source above;
the runner was local source `06d60ef8003d68da55d2bd5614827bf1f7fa5c81`.
The partial experiment is retained locally at
`results/metamorphic-three-b6de6db-20261103` in the primary's metamorphic worktree.
The [interruption receipt](../evidence/verification/state-20261103/interruption.json)
records this boundary. The harness and unfinished search outputs are not promoted
by this documentation change.

No case reached a decision, no transformation matrix completed, and no invariance
or localization-accuracy conclusion follows. [Issue #61](https://github.com/1337isnot1337/DOPPLERGEIST/issues/61)
remains open. The interrupted job's last persisted running state must not be
relabeled as a completed decision or an application failure.

## Field-data eligibility screen

The metadata-only [AeroSonicDB screen](../evidence/verification/state-20261103/field-metadata-screen.json)
records the publisher URLs and checksums for three small metadata/license files;
no audio was downloaded. The publisher intentionally displaces recording
coordinates, and the inspected materials do not establish independently verified
sample-zero UTC synchronization or a displacement bound adequate for the project's
distance thresholds. The Australian corpus is also outside the current CONUS
acceptance scope. It has not been counted toward the independent field gate.
See the [publisher's record](https://zenodo.org/records/10215080) and the
[issue #53 screening comment](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53#issuecomment-6594421391).
Do not try to recover intentionally withheld recorder coordinates.

Further validation can use synthetic inputs or recordings collected with consent
and known ground truth. Preserve truth separation and all failed or inconclusive
cases. A close synthetic leading hypothesis and an accepted independently
validated real localization remain different claims.
