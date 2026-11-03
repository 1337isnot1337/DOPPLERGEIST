# Worker 7a37d350 verification, 2026-11-03

## Current evidence and publication

The strict four-event HTTP replay passed end-to-end locally and in GitHub CI on
the explicit full-coverage synthetic dataset. Both runs returned
`succeeded / supported_by_evidence_checks` and matched all four true flyovers.
Both returned the exact clock supplied in the request. Their point errors and
uncalibrated sensitivity radii are distinct measurements:

| Current experiment | Scientific outcome | Complete runtime | Point error | Returned sensitivity radius | Accepted point-error tiers |
| --- | --- | ---: | ---: | ---: | --- |
| Full-coverage synthetic, local | Supported under the declared finite-grid checks | 329.77454449200013 s | 0.07932759464807976 m | 117.19570324924227 m | 100, 500, and 1,000 m |
| Full-coverage synthetic, hosted | Supported under the declared finite-grid checks | 372.59730909999996 s | 0.07993058330434617 m | 117.19575435008896 m | 100, 500, and 1,000 m |

The [local acceptance receipt](../../evidence/verification/worker-7a37d350/full-coverage-replays/local/acceptance.json.gz)
has SHA256 `fa43bb2301386ec45059061afe9506488421226a1cbfaa59117fc0bb6ffc8d13`.
The [matching hosted workflow](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41575931388)
finished successfully and passed separate artifact, fixture, and semantic audits.
Its [acceptance receipt](../../evidence/verification/worker-7a37d350/full-coverage-replays/hosted/acceptance.json.gz)
has SHA256 `fee5b38ecaf3c1c2040df3f39fcc2e9dee4e7c08614c116f0c765b7970504761`.
These are repeats of one synthetic case in two environments.

The accepted distance tiers compare the estimated point with synthetic truth.
They do not mean that the uncertainty radius is at most 100 m. The 0.079 m point
error does not establish submeter precision, a calibrated confidence interval,
or exhaustive continuous-space uniqueness.

The configured research replays also passed their original checkpoint gates.
Earlier strict HTTP failures remain separate, unchanged results below.

