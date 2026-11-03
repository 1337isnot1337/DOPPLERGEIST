# Preserved strict replay revisions

This packet preserves four completed experiments before the full-coverage fixture
variant. Every protocol required a supported `succeeded` decision. All four
experiments completed the HTTP pipeline and failed that scientific acceptance
gate. Their original receipts remain unchanged.

| Case directory | Published source | Result |
| --- | --- | --- |
| `strict-local-31484` | `31484bf0266007ab20fadc628a5e6a6376f71b88` | `inconclusive / ambiguous_locations` |
| `strict-hosted-31484` | Same source | `inconclusive / ambiguous_locations` |
| `finite-local-134f` | `134f617d751b705c16a422ddc9ed53e78bf88012` | `inconclusive / finite_search_incomplete` |
| `finite-hosted-134f` | Same source | `inconclusive / finite_search_incomplete` |

The local commits have different metadata from the published commits. Their Git
trees match exactly: `157207dc059781f40443c2766a8e2ae315f50020` for the first
revision and `b009d69fdd85c692d004626c902cc8cf6485184d` for the finite revision.
Source manifests record the executed files in each environment.

## Integrity and interpretation

`manifest.json` records every preserved receipt's source path, original size and
SHA256, storage encoding, stored size, and stored SHA256. Files larger than
50,000 bytes use deterministic gzip compression. Decompression recovers the
original bytes. Small files retain their original bytes directly.

`summary.json` contains selected receipt fields. A missing field remains `null`;
it does not imply failure or success. The HTTP receipts and independent audits
provide the complete checks for older schemas.

The finite runs recorded 1,512 unknown score candidates. A diagnostic replay
traced them to missing temporal trajectory support. The original fixture only
samples each aircraft for 270 seconds. These unknowns remain unresolved in the
preserved runs; no close diagnostic coordinate is relabeled as a supported fix.

## Hosted artifacts

| Workflow run | Artifact ID | Downloaded ZIP SHA256 |
| --- | --- | --- |
| [41571753852](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41571753852) | `13201134321` | `7fa09687a9264920b5741194eeb6cac19a6f4b8059954b067765b7b726875d1f` |
| [41573699946](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41573699946) | `13203250961` | `0b47e337370ce56503974c20567fff73a5c481e645edd04dec200dd9c7f020a0` |

The first hosted artifact omitted its declared zero-byte manager lock. Its
scientific payload hashes passed, but the complete inventory audit failed. The
missing file has not been fabricated or inserted into this packet.

The later workflow included hidden files within its two results directories.
Its independent audit verified all 5,041 declared files, including the manager
lock, totaling 139,793,354 bytes. The scientific decision still failed because
the trajectory support remained incomplete.

## Scope

This compact packet excludes audio, flight indexes, spectral arrays, search
tiles, and SQLite ledger payloads. Original artifact manifests retain their
sizes and hashes. The source commits and predeclared protocols identify how to
regenerate the experiments. Hosted artifacts have the workflow's retention
period; these committed receipts remain durable.

The source-provenance folder records recovery and audit of existing released
metadata. It does not establish independent recorder timing or microphone
coordinates. Copyrighted source transcripts and screenshots are not duplicated
here.
