# Checkpoint replay in a clean runner

The `Checkpoint methodology replay` workflow installs the project in a fresh
Ubuntu/Python 3.12 GitHub Actions runner, runs the tests, generates independent
synthetic audio and executes both configured CLI cases. A dependent job restores
the three regional-input release bundles and repeats the real regional case.
Logs and receipts are preserved when a step fails.

This verifies the configured methodology. Automatic event discovery, MP3 upload
acceptance, independently timed real-audio accuracy and national coverage remain
separate acceptance gates.

## Commands

With project dependencies, pytest, ffmpeg, ffprobe and GitHub CLI installed:

```bash
python -m pytest -q
python scripts/ci_checkpoint_replay.py --output results/new-synthetic-replay
python scripts/restore_ci_checkpoint.py --destination . --receipt results/new-restoration.json
python scripts/ci_checkpoint_replay.py --output results/new-regional-replay --real-config data/source/reproduce-local.json
```

Each replay output directory must be new. Restoration refuses to overwrite any
existing destination file. Use a fresh checkout to restore regional data. The
three archives total 1,517,171,699 compressed bytes; extraction and staging require
additional disk space. The wrapper uses the shared `scripts/restore_artifacts.py`
downloader and extraction checks. GitHub CLI must have read access to the release
through its existing authentication or `GH_TOKEN`. The workflow supplies its
read-only GitHub token only to the restoration step. Receipts never record the
credential; they record the shared restorer's source hash.

## Checks and limits

The independent synthetic generator is copied unchanged into a new fixture tree.
Both configured cases run through the actual CLI. Evaluation truth is moved out
of that tree without parsing it and read only after both searches finish. This
is procedural truth separation, not an operating-system access boundary.
Each synthetic case must locate within 100 m and select the expected flights.
Every requested case, including failures, appears in the receipt.

Regional archives and every contained file must match their sizes and SHA256
values in the committed manifest. Shared validation runs in a temporary staging
directory before the wrapper publishes new files. No source MP4 is restored. After search, the
regional result is compared with the checked-in public-platform reference.
Source-informed windows/bounds and the unverified independent recording clock
remain explicit. Passing this case does not establish blind real-world accuracy.

Receipts record the fixed source snapshot, configuration/input hashes, package
versions, ffmpeg versions, commands, return codes and sampled memory. A report
file alone does not count as a successful CLI run. The pipeline report also hashes
the exact parsed configuration, ridge files, type database and configured
DEM/geoid files. `provenance.truth_separation` is `not_assessed`: hashes cannot
establish how event windows or search bounds were selected. Used Copernicus tile
hashes are explicitly incomplete when the provider does not expose those paths.

Implementation hashes cover only the `aircraft_geoloc` package's Python files.
The workflow also builds and installs a wheel in a separate virtual environment.
An isolated Python process checks that its package digest matches the checkout
and that adding an unrelated installed module cannot change the digest.

## Evidence and execution

Artifacts contain acceptance receipts, per-case reports/plots, logs, source
snapshots and environment records. The generated synthetic WAV is excluded. The
restored reference WAV and source MP4 are never uploaded. GitHub retains the
artifacts for 30 days.

The initial push trigger is restricted to `worker/ci-checkpoint-20261102` to avoid
large downloads on unrelated development pushes. After merge, use GitHub's
**Run workflow** action. Lightweight general CI remains a separate concern.