The implementation is published in [PR 86](https://github.com/1337isnot1337/DOPPLERGEIST/pull/86).
The tested local implementation is `b6413a6fcb4abc43816ab439931af6433296032e`.
Its published equivalent is
[`e33e2f38068c704a1d9e5a8a76c41d73b8020f92`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/e33e2f38068c704a1d9e5a8a76c41d73b8020f92).
Both have Git tree `69169d71301576b15f859879df8f5bf7165c7613`.
Later report and evidence commits do not change which frozen source produced a run.

Operational synthetic pipeline verification, configured real-data reproduction,
and supported independent real localization are distinct claims. The first two
have evidence below. Independent real acceptance still requires recorder-position
and recording-time provenance. This report does not close
[DG-12 / issue #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13).

The [original evidence manifest](../../evidence/verification/worker-7a37d350/manifest.json)
and [preserved revision packet](../../evidence/verification/worker-7a37d350/replay-revisions/README.md)
retain raw receipts, hashes, audits, and historical failures. No prior result is replaced.

## Explicit full-coverage fixture experiment

The new dataset adds bounded tangent tails to every aircraft, including every
distractor. It preserves all 3,252 original rows, all 12 identities, and the
original production spline coefficients exactly. Each track now contains 2,224
one-second samples, totaling 26,688 rows.

The uploaded MP3, truth labels, request, terrain, and geoid match the historical
four-event run byte-for-byte. Renderer WAV audio samples and non-timestamp metadata
also match. Only its wall-clock `PEAK` timestamp differs; no historical file was
edited. The new mode is selected explicitly with `--fixture-variant full-coverage`.
The original `local-segments` default remains available.

The [independent fixture audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/staged-independent-methodology.json)
passed 20 checks. Its SHA256 is
`a1d27e9fa7e6dc2149192bb1fda3ddd67f0ce57f8ed83f5a822f70679fcee760`.
It reconstructed continuous speed from the serialized production spline.
The maximum certified speed was 101.74426193081403 m/s, below the declared
137.2 m/s bound. Position and velocity remain continuous at both tangent joins;
acceleration continuity is not asserted.

The temporal bound covers sound speeds of at least 338 m/s and nominal receivers
inside the actual 20 km three-dimensional CPA distance gate. For the 960-second
recording, every track covers emission times from -963 to +1,260 seconds.
The first-arrival upper bound precedes sample zero by 1.4745562130176495 s.
The last-arrival lower bound follows the recording by 300 s. Subsonic motion makes
arrival time monotone. One-second sampling stays below the 30-second gap threshold.
Refinement and uncertainty profiles remain subject to unchanged runtime support
and acceptance checks. The temporal proof does not establish optimizer convergence,
continuous uniqueness, or calibrated accuracy.

The [frozen-source test summary](../../evidence/verification/worker-7a37d350/full-coverage-replays/tests/local-verification-summary.json)
records 550 passing tests, one documented PID-namespace skip, and 25 passing
subtests. Its JUnit has 551 test-case elements and suite count 576. The final
fixture-specific check passed 21 tests. Snapshot preflight passed with SHA256
`a46e1df0e84d7b73768a72ac0edc8ac8593e487b6ef9463bb9ec8b6a7b47f4e9`.
These regression checks do not replace an end-to-end scientific result.

The strict replay declares a 1,800-second total budget and requires a supported
`succeeded` decision. Earlier 1,200-second protocols and failed outcomes remain
unchanged. This is a different trajectory dataset and cannot retroactively promote
a historical result. The local run passed after all 4,940 tiles, 97,280 coarse
points, and 1,681 fine points completed. The earlier finite run searched 28,672
coarse points; the new experiment did not narrow that domain.

The local ledger records 6,801 distinct finite modes: 100 retained and 6,701 discarded.
There are zero unclassified score candidates. The discarded upper score bound is
2.097033056419206. Its normalized gap, 0.4649500542658541 per group, exceeds the
unchanged 0.2 near-tie threshold. The scientific implementation digest remains
`9b3e8ac4ff52c07ba9671a369cba02dca0935daf26ff6ef2fa49ce57b7393139`,
matching the preceding failed finite integration.

The base profile radius was 6.283345338474251 m. The returned finite union expands
it to 117.19570324924227 m across 10 near-tied returned representations from five
mode IDs. It covers evaluated points and actually reported profiles; unperformed
competitor profiles remain unbounded. No coverage probability is inferred.

Search took 279.82824932600124 s within the 329.77454449200013 s complete replay.
All seven HTTP checks, seven stage checks, and 18 job cross-checks passed.
Every execution stage exited 0. The service stopped cleanly at
2026-11-03T04:08:47.639327Z; evaluation truth reading began at
2026-11-03T04:08:55.245794Z. No timeout, interruption, or forced kill occurred.

The [independent terminal audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/local-terminal.json)
passed 39 checks and verified 5,041 files totaling 246,957,823 bytes.
Its SHA256 is `8ca25334db10b29d656905dc5e9b8b6532a830384998579a52399fe887f99121`.
The [actual-input fixture audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/local-fixture.json)
passed 26 checks, including every serialized tail and original-input invariance.
A separate [semantic audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/local-semantic.json)
passed 27 checks and independently recomputed all 105
candidate geometry, clock, flight-set, and ridge-window comparisons, plus the union.
Its SHA256 is `e0738e7ea2e4c0bc43f15d934ce21e9ee3af78eb1e92f56bd0f1989ba8fa1de5`.
Its [correction record](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/local-semantic-correction.json)
preserves an initial auditor-only tolerance comparison error. The corrected audit
uses the frozen runner's one-second edge tolerance. Native receipts and policy are unchanged.

The winning groups contain 327, 366, 380, and 379 unique ridge times. Each has
100% support in its assigned true arrival interval and 0% in every other true
interval, even with zero edge tolerance. This independently supports the four
flyover associations. It does not establish real-data association accuracy.

### Hosted strict repeat

The hosted replay used a clean checkout of published commit
`e33e2f38068c704a1d9e5a8a76c41d73b8020f92`. It completed in
372.59730909999996 s, including 313.851646524 s of search. It also completed all
4,940 tiles, 97,280 coarse points, and 1,681 fine points, with zero unknowns.
Its finite counts are 6,801 distinct modes, 100 retained, and 6,701 discarded.

The hosted point error was 0.07993058330434617 m. Its base profile radius was
6.268946589875684 m; the reported finite union was 117.19575435008896 m.
Small numerical differences between environments did not change acceptance.
All four true flyovers and the exact supplied clock matched. All point-error tiers
passed. The [hosted semantic audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/hosted-semantic.json)
passed 27 checks, including all 105 candidate comparisons and the exact finite union.
The winning groups again have 100% target-window and 0% cross-window support,
even with zero edge tolerance. Its audit SHA256 is
`00479de49684e57f1d02863dbad9efd4555f816c4b8cf87332fb45aff90d028d`.

The [hosted terminal audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/hosted-terminal.json)
verified all 5,041 declared files, totaling 246,107,737 bytes, and 4,953 stage artifacts.
Its SHA256 is `ae84f43c4332bbc8c5e70abf0bb40c6085b1c0feb1ecd3db424041aec7741db8`.
The [hosted fixture audit](../../evidence/verification/worker-7a37d350/full-coverage-replays/audits/hosted-fixture.json)
also passed, with SHA256
`240eda25416cc94c9511cbe0ea65edf27840097af05616030efd752bc45a8cb4`.
Artifact `13203940538` contains an 89,042,803-byte ZIP with SHA256
`6d30b62d564bb238a5e034e4ce91c947edf89eb3a9e35e8b7ed44693abe57198`.

Hosted JUnit records 551 test cases, zero failures, zero errors, and zero skips.
Its suite count is 576 with subtest accounting; regression runtime was 94.946 s.
The executed snapshot SHA256 is
`fdf6b9e2d562fcceff44f881503a8859b6289c229209a9c013fb998f8bd415b1`.
Only the generated `egg-info/SOURCES.txt` inventory differs between whole snapshots; committed source files and scientific package digests match.
The
[complete packet guide](../../evidence/verification/worker-7a37d350/full-coverage-replays/README.md)
explains exact-byte restoration and distinguishes these supported results from
all preserved historical failures.

### Reproduce the frozen experiment

After installing dependencies, reproduce this experiment from the frozen review
source with a new output directory:

```bash
.venv/bin/python scripts/ci_http_replay.py --events 4 --seed 20261103 --fixture-variant full-coverage --expect-status succeeded --timeout-s 1800 --output results/http-full-coverage-new
```

## Initial replay outcomes

The configured synthetic and regional real-data replays passed their original
100 m checkpoint gate. The actual HTTP replay completed the automatic pipeline,
but its scientific decision remained `inconclusive` with reason
`ambiguous_locations`.

These results do not complete the automatic real-audio acceptance goal. They
establish three specific replay outcomes, with the original evidence and scope
limits intact. The [compact summary](../../evidence/verification/worker-7a37d350/summary.json)
records those distinctions in JSON.

| Replay | Measured horizontal WGS84 distance | Outcome |
| --- | ---: | --- |
| Configured synthetic, two events | 15.395598179748822 m | Original checkpoint passed. Correct flight pair. |
| Configured synthetic, known minute | 40.87444831462204 m | Original checkpoint passed. Correct flight. |
| Configured regional real recording | 43.85847078233993 m from the published platform coordinate | Original checkpoint passed. Limited reference provenance. |
| Automatic HTTP upload, four synthetic events | 0.07932759464807976 m for the leading diagnostic candidate | HTTP and evidence checks passed. Supported localization failed. |

The [project target](../AGENT_TASKS.md) permits up to 1,000 m error on supported,
independently evaluated real recordings. The configured receipts retain their
original strict comparison, `error_m < 100`. No historical threshold changed.

The HTTP result has no accepted localization at 100, 500, or 1,000 m. Its close
leading coordinate does not change the producer decision.

## Configured synthetic replay

The checkpoint runner generated fresh inputs and ran both configured cases
through the research CLI. The runner loaded evaluation truth after both searches
finished. The two-event case selected `true-A` and `true-B`. The known-minute
case selected `true-A`.

| Case | Clock error | CLI runtime | Pipeline runtime |
| --- | ---: | ---: | ---: |
| Two events | +0.06380653381347656 s | 57.089823707001415 s | 54.710632066999096 s |
| Known minute | +0.5 s | 5.808332649001386 s | 4.314339821999965 s |

The total replay took 65.10348595100004 s. Its interval was
2026-11-03T02:52:06.432525Z through 2026-11-03T02:53:11.535938Z.
The [original receipt](../../evidence/verification/worker-7a37d350/configured-synthetic/acceptance.json)
contains the input hashes, runtime versions, exact commands, and implementation
hashes.

These cases used supplied event windows and frequency bands. They did not
exercise automatic discovery, the upload interface, or independent real-recording
accuracy. The preserved configuration files are
[two-events.json](../../evidence/verification/worker-7a37d350/configured-synthetic/two-events.json)
and [known-time-minute.json](../../evidence/verification/worker-7a37d350/configured-synthetic/known-time-minute.json).

## Configured regional real-data replay

The real replay used the restored WAV, regional trajectories, aircraft types,
terrain raster, and geoid raster. The original
[configuration](../../evidence/verification/worker-7a37d350/configured-regional/reproduce-local.json)
remained unchanged. Its SHA256 is
`d397fa1102d33af564f1414141a879d8394be7a1d04b941e3b9e88915646b541`.

The CLI completed with exit code 0. The pipeline took 38.82141950799996 s, and
the CLI took 41.041487852999126 s. The complete replay took
41.69168271300077 s, from 2026-11-03T02:59:48.057979Z through
2026-11-03T03:00:29.749610Z.

The distance exactly reproduces the checked-in regional baseline distance. The
search used two supplied event windows, frequency bands, parameter ranges, and
regional bounds. It processed 2,525 grid points and 3,587 trajectory segments.
The [receipt](../../evidence/verification/worker-7a37d350/configured-regional/acceptance.json)
preserves the result and reference qualifications.

The comparison coordinate comes from a public nest-platform listing. It is not
surveyed microphone ground truth, and its physical uncertainty remains
unquantified. The recording clock also lacks independent verification. Loading
the reference after the search does not remove the source-informed configuration.

This result establishes the configured regional replay. It does not establish
automatic upload acceptance, independent real-recording accuracy, or national
search coverage. Only this two-event configuration ran in this replay.

## Actual HTTP replay with four synthetic events

The HTTP run submitted an MP3 through the local upload service. The request
supplied the generator's exact sample-zero UTC and requested CONUS coverage.
It supplied no event windows, frequency bands, true coordinates, or true flight
identities. The offline index retained all generated traffic.

The service discovered four independent event groups. The search completed all
4,940 tiles and reported no unsearched tiles or tile failures. The retained
evidence showed all four groups in the joint fit. Generated traffic completeness
does not establish real-world coverage.

The producer returned 105 retained candidate hypotheses and the decision
`inconclusive` / `ambiguous_locations`. The leading candidate explained the four
required synthetic flyovers. Its clock error was 0 s because the request supplied
the exact generator clock. The [original acceptance receipt](../../evidence/verification/worker-7a37d350/http-four-event/acceptance.json)
retains `passed: false` and `supported_localization_passed: false`.

| Distance tier | Retained candidates within the tier | Candidates with the full correct flight set | Supported localization |
| --- | ---: | ---: | --- |
| 100 m | 20 | 8 | No |
| 500 m | 105 | 53 | No |
| 1,000 m | 105 | 53 | No |

These counts describe candidate hypotheses, not accepted fixes. The search did
not claim exhaustive assessment of all alternative modes. Browser behavior,
live data acquisition, and independent real-recording accuracy remain unverified.

The complete replay took 234.54135051400044 s. Generation took
6.610181591999208 s, indexing took 1.4021897190013988 s, and the HTTP stage took
226.2638104100006 s. Tiled search reported 194.6471166780011 s.

The [pre-run protocol](../../evidence/verification/worker-7a37d350/http-four-event/protocol.json)
declared the expected inconclusive result. The
[HTTP receipt](../../evidence/verification/worker-7a37d350/http-four-event/http-verification.json)
records successful transport and expectation checks. Matching that expectation
does not count as accepted localization.

After shutdown, a separate
[artifact audit](../../evidence/verification/worker-7a37d350/http-four-event/audit.json)
verified 5,040 manifest entries totaling 66,073,363 bytes. A later
[pipeline evidence audit](../../evidence/verification/worker-7a37d350/http-four-event/pipeline-evidence-audit.json)
verified intake, discovery, acquisition, search, refinement, decision, and
automatic provenance. All 20 missing, corrupt, or inconsistent evidence controls
failed as expected.

The later audit examined saved stage evidence. It did not rerun the scientific
pipeline or replace the original HTTP receipt. The service and workers stopped
before the evaluator loaded truth. This ordering does not claim operating-system
isolation of truth files.

## Memory measurement correction

The original synthetic and HTTP receipts contain zero values from the external
process-tree RSS sampler. Those values are invalid measurements. The execution
environment exposes process identifiers and numeric `/proc` paths from different
PID namespaces. The old sampler can read unrelated processes or return zero.

The [synthetic correction note](../../evidence/verification/worker-7a37d350/configured-synthetic/rss-correction.json)
and HTTP artifact audit preserve this finding separately. Neither correction
changes the original receipts. No whole-pipeline memory peak was recovered for
those runs.

The correction note recorded a pending helper review. The integration lead
subsequently approved the namespace guard and updated the audited helper blob to
`1612021776965713e88c586563ab51d4b8682a8b`. This review resolves that historical
pending state. The correction note retains its original bytes.

The regional replay used the reviewed namespace guard. Its receipt records
`peak_sampled_process_tree_rss_bytes: null`,
`memory_measurement_status: "unavailable"`, and
`memory_measurement_reason: "proc_pid_namespace_mismatch"`.

The HTTP search worker separately reported a native high-water counter of
333.27734375 MiB through the end of tiled search. That counter does not use
numeric `/proc` lookups. It excludes the complete process tree and later joint
refinement. No worker-start baseline was recorded, so inherited high-water state
was not separately excluded.

## Executed source and compact evidence

The [manifest](../../evidence/verification/worker-7a37d350/manifest.json) lists every
preserved file, source path, size, and SHA256. Raw JSON receipts retain their
original bytes and historical absolute paths. Those paths identify the original
workspace and are not portable restoration instructions.

The archives preserve the exact implementation files from each executed snapshot.
The synthetic archive also includes its generator. The HTTP archive includes its
runner and the uncommitted verifier that actually ran. Archive metadata is
normalized, while each payload file retains its original bytes. Cache and bytecode
files are excluded.

| Replay | Recorded checkout commit | Recorded implementation snapshot SHA256 |
| --- | --- | --- |
| Configured synthetic | `e2bb3dce63591ff7c92a0f985b40dd6a01a24cec` | `134d2ee28c2b1ea8b605fd08cdcae68807e2293d9da1e4168ae8a1ab1fc417ae` |
| HTTP four-event synthetic | `e2bb3dce63591ff7c92a0f985b40dd6a01a24cec` | `3bdd8c40e75cbf911eaf210dcffd503ea77371a7cb99670d357c57bb0e8289f6` |
| Configured regional real | `ea06146122853e8c61885e78b3cd3a7634b1e508` | `3581e2ef3a7eef88d4c9527c99303ba409ea822613ba555f04934fc36e625d7c` |

The receipts record uncommitted changes alongside these commit identifiers.
The snapshots, rather than the commit identifiers alone, identify the executed
source. They do not establish execution of the final patched integration code.
The initial HTTP verifier differs from the later verifier that produced the
pipeline evidence audit.

| Executed-source archive | SHA256 |
| --- | --- |
| [Configured synthetic](../../evidence/verification/worker-7a37d350/configured-synthetic/executed-source.tar.gz) | `a09181f332d2f9d906b53e68f92829f97cee2a6aa375378b0e73a49b0f4ac679` |
| [Configured regional](../../evidence/verification/worker-7a37d350/configured-regional/executed-source.tar.gz) | `7e836c20844a6c44f9b6cf6bc7913cbba5e2610fcfc78dcf302d9772d6706d52` |
| [HTTP four-event](../../evidence/verification/worker-7a37d350/http-four-event/executed-source.tar.gz) | `b545c68b23e9055959736caa3ff39501fc1f19c6e7ed6c74619c45baab625ac9` |

The compact evidence excludes audio, flight indexes, trajectory tables, terrain
rasters, spectral arrays, and search tiles. The original replay directories remain
intact. The receipts and archives preserve source and measurement provenance
without duplicating those large inputs.

## Earlier strict replays of the first published tree

The configured synthetic and regional replays remain reproducible as previously reported.
Fresh strict local and hosted HTTP replays also completed every automatic pipeline stage.
Both returned `inconclusive` with reason `ambiguous_locations`.
Neither established supported localization at 100, 500, or 1,000 m.

| Source identity | Value |
| --- | --- |
| Local committed replay | `0d294857e6ca53d94e821ba5a9e3c6d84432ad70` |
| Published commit | [`31484bf0266007ab20fadc628a5e6a6376f71b88`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/31484bf0266007ab20fadc628a5e6a6376f71b88) |
| Identical Git tree | `157207dc059781f40443c2766a8e2ae315f50020` |
| Pipeline implementation SHA256, both runs | `a8d9ecb4d63191d5faf1f28a85ee4590c2b11cb4e35bd33f38d5541202f203cc` |
| Draft pull request | [PR 86](https://github.com/1337isnot1337/DOPPLERGEIST/pull/86) |

The commit identifiers differ because their metadata differ. Their source tree is identical.
The hosted receipt records a clean checkout of the published commit.

| Strict replay | Complete runtime | Search runtime | Leading diagnostic distance | Accepted localization |
| --- | ---: | ---: | ---: | --- |
| Local committed source | 230.4970262700008 s | 189.43406654499995 s | 0.07932759464807976 m | No |
| Hosted published source | 211.913849438 s | 175.24116735699997 s | 0.07932759464807976 m | No |

Both protocols required `succeeded`. Their expectation checks correctly failed when the producer returned `inconclusive`.
The HTTP subprocess exited 1 for that failed gate. It did not crash or exceed its deadline.
The raw HTTP checks, seven stage checks, and 18 job cross-checks passed in both receipts.
Services and workers stopped before evaluation truth was loaded.
Neither run recorded an interruption or forced service kill.

Each run discovered four independent synthetic event groups and completed all 4,940 declared tiles.
The leading diagnostic candidate explained the correct four flights.
Its clock error was zero because the request supplied the generator's exact sample-zero UTC.
The search did not establish exhaustive assessment of all alternative modes.
The close coordinate therefore remains a diagnostic, with all accepted distance tiers false.

The [strict hosted workflow](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41571753852) finished with conclusion `failure`.
Its regression step passed, its strict replay failed, and its artifact upload completed.
The hosted JUnit file records 412 distinct test cases, zero failures, zero errors, and zero skips.
Its suite count is 437; exact subtest accounting can be confirmed from the job log.
The separate [tests workflow](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41571789050) finished successfully.

Local process-tree memory measurements remain unavailable because the PID namespaces do not match.
Hosted measurements were available: 529,707,008 bytes during generation and 501,772,288 bytes during HTTP execution.
These are sampled process-tree RSS values. Sampling can miss peaks and double-count shared pages.
They are not exact whole-pipeline peak measurements.

## Evidence preservation and artifact transfer

The local strict receipt SHA256 is `8a4864733bfeee215e5ae64b215fe4c0420d8e4f7419d2760a8059f96c880b3c`.
Its independent inventory audit verified 5,039 files totaling 65,755,120 bytes.
A second audit independently checked candidate distances, clocks, and flight-set flags.

The hosted strict receipt SHA256 is `dda7f3575eab2c6364d13a3bbd200736206fbf94fcff249d8166d6f0ef92c892`.
A separate semantic audit passed 17 checks on acceptance, stage consistency, shutdown order, and JUnit results.
That audit does not claim complete transferred-artifact verification.
The primary artifact auditor found that upload omitted the hidden manager lock listed in the run manifest.
The completed audit verified 5,038 of 5,039 declared files, totaling 65,878,042 transferred bytes.
The only missing member was the zero-byte manager lock. Every present file matched its recorded hash.
The complete-artifact audit therefore failed, while scientific payload and receipt binding passed.
No omitted file has been fabricated or inserted into the downloaded artifact.

The hosted archive is artifact `13201134321` from run `41571753852`.
Its downloaded ZIP SHA256 is `7fa09687a9264920b5741194eeb6cac19a6f4b8059954b067765b7b726875d1f`.
The downloaded ZIP contains 59,230,481 bytes.

## Implemented finite-search evidence integration

The subsequent integration implements the finite-search producer, assessment mapping, and conservative scorer classification.
The earlier strict receipts above ran before this integration and retain their inconclusive results.
The new source identities are:

| Source identity | Value |
| --- | --- |
| Local committed source | `6a90d254e41ff4c6e61ae6763da3375809aed905` |
| Published commit | [`134f617d751b705c16a422ddc9ed53e78bf88012`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/134f617d751b705c16a422ddc9ed53e78bf88012) |
| Identical Git tree | `b009d69fdd85c692d004626c902cc8cf6485184d` |
| Local executed snapshot SHA256 | `ba781d4ff630a37fb8139d534bea1a99544690c40f2fb42717084b9196d3ba53` |
| New strict hosted workflow | [Run 41573699946](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41573699946) |

The local and published commits have different metadata and parent histories, but identical file trees.
The new local strict replay uses `results/http-finite-7a37d350` in the isolated finite-search worktree.
The replay finished with `inconclusive` / `finite_search_incomplete`.
The strict acceptance and all supported distance tiers remained false.
Total runtime was 255.46627763300057 s; search took 209.6162983560007 s.
The raw HTTP checks, seven stage checks, and all 18 job cross-checks passed.
The service stopped cleanly before truth evaluation, with no timeout or interruption.

The ledger audit passed, but the finite envelope remained incomplete:

| Recorded quantity | Result |
| --- | ---: |
| Completed declared tiles | 4,940 of 4,940 |
| Coarse points | 28,672 |
| Fine points | 1,681 |
| Recorded distinct finite modes | 6,709 |
| Retained raw modes | 100 |
| Discarded modes | 6,609 |
| Unclassified score candidates | 1,512 |
| Justified discarded upper score bound | Unavailable (`null`) |

All 100 retained modes had complete assessments. Unknown candidates elsewhere still prevented a complete finite envelope.
A frozen-source diagnostic replay reproduced all six affected coarse tiles and their retained rows exactly.
It counted 3,024 scheduled trial classifications with incomplete acoustic support and 3,534 event-fit attempts outside recorded trajectory support.
No empty clock schedules caused these unknowns.
The original generator stores each aircraft only from -135 to +135 seconds around its flyover.
Some proposed associations require trajectory support outside those intervals.
The diagnosis receipt SHA256 is `c7e684e64f2f2933b717518875326c850ccdeaa1542e450b4970a7f48b3b31b5`.
The leading diagnostic point was 0.07932759464807976 m from the synthetic truth, independently recomputed with WGS84 geodesics.
Its tested-profile radius was 6.283345338474251 m. Confidence stopped before computing any finite-mode uncertainty union.
Neither value establishes accepted localization or calibrated precision.
Distance-tier acceptance flags measure truth error conditioned on a supported decision; they are not separate confidence guarantees.

This run supplied the exact generator clock, constant terrain, and a complete generated aircraft population.
Population completeness did not supply the missing temporal support for each aircraft.
It does not validate recording-clock inference, a real microphone position, live acquisition, or real national traffic completeness.
The [independent semantic audit](../../evidence/verification/worker-7a37d350/replay-revisions/audits/finite-local-semantic.json) passed 20 consistency checks.
The acceptance receipt SHA256 is `193368b74e1f009e4ff62021b10ecbe65fb38fbf0591d851053e7ed97c025011`.

The corresponding [hosted run 41573699946](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41573699946) also finished with conclusion `failure`.
It returned `inconclusive` / `finite_search_incomplete`, with the same 1,512 unknown candidates and retention counts.
Its HTTP, stage, and job cross-checks passed. All supported distance tiers remained false.

| Finite integration replay | Complete runtime | Search runtime | Diagnostic truth error | Tested-profile radius | Published finite union |
| --- | ---: | ---: | ---: | ---: | --- |
| Local | 255.46627763300057 s | 209.6162983560007 s | 0.07932759464807976 m | 6.283345338474251 m | None |
| Hosted | 357.38725547399997 s | 298.876393295 s | 0.07993058330434617 m | 6.268946589875684 m | None |

The hosted geodesic and clock comparisons were independently recomputed.
Small numerical differences between environments did not change the failed scientific decision.
Hosted JUnit records 535 test cases, zero failures, zero errors, and zero skips; its suite count is 560 with subtest accounting.
The [hosted semantic audit](../../evidence/verification/worker-7a37d350/replay-revisions/audits/finite-hosted-semantic.json) passed 17 checks.
The hosted acceptance SHA256 is `420ae85c33d95578c9aa9bff17878cb234757af68fb4aee8d77b560ec227ac1b`.
The preserved artifact ZIP SHA256 is `0b47e337370ce56503974c20567fff73a5c481e645edd04dec200dd9c7f020a0`.
The [complete hosted artifact audit](../../evidence/verification/worker-7a37d350/replay-revisions/audits/finite-hosted-independent.json) verified all 5,041 declared files, totaling 139,793,354 bytes.
It also checked all 40 source snapshot files and all 4,953 stage artifacts.
Its SHA256 is `e866651a9cef758619438ba89eea92929467473343f9478f256a07dc5a9682e5`.
The archive is artifact `13203250961` from run `41573699946`.
The separate [local full binding audit](../../evidence/verification/worker-7a37d350/replay-revisions/audits/finite-local-independent.json) verified 5,041 files totaling 139,839,336 bytes.
Its SHA256 is `0348581f66c15181bcf6084b95578d4820e55a297485ac67ae417230ab80ddaf`.

W2's retention ledger and W5's assessment mapping are integrated with the new W3 classifier.
The scorer distinguishes evaluated rejection from unavailable model or acoustic support.
Every scheduled shared-clock trial contributes to completeness, including trials that do not win.
Unknown trials keep the finite envelope incomplete. Empty clock domains do not become acoustic rejections.
The changes preserve numerical scoring, clock schedules, and existing scientific thresholds.

The HTTP verifier audits ledger identity, records, hashes, original retained points, stage coverage, and assessment mappings.
It reconstructs candidates before the decision policy expands their uncertainty union.
Tests reject omitted modes, malformed discarded seeds, inconsistent checkpoints, hidden unknown trials, and forged uncertainty.
A positive fixture expands a 50 m tested profile to an approximately 333 m finite-mode union without changing ledger bytes.
A corresponding shifted-only fixture cannot erase an original competing point and claim the smaller profile.
The verifier file passed 85 tests after these controls.
A later null-present precedence control raised its final focused total to 86 passing tests.
These focused stages precede the separately recorded complete hosted regression run.

This bookkeeping establishes only the declared finite evaluation and its reported support.
It does not establish continuous uniqueness, calibrated probabilities, or independent real-data accuracy.

## Existing real reference: independent acceptance remains blocked

The configured real replay measured 43.85847078233993 m from the historical public-platform reference.
Its source-informed regional configuration remains distinct from automatic real-recording acceptance.
The recording clock in that replay was inferred from the same acoustic and trajectory fit.
It is not an independent timestamp.

The preserved source attribution identifies [colsto's reference audio](https://www.youtube.com/watch?v=4CxVxuMVkMc).
The original comparison uses [OspreyWatch nest 3916](https://app.osprey-watch.org/nest/3916).
That listing publishes a rounded platform coordinate and supplies no detailed description.
It does not establish a microphone offset or a physical uncertainty radius.

A separate [OspreyWatch camera listing](https://app.osprey-watch.org/nest/12532) identifies a PSEG webcam at a utility-pole nest platform.
Its stream link agrees with the [official PSEG webcam page](https://www.psegliny.com/wildlife/osprey/ospreycams).
Those pages do not, by themselves, connect the preserved reference WAV to that stream.
They also do not document microphone placement, coordinate accuracy, recording continuity, or sample-zero UTC.
The two published nest coordinates must not be silently substituted for each other.

A surveyed microphone coordinate is not mandatory for a 1 km evaluation.
An independently supported position region can suffice if the prediction meets the criterion throughout that region.
For a reference center with radius R, the conservative distance bound is the measured center distance plus R.
Coordinate rounding alone cannot justify R. Neither can agreement with the fitted location.

The specific evidence still needed for this recording is:

- A source record linking the preserved audio to an identified recorder or published camera stream.
- A justified microphone-position region, including any map error, camera-to-microphone offset, and relevant relocation uncertainty.
- A recording date and defensible sample-zero UTC interval derived independently of the localization fit.
- Evidence accounting for any clipping, edits, stream gaps, buffering, or clock offset when deriving that interval.

Six released metadata and screenshot files were recovered through [export run 41573044968](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41573044968).
All six matched their recorded size and SHA256, totaling 3,156,084 bytes.
The [export receipt](../../evidence/verification/worker-7a37d350/replay-revisions/source-provenance/export.json)
has SHA256 `ed0fd27f0d2d5d37bd6cdbf246e5ccfaec958304f03e96d08945cdde9d9fcb1b`.
The method video's description explicitly links the preserved raw-audio video.
That establishes a documentary link between the demonstration and the audio source.

The raw-audio description is empty. Its metadata records a 3,600-second duration and upload/extraction times, which do not establish capture time.
At transcript time 00:27, the author states September 8 in the continental US.
That statement gives no year, timezone, or sample-zero clock.
At 23:06, the author proposes 20:37 UTC for a one-minute example.
The supplied evidence does not establish that example's exact raw-sample interval or its clock uncertainty.
The recovered spectral frame displays horizontal-axis ticks beyond the raw recording's 3,600-second duration, requiring an explicit timeline mapping.

At 26:03–26:05, the author claims visual identification of the security camera after an audio-guided search.
The recovered Street View frame shows a pole and harbor context, without establishing the recorder or microphone position bound.
These files provide no connection to the PSEG webcam listing.
The documentary link is stronger than before, but bounded recorder position and independent UTC remain unestablished.
The fitted 20:17:29.662 UTC value must not fill either gap by circular reasoning.
The original 43.85847078233993 m comparison remains a source-informed regional replay.

One eligible real recording with a supported automatic result can establish the first valid real demonstration.
A proposed 12-recording corpus is a broader validation program, not a prerequisite for that first result.
Such a result must preserve normal inputs, the declared coverage, all supported independent flyovers, and the producer's scientific acceptance gates.
It must also report reference uncertainty and the distance comparison explicitly.
One successful recording would not establish general reliability, false-positive rates, or real national coverage.
