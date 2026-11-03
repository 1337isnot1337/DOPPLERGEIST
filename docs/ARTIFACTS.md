# Checkpoint artifacts

Release: [checkpoint-2026-11-02](https://github.com/1337isnot1337/dopplergeist/releases/tag/checkpoint-2026-11-02).
The repository is private; collaborators need repository access to download assets.

Readable result JSON, CSV and PNG files are mirrored under `evidence/results/` in
Git. Complete results, including spectral NPZ arrays, and all collected input data
are release assets. The original YouTube MP4 is deliberately excluded. The linked
reference WAV used by the tests remains included.

## Download and restore

For selective downloads and restoration that preserves existing files, use
`python scripts/restore_artifacts.py --list`, then repeat `--bundle NAME` for the
needed bundles. See [SETUP.md](SETUP.md) for examples. This checks bundle/file hashes
and refuses conflicting files. The manual commands below overwrite matching paths.

From the repository root, with GitHub CLI authenticated:

```bash
mkdir -p .artifacts
gh release download checkpoint-2026-11-02 --repo 1337isnot1337/dopplergeist --dir .artifacts
(cd .artifacts && sha256sum -c SHA256SUMS)
for archive in .artifacts/*.tar.gz; do tar -xzf "$archive"; done
mkdir -p data/adsb/2026-09-08
cp .artifacts/v2026.09.08-planes-readsb-staging-0.tar.a? data/adsb/2026-09-08/
```

Restore into a clean checkout or preserve existing `data/` and `results/` first:
archive extraction writes those paths. The raw ADS-B parts are already compressed
internally and are uploaded unchanged. They are not independently extractable tar
files; the ingestion script streams their concatenation.

To download only enough for the regional reference replay, select these assets
with repeated `--pattern` arguments: `data-source.tar.gz`, `data-adsb-derived.tar.gz`,
and `data-terrain.tar.gz`. Download `manifest.json` and `SHA256SUMS` as well.
Verify selected files against their matching checksum lines before extracting.

## Manifest and transformations

[The checked-in manifest](../evidence/artifact-manifest.json) and release
`manifest.json` list each asset's size/hash and every contained file's path,
size/hash. Except for the two YouTube metadata JSON files, data and results are
byte-for-byte exports. Those metadata exports retain descriptive provenance but
omit transient media URLs, request headers and playback metadata; originals remain
local. Their original and exported hashes are both recorded.

Historical failed measurements, failed input downloads and logs are retained as
provenance; their presence is not a claim that they are usable inputs. Installed
virtual environments and Python caches are not research artifacts and are omitted.

`scripts/package_artifacts.py` builds the checksummed bundles without uploading
anything. It excludes MP4/video files and refuses to overwrite an existing bundle
directory. The published manifest is the inventory for this particular checkpoint.
