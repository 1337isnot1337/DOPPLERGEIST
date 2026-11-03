# Independent audit of the four-event CI browser replay

## Outcome

The actual browser upload completed the automatic scientific pipeline and showed
the returned result on desktop and mobile. All four generated flyovers were
discovered and correctly matched. The leading point was **0.0799305833 m** from
the synthetic reference, with **0 s** clock error. The decision remained
**`inconclusive / ambiguous_locations`**. The localization acceptance wrapper
therefore failed, as intended. This evidence does not promote that point to an
accepted location or establish independent real-recording accuracy.

This is a passive audit of another worker's completed run. No additional national
search, threshold change, or producer modification was performed for this audit.

## Source and execution identity

| Item | Identity |
| --- | --- |
| Scientific source | `e2bb3dce63591ff7c92a0f985b40dd6a01a24cec` |
| Source tree | `4db8aec1e8fc0f3b41b18e9d43a9ab07f608247f` |
| Workflow | [41562469268](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562469268) |
| Job | `125676036022` |
| Backend job | `bfe6866813b34141a2ed84d64612110a` |
| Full artifact | [13197212672](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562469268/artifacts/13197212672) |
| Artifact ZIP bytes | 82,031,174 |
| Artifact ZIP SHA256 | `4b48add76c813441cd6578bf5b677bf9f8e5581152d3a1ca80d762389d1ef2fa` |

The downloaded ZIP matched GitHub's reported digest. Its 5,048 entries passed path
and symlink checks before extraction. The original manifest lists 5,061 files:
all **5,040 retained entries** match their recorded bytes and SHA256. Twenty
Python bytecode files were explicitly excluded by the workflow. One transient
service lock is also absent. `artifact-audit.json` preserves the initial missing
file findings; `artifact-retention-audit.json` classifies them. There are no
retained-file byte mismatches. The full workflow artifact has a retention limit;
these selected records and native screenshots are committed for durable review.

## Measured execution

| Check | Recorded result |
| --- | --- |
| CI tests before replay | 267 tests + 25 subtests, zero failures/errors/skips, 64.63 s |
| Browser/HTTP transport | Passed |
| Final scientific decision | Inconclusive: `ambiguous_locations` |
| Discovered / correctly matched independent flyovers | 4 / 4 |
| Source trajectories / samples | 12 / 3,252 |
| Returned candidates / distinct associations | 105 / 5 |
| Completed / planned tiles | 4,940 / 4,940; zero tile failures |
| Coarse / refined grid points | 28,672 / 1,681 |
| Search elapsed time | 277.132268888 s |
| Search process-self peak RSS | 450.14453125 MiB |
| Browser/product stage elapsed time | 328.750445656 s |
| Sampled browser/product process-tree RSS | 1,453,154,304 bytes |
| Whole replay elapsed time | 337.896905789 s |

Native JUnit counts 292 test cases because it includes the 25 subtests. The
process-self RSS and sampled combined process-tree RSS are different measures.
The latter may miss short peaks and count shared pages more than once.

Unknown aircraft types and jets remain in the input. The CI harness permuted
trajectory order and replaced flight identifiers with opaque identifiers while
preserving non-ID trajectory values. The four matched ridges contain 327, 366,
380 and 379 samples. Their samples fall within the correct generated arrivals;
the retained evaluation also checks that they do not overlap other true arrivals.

The normal request supplies the MP3, CONUS scope and trusted sample-zero UTC
`2026-09-21T14:13:20Z`. It supplies no event windows, bands, receiver coordinates or
true flight identifiers. The reference labels were opened after the terminal job
and graceful service shutdown. Reference separation in this CI run is procedural;
the generator and reference were not hidden by an operating-system namespace.

## Why the close point is still unaccepted

The full profile contains 33 successful scenarios for frequency, clock, altitude,
sound speed and source frequency. It reports no boundary limitation or failure
and returns a **6.26894658988 m** sensitivity radius.

The first near-tied, same-association alternative is **21.9602766355 m** from the
leader. Its support gap is **0.03732479396 per group**, below the existing
0.2-per-group near-tie threshold. Ten of the retained rows meet that threshold;
their maximum separation from the leader is **117.195754350 m**. The returned
6.27 m radius does not contain those competing points.

These separations require only the persisted candidates, not reference location.
They motivate review of an explicitly reported combined mode/perturbation
envelope. They do not authorize substituting the 1,000 m target for an established
radius. The run also lacks the new finite-retention and assessed-mode evidence.
Completed tile counts alone do not prove that pruning retained every competitive
mode, or that continuous space has a unique solution.

