# Worker 7a37d350 verification, 2026-11-03

## Result

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

## Remaining acceptance and publication

The decisive remaining result is a supported automatic real-recording
localization with independently established recorder position and recording-time
evidence. The evaluation must preserve the declared coverage and all supported
independent flyovers. A successful producer decision and the distance criterion
must both hold.

The configured regional distance and inconclusive synthetic coordinate do not
satisfy that requirement. This report does not close
[DG-12 / issue #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13).

Final publication references remain pending the integration lead's review:

- Integration commit: pending.
- Pull request: pending.
- Release or complete artifact location: pending.
