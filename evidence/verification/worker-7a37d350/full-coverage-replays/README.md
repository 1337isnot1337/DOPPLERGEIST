# Supported full-coverage synthetic replays

This packet preserves one synthetic four-flyover case executed locally and in
GitHub CI. Both strict runs returned `succeeded / supported_by_evidence_checks`.
All four true flyovers matched, and both returned the exact recording clock
supplied in the request.

| Environment | Complete runtime | Point error | Returned sensitivity radius |
| --- | ---: | ---: | ---: |
| [Local receipt](local/acceptance.json.gz) | 329.77454449200013 s | 0.07932759464807976 m | 117.19570324924227 m |
| [Hosted receipt](hosted/acceptance.json.gz) | 372.59730909999996 s | 0.07993058330434617 m | 117.19575435008896 m |

The 100, 500, and 1,000 m point-error tiers passed in both runs. Those flags do not
mean that the uncertainty radius is at most 100 m. The radius is an uncalibrated
union of evaluated finite modes and reported sensitivity profiles. It does not
establish a coverage probability or continuous-space uniqueness. These runs
repeat one development fixture in two environments; they are not two independent
real-recording validation cases.

## Frozen source and protocol

- Tested local implementation: `b6413a6fcb4abc43816ab439931af6433296032e`.
- [Published implementation](https://github.com/1337isnot1337/DOPPLERGEIST/commit/e33e2f38068c704a1d9e5a8a76c41d73b8020f92): `e33e2f38068c704a1d9e5a8a76c41d73b8020f92`.
- Identical Git tree: `69169d71301576b15f859879df8f5bf7165c7613`.
- [Pull request](https://github.com/1337isnot1337/DOPPLERGEIST/pull/86): PR 86.
- [Hosted workflow](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41575931388): run `41575931388`.

Both protocols select four events, seed `20261103`, fixture variant
`full-coverage`, an expected supported `succeeded` result, and a 1,800-second total
budget. The normal request supplies exact sample-zero UTC and CONUS coverage.
It does not supply true coordinates, true flight IDs, or manual acoustic windows.
The offline population contains all 12 generated aircraft. Terrain is constant.
Evaluation truth was opened only after the service and workers stopped.

The scientific package digest is
`9b3e8ac4ff52c07ba9671a369cba02dca0935daf26ff6ef2fa49ce57b7393139`
in both environments. It is unchanged from the preceding failed finite-search
integration. The new fixture supplies longer physically bounded trajectories;
it preserves the uploaded MP3, labels, original samples, and all distractors.
The renderer WAV differs only in creation-time `PEAK` metadata. Its audio samples
and all other bytes are preserved.

## Packet layout

| Directory or file | Contents |
| --- | --- |
| `local/` | Original local protocol, acceptance, HTTP and stage receipts, source/input manifests, and small evaluation metadata |
| `hosted/` | Equivalent hosted receipts and the verified artifact download receipt |
| `tests/` | Frozen-source regression results, fixture checks, and snapshot preflight |
| `audits/` | Independent inventory, retention, fixture-invariance, geometry, clock, ridge-window, and uncertainty checks |
| [manifest.json](manifest.json) | Original and stored sizes, hashes, paths, and encoding for preserved artifacts |
| [summary.json](summary.json) | Selected fields for both supported outcomes; original receipts remain authoritative |

The [local terminal audit](audits/local-terminal.json) verified all 5,041 declared
files totaling 246,957,823 bytes. The [hosted terminal audit](audits/hosted-terminal.json)
verified all 5,041 declared files totaling 246,107,737 bytes. Both also verified
all 4,953 stage artifacts. The fixture audits check actual input preservation,
every original trajectory row, and serialized tails.

The [local semantic audit](audits/local-semantic.json) and
[hosted semantic audit](audits/hosted-semantic.json) each passed 27 checks.
They independently recompute all 105 candidate geometry, clock, flight-set, and
ridge-window comparisons, plus the reported finite union. Each winning group has
100% ridge-time support in its assigned true arrival interval and 0% in every
other true interval, even with zero edge tolerance.

## Exact-byte restoration

Small receipts retain their original bytes directly. Larger receipts use
deterministic gzip compression. The manifest records both the original and stored
SHA256 values. Decompression restores the original receipt; it does not normalize
JSON or rewrite historical paths.

From this directory, verify the two decompressed acceptance hashes:

```bash
gzip -dc local/acceptance.json.gz | sha256sum
gzip -dc hosted/acceptance.json.gz | sha256sum
```

Expected local SHA256:
`fa43bb2301386ec45059061afe9506488421226a1cbfaa59117fc0bb6ffc8d13`.
Expected hosted SHA256:
`fee5b38ecaf3c1c2040df3f39fcc2e9dee4e7c08614c116f0c765b7970504761`.

Original absolute paths identify the execution environment; they are not portable
restoration instructions. Audio, flight indexes, rasters, spectral arrays, search
tiles, and SQLite ledger payloads are excluded from this compact packet. Their
sizes and hashes remain in the original artifact manifests. The hosted archive
is artifact `13203940538`, with ZIP SHA256
`6d30b62d564bb238a5e034e4ce91c947edf89eb3a9e35e8b7ed44693abe57198`.
See its [download receipt](hosted/download-receipt.json). Hosted artifacts remain
subject to workflow retention; committed receipts provide the durable record.

## Preserved audit correction and earlier failures

The semantic auditor's first local version incorrectly compared the recorded
one-second edge tolerance with the full two-second discovery window. The frozen
runner explicitly uses half that window. Every numeric ridge-window fraction
already matched; only the auditor's tolerance comparison failed.
The [correction record](audits/local-semantic-correction.json) preserves both
script versions and the initial failed audit. The corrected audit uses the
predeclared tolerance and adds a zero-tolerance winning-group check. No native
replay receipt, source implementation, or scientific threshold changed.

The [earlier strict-revision packet](../replay-revisions/README.md) preserves the
`ambiguous_locations` and `finite_search_incomplete` failures. The new trajectory
dataset does not replace or retroactively promote them. The
[worker report](../../../../docs/verification/WORKER_7A37D350.md) distinguishes this
supported synthetic result from the configured regional real-data replay.
Independent real-recording acceptance remains blocked by recorder-position and
sample-zero UTC provenance. The 117.2 m synthetic envelope does not resolve those
gaps or validate real national traffic coverage.
