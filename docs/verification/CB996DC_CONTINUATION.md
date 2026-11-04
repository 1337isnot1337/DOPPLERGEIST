# Continuation of cb996dc checkpoints

This profile continues stopped searches from `cb996dcb49b9d31a24c10b9b5418c35423f7bbcd` under a specific Python consumer.
It ports the unique behavior from [PR #260](https://github.com/1337isnot1337/DOPPLERGEIST/pull/260) after the #263 compatibility changes.
The profile preserves completed tile bytes, their producer identities, and the retained scores and bounds.

The consumer must match the 30 source hashes in [the verification receipt](cb996dc-continuation-20261104.json).
Those files are identical at `350c9bfa1a56ce2b46d0418b39779b12cdfa04de` and `be56c2fae81fe65159103ddb2bf3ccd59ca3bb67`.
The consumer also needs the `checkpoint_resume.py` profile and tests from this change.
The source list covers search orchestration, input interpretation, scoring, retention, and their Python dependencies.
It excludes this adapter and files that only provide CLI, API, or UI behavior.

The geometry change proposed in #293 changes which trajectory segments can produce scores.
The shared-observation change for #275 changes which event groups can receive independent scores.
Those consumers need a separate compatibility proof before they can reuse these scores.
This profile rejects changes to `geometry.py`, `search.py`, `tiled_search.py`, or any other pinned file.
It does not authorize continuation on arbitrary future versions of main.

## Preserved behavior and restrictions

The old scorer used two matched groups by default for a broad recording clock with multiple groups.
The profile writes that effective minimum into both the search manifest and the operator configuration.
An explicit saved minimum remains unchanged.
The profile uses ordinary batched arithmetic and does not enable `legacy_first_batch`.

The profile requires the Python ridge fitter, acoustic solver, CPA calculation, and flight decoder.
The current native flight decoder has no environment switch, so the source checkout must have no compiled `_native_index` extension.
The producer and consumer must have the same Python version, machine architecture, and recorded package versions.
Audio, request, runtime, event preparation, and saved-file identity checks remain active.
The job must have a terminal status of `cancelled`, `failed`, or `inconclusive`.
The profile rejects fine checkpoints and the legacy first-batch mode because this producer did not create them.

The adapter copies the retention database independently before it changes the run identity.
It keeps the previous search directory and identity files for rollback.
An interrupted metadata commit restores the original search, operator configuration, and audio identity.
The compatibility reader binds the old producer to the new run hash and the pinned consumer fingerprint.

## Real-data evidence

Both replay pairs used the same recorded input and numerical runtime within each pair.
All recordings, trajectories, terrain, and ridge measurements came from recorded or released data.
The receiver location and regional bounds were source-informed.
The historical regional index excluded known jets during its original ingestion and does not establish complete coverage.
These comparisons establish software equivalence for these workloads, not independent location accuracy or nationwide completion time.

| Replay | Candidate associations | Ranked payloads | Retained records | Retained bounds | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Regional tile, two points, 317 tracks, 16 groups | 1,699 | 20 | 112 | 1,617 | Exact scores, order, retention, and remaining payload fields |
| Full-day query, one point, 1,354 tracks, 16 groups | 16,015 | 100 | 499 | 15,691 | Exact scores, order, retention, and remaining payload fields |

The full-day replay used an unknown recording clock and one documented association-anchor partition.
Its query covered `1788825600.17` through `1788911999.6` seconds UTC.
Its anchor partition covered `1788864888.7151732` through `1788865236.7214916` seconds UTC.
Physical fit intervals remained unchanged.
This bounded partition satisfies the dense replay check without a complete nationwide search.

The full-day retention checksum was `ca75b434b7776ca1507c9efed4e3e0f7df891a623c0b28b30fe19d0d1b5048e7` on both revisions.
The producer exposed a `minimum_matched_events: 2` diagnostic that the consumer no longer emits.
The consumer added an empty `clock_excluded_unsupported_tracks` diagnostic.
All other compared payload fields were equal.

The full-day runs finished within independent 180-second limits.
An earlier two-point full-day attempt exceeded the same candidate budget on both revisions before scoring.
Its failure receipts and partial artifacts remain available in the local evidence directory.
The successful point partition used the existing documented benchmark configuration instead of an increased candidate budget.
The shared machine ran concurrent work, so the elapsed times do not support a performance claim.

A separate run used the unmodified cb996dc JobManager and the whole real MP3.
It produced an actual inconclusive job with two nonempty coarse tiles.
The continuation tests reused both tiles and reproduced the ordered ranked result exactly.
The tests also rejected changed producer and geometry identities, invalid manifests, changed runtimes, native processing, and active jobs.
The interrupted-commit control restored the original run identity and metadata.
No original checkpoint or live job changed during these checks.

## Continue a compatible stopped job

1. Stop the job and wait for its worker to exit.
2. Copy the complete stopped job directory, including its retention database and referenced inputs.
3. Use the consumer files from `be56c2fae81fe65159103ddb2bf3ccd59ca3bb67` with this continuation change applied.
4. Use the Python version and package versions recorded in the saved manifest.
5. Verify that the checkout has no compiled `_native_index` extension.
6. Run the continuation from that checkout with all three numerical backend variables set to `python`.

```bash
DOPPLERGEIST_RIDGE_BACKEND=python \
DOPPLERGEIST_ACOUSTIC_BACKEND=python \
DOPPLERGEIST_CPA_BACKEND=python \
PYTHONPATH=src \
python -m dopplergeist.cli resume JOB_ID --jobs /path/to/copied-jobs
```

The normal resume command performs the compatibility checks before it queues work.
An unsupported consumer leaves the old checkpoint incompatible.
An inconclusive result remains inconclusive unless the resumed search independently meets the normal decision requirements.

## Repeat the continuation controls

1. Use an actual stopped cb996dc job with at least one nonempty coarse tile.
2. Run the tests in the pinned consumer checkout.

```bash
DOPPLERGEIST_RIDGE_BACKEND=python \
DOPPLERGEIST_ACOUSTIC_BACKEND=python \
DOPPLERGEIST_CPA_BACKEND=python \
DOPPLERGEIST_REAL_CB996DC_JOB=/path/to/stopped-job \
PYTHONPATH=src \
python -m pytest -q tests/test_real_cb996dc_checkpoint.py
```

The tests copy the real checkpoint before fault injection or continuation.
They skip when the environment does not provide a real job.
They do not generate replacement recordings, trajectories, or scores.