The independently recomputed leading point error is below 100, 500 and 1,000 m.
Supported localization remains **false at all three thresholds**. All 105 point
errors, associations and near-tie comparisons are retained in
`independent-post-run-evaluation.json`, including non-leading results.

## This is a distinct encoder-variant experiment

The CI harness regenerated the four-event scene from renderer `1f03425` and seed
`20261103`. It did not upload the primary's canonical MP3 bytes.

| Input | Canonical release | Actual CI upload |
| --- | --- | --- |
| MP3 bytes | 3,841,100 | 3,841,101 |
| MP3 SHA256 | `6c44970b812d9147146c2f712c5012efd255ce80bb240aa6c1d9f3a796c45e85` | `9d96ddb1aad4156511b5549b3523bd8293d0a03625a12a21e806f5667f4f1e4c` |
| Decoded float32 SHA256 | `b48e0c4d3c971d45c51ab2249297b3c883f94eddce8789354edbbed77b77074e` | `74604618cb5a375d912233e496b4d95c0ef59715fd525702de40352364cd8e67` |

Both decode to 3,840,000 mono float32 samples at 4,000 Hz, but the decoded samples
are not byte-identical. The MPEG payload after the ID3 prefix also differs. The CI
variant decode matches the saved CI normalized cache exactly. Consequently, this
is not merely a verified metadata-only difference or a canonical-input replay.
The negative equivalence result and exact decoder commands are preserved in
`canonical-signal-equivalence.json`.

The original Parquet does match the canonical source
(`3c9465f1816ed71c097eda451db9c7c2f42fa317163cb406ca7fc0a7be25a258`).
The actual opaque-ID derived Parquet has SHA256
`b85243afa485398e9f9aa9b8d5c62b9eb32f412c8f687bfa56a39e4b303c5fc8`.
Evaluation labels also match the canonical labels
(`339d4517ee1197070404ea1caf901ce5705eb6e10a8dc23bd2b42c3c034f85d6`).

## Audit method and retained evidence

The passive auditor at `../passive-audit/audit_completed_run.py` verified the
declared source against Git objects, all 4,940 checkpoint identities/counts,
input/config hashes, event mapping, candidate ordering, original clock bounds,
per-event contributions, residual score preservation and selected sensitivity.
It did not read truth or execute the producer. Its SHA256 and each check appear
in `independent-integrity-audit.json`.

The separate post-run evaluation used WGS84 geodesic distance and the recorded
opaque-ID mapping. The support gap is `(leader_score - other_score) / max(group
counts)`. The conservative retained-row cutoff is `3.956833284003326 - 0.2 * 4`,
or `3.1568332840033255`. This arithmetic does not bound an unsearched continuous
region or the possible improvement of an unassessed seed.

`source-records.zip` preserves exact source JSON bytes for acceptance, indexing,
request/operator configuration, lifecycle, browser result, backend result,
decision, refinement, provenance, search report and search/original-artifact
manifests. Its members are listed in `source-records-manifest.json`. The original
full artifact retains all tile payloads; their complete hash manifest and the
independent all-tile audit are committed here. `manifest.json` hashes this compact
evidence directory, excluding itself.

`page.png` and `page-mobile.png` are the native CI screenshots, visually reviewed
by the independent verifier. They show the actual inconclusive status, coverage
notes, first five candidate cards and four event curves. The additional 100
candidate cards are collapsed; this audit does not claim an expansion interaction.

The independent field corpus with trustworthy microphone location and sample-zero
UTC remains issue #53. This finite synthetic development case does not close it.

## Follow-up: actual saved-job service readback

`ui-readback/` records a later check of a full independent copy of the 4,965-file
completed backend job, served by the original `e2bb3dc` implementation. The real
HTTP API returns the same result JSON semantically, including all 105 candidates,
four events and the unchanged inconclusive status. The actual artifact endpoint
lists 4,964 files. Its downloaded `refined-candidates.json` matches the original
434,500 bytes and SHA256 exactly. No new upload or scientific run was submitted.
The service exited normally with code zero. All 4,965 job-file hashes were
unchanged after shutdown; the transient manager lock is outside that comparison.

The intended browser expansion check remains **unverified locally**. Official
Playwright browser downloads for both the installed package and the exact CI
browser version returned a 195-byte `Site Unavailable` HTML body instead of a ZIP.
The dedicated cloud browser could not reach this runtime's loopback service
(`net::ERR_CONNECTION_REFUSED`). The native response headers/body and the HTTP
readback/lifecycle receipts preserve those limits. This follow-up therefore adds
actual service restart/download evidence, not an expanded-candidate screenshot
or a new localization result. The original CI mobile-layout check remains the
source for its observed 390-pixel document/viewport equality.
