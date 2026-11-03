# Four-flyover browser replay: 2026-11-03

The actual browser-to-HTTP pipeline completed on the full synthetic recording. Its leading candidate was **0.07993058330434617 m** from the synthetic reference.

The producer returned **`inconclusive / ambiguous_locations`**. **Supported localization did not pass**, despite the small leading-candidate error. The [complete acceptance receipt](acceptance.json) preserves these separate outcomes.

| Outcome | Recorded result |
| --- | --- |
| Browser upload, HTTP service, result reload, and original-file download | Passed |
| Automatic discovery | Four events in four independent harmonic groups |
| Leading candidate | Correct complete four-flight association |
| Leading horizontal error | `0.07993058330434617 m`, WGS84 geodesic distance |
| Recording-clock error | `0.0 s`, within the exact supplied window |
| All four true flyovers explained | Passed |
| Producer decision | `inconclusive`, reason `ambiguous_locations` |
| Supported localization at 100 / 500 / 1,000 m | False / false / false |
| Verifier exit | `1`, preserving unmet localization acceptance |

The [workflow run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562469268) used job `125676036022` and application job `bfe6866813b34141a2ed84d64612110a`. Generation, indexing, and browser-upload subprocesses each returned `0`.

## Executed pipeline and input scope

The run used the published fixture generator at commit `1f0342594bdc7fc7089a075b6dbf26aca9342711`, with four events and seed `20261103`. It generated the complete **960-second MP3**. The actual MP3 SHA256 is:

```text
9d96ddb1aad4156511b5549b3523bd8293d0a03625a12a21e806f5667f4f1e4c
```

This is the MP3 generated during this run. The report does not assert byte identity with a separately encoded release asset.

The index retained all **12 trajectories and 3,252 rows**, with **271 samples per trajectory**. The four type classes each contributed 813 rows: `C172`, `PC12`, `A320`, and unknown. The index excluded no jets or unknown types and clipped no trajectory geometry.

The verifier replaced every trajectory identifier with an opaque random identifier and randomized trajectory order. It retained all non-ID values and every row. The artifact preserves the original Parquet, derived Parquet, and evaluation mapping. The original Parquet SHA256 is `3c9465f1816ed71c097eda451db9c7c2f42fa317163cb406ca7fc0a7be25a258`. The derived Parquet SHA256 is `b85243afa485398e9f9aa9b8d5c62b9eb32f412c8f687bfa56a39e4b303c5fc8`.

The normal upload request contained CONUS coverage and the explicit synthetic sample-zero clock, `2026-09-21T14:13:20Z`. It contained no selected flights, event windows, frequency bands, recorder coordinates, or narrowed receiver bounds. The operator configuration supplied absolute index, terrain, and geoid paths. The flight coverage declaration described a complete finite synthetic population, not real historical receiver coverage.

The actual pipeline performed these stages:

1. Generate the complete recording and trajectories from the pinned fixture.
2. Preserve the full trajectory population and build its SQLite index.
3. Submit the MP3 through Chromium and the actual upload form.
4. Decode the recording and discover events across its full duration.
5. Search CONUS tiles, score event associations, and refine retained candidates.
6. Profile the leading candidate and produce the actual confidence decision.
7. Reload the result, inspect desktop/mobile output, and download the original upload.
8. Stop the service and workers, then load evaluation truth.

Chromium `156.0.8078.4` and Playwright `1.64.1` completed the browser checks without JavaScript errors. The mobile viewport and document widths both measured **390 px**. The browser receipt records **4,964 artifacts**. The downloaded original matched the uploaded bytes.

The verifier recorded service/worker shutdown at `2026-11-03T02:01:20.072556Z`. It recorded truth loading at `2026-11-03T02:01:20.072667Z`. The service returned `0` after SIGINT shutdown and worker joins. This establishes procedural truth separation, not operating-system isolation.

The exact command and prerequisites are in [the replay guide](../../../docs/CI_MULTIEVENT_UPLOAD_REPLAY.md). The executed command used `--events 4`, `--timeout-s 1800`, and `--expect-status inconclusive`. The expected status governs transport verification. It does not make supported localization pass.

## All four events participated

The saved discovery and result records contain these events. Their times are seconds from sample zero.

| Event | Independent group | Start | End | Ridge samples |
| --- | --- | ---: | ---: | ---: |
| `event-0001` | `harmonics-0001` | 75.0 | 240.0 | 327 |
| `event-0002` | `harmonics-0002` | 295.5 | 480.0 | 366 |
| `event-0003` | `harmonics-0003` | 518.0 | 709.5 | 380 |
| `event-0004` | `harmonics-0004` | 740.0 | 933.0 | 379 |

The leading row selected event indices `[0, 1, 2, 3]`. All four nominal diagnostics matched the exported event diagnostics. Each diagnostic recorded full trajectory support, zero outliers, and no drift-bound limit.

The leading profile contains **33 rows**. Its sources are altitude, clock, frequency, sound speed, and source frequency. The producer reported `complete=true`, `boundary_limited=false`, and no profile failures. The receipt records frequency scenarios for every selected event and both altitude-bias signs for every selected flight.

These records establish participation in the joint fit and declared profile scenarios. They do not establish a causal contribution through a leave-one-event-out experiment. The [scientific audit](scientific-audit.json) and complete artifact preserve the detailed evidence.

## Why the decision remained inconclusive

The first ambiguity trigger was retained **rank 6**, with the same correct four-flight association as the leader.

| Retained row | Normalized score | Error from synthetic reference |
| --- | ---: | ---: |
| Rank 1 | `3.956833284003326` | `0.07993058330434617 m` |
| Rank 6 | `3.8075341081656915` | `21.885529691476 m` |

The saved decision records **21.960276635521613 m** between these positions. Its normalized score gap is **0.037324793959408575 support units per group**. That gap falls within the existing `0.2` near-tie threshold. The separation exceeds the leader's returned sensitivity radius of **6.268946589875684 m**.

The decision therefore reports local spatial ambiguity around the correct association. The 1,000 m target does not expand the narrower radius returned for this candidate. The radius describes finite engineering perturbations and is not a calibrated confidence interval.

This ambiguity triggers before the later alternative-assessment gate. That gate also remains unresolved: `alternative_modes_exhaustively_assessed=false` and `alternatives_evaluated=false`. No certificate establishes complete assessment of competing spatial modes.

The [finite-search audit](finite-search-audit.md) explains the retained-score bounds and their limits. A raw discarded-score cutoff does not bound the result of unperformed continuous refinement. Multiple retained rows do not establish the number of independent physical modes.

The earlier two-event outcome remains in its [separate preserved evidence](https://github.com/1337isnot1337/DOPPLERGEIST/blob/48955d9e665fe61bb5cf2234c73b145917158082/evidence/verification/ci-automatic-20261103/README.md). That run had a distant incorrect leader and a lower-ranked correct association. Different scenes and source versions prevent a causal comparison between these outcomes.

## Every retained outcome at the three distance thresholds

The receipt retains all **105 candidate records**. Of these, **53 contain all four groups** and **52 contain three groups**. All 105 records use correct event-to-flight assignments for the events they select.

The comparison uses inclusive `error <= threshold`. The leading point also satisfies the separately recorded strict `error < 100 m` comparison.

| Threshold | All candidate records within threshold | Records with the complete correct four-flight set | Leading point within threshold | Supported localization |
| --- | ---: | ---: | --- | --- |
| 100 m | 20 | 8 | Yes | No |
| 500 m | 105 | 53 | Yes | No |
| 1,000 m | 105 | 53 | Yes | No |

These are correlated hypotheses from **one synthetic scene**, including different positions and event subsets. They are not independent trials, recordings, or estimates of an accuracy rate. All candidate errors and associations remain in [acceptance.json](acceptance.json).

## Search work, runtime, and memory

The search completed **4,940 / 4,940 tiles**, with no tile or refinement failures. It reported **28,672 coarse points**, **1,681 fine points**, and **15,129 duplicate fine points skipped**. The coarse counter includes scored nodes in tiles with queried tracks, not every geometrical node across CONUS.

The report marks declared data coverage and all four event groups complete. It leaves alternative-mode completeness false. The complete synthetic population does not establish complete real aircraft coverage.

| Measured stage | Return code | Elapsed time | Peak sampled process-tree RSS |
| --- | ---: | ---: | ---: |
| Generation | 0 | 7.021792 s | 503.703125 MiB |
| Indexing | 0 | 1.804846 s | 273.558594 MiB |
| Browser upload and pipeline | 0 | 328.750446 s | 1,385.835938 MiB |

The replay took **337.896906 seconds** against its **1,800-second budget**. The workflow timeout was 45 minutes, with 33 minutes allocated to the upload step. Installation and repository tests are outside the replay duration.

The sampler inspected the process tree every **0.2 seconds**, including children created by nonleader threads. It can miss transient peaks and count shared pages more than once. The browser-stage measurement includes browser and service processes. It is not unique physical memory consumption.

The search process separately reported **450.144531 MiB** peak RSS and **277.132269 seconds**. That process measurement covers a different scope from the browser process-tree measurement. The [acceptance receipt](acceptance.json) preserves the exact byte counts and measurement descriptions.

## Source and test gates

The actual workflow recorded this frozen source:

| Identity | Value |
| --- | --- |
| Integration commit | `e2bb3dce63591ff7c92a0f985b40dd6a01a24cec` |
| Integration tree | `4db8aec1e8fc0f3b41b18e9d43a9ab07f608247f` |
| Base main commit | `63d620f390196e81eb669ca5c4ec483dddc4f163` |
| Wrapper blob | `47c22391784c3da7565a99afd3c4d958c0d7f7fb` |
| Wrapper control blob | `73906ec46693153cc1084c472e1764c6072ebde3` |
| Automatic adapter blob | `acc6add579f57c97e62b8a913ac25fa8fe293404` |
| Tiled-search blob | `96d9a919c25e9ba254486f9c92268a0f63715c92` |

The [source manifest](source-manifest.json) records every direct copy, preserved base file, and composed file. W5 source comes from `a0dd8403f304f28ff581dfb87fabf5734f8fd152`, with only the published PR52 profile-authority block applied. That composition preserves the normalization guard, original clock window, unmatched-event diagnostics, and acquisition bounds.

W2 source combines PR57 `50c01271fc4edc0c4743959b442234a9da46e570` with the published refinement-grid union change. Their exact common ancestor is `3ea3406ae827a26b193202fb7f737714438af506`. The runtime merge was conflict-free. The test merge retained both complete appended test blocks. [Composition records and patches](composition/) preserve these derivations.

Package installation, Chromium installation, and `pip check` passed on CPython **3.12.15**. The integrated suite passed **267 tests and 25 subtests in 64.63 seconds**, with no skipped or deselected tests. All 14 job evidence checks passed. The evidence collector reported no errors.

The focused harness [PR69 test run](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562629812) also passed:

| Python | Tests | Subtests | Runtime | Warnings | Skips |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.11.17 | 220 | 17 | 16.86 s | 7 | 0 |
| 3.14.9 | 220 | 17 | 19.76 s | 1 | 0 |

Both CLI smoke checks passed. Both jobs used merge commit `f36e3434589a6f4e0d52ed417c8b5a3ded639f8e`. Its tree `c1170b830d8a0b7ba061d71eea4a41585ee7052f` equals the original focused PR head tree. These are harness-control results on main, separate from the numerical integration run.

## Full local Git clone

The [local clone receipt](local-clone.json) records a complete, non-shallow Git clone at `DOPPLERGEIST-verified`. Its clean checkout matches the integration commit and tree above. It contains **738 tracked files**, **262 commits across restored references**, and **62 exported references**.

All exported references matched their recorded values. `git fsck` and `git bundle verify` passed. The [separate export workflow](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562941485) transferred Git objects and references without checkout authentication configuration. This clone supplements the preserved execution artifact and implementation snapshot.

## Preserved artifact and limits

The selected native reports, environment files, and screenshots match the extracted artifact byte for byte.

| Native evidence | Copies in this directory |
| --- | --- |
| Complete outcome | [Acceptance receipt](acceptance.json), [product verifier report](product-verifier-report.json) |
| Actual producer output | [Decision](job/decision.json), [result](job/result.json) |
| Search and refinement | [Search report](job/search-report.json), [refined candidates](job/refined-candidates.json) |
| Browser output | [Browser receipt](browser/browser.json), [desktop PNG](browser/page.png), [mobile PNG](browser/page-mobile.png) |
| Inputs and shutdown | [Index report](indexing.json), [service lifecycle](service-lifecycle.json) |
| Test evidence | [Pytest log](environment/pytest.log), [JUnit result](environment/pytest.xml) |

The [complete workflow artifact](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562469268/artifacts/13197212672) contains **82,031,174 bytes**. Its SHA256 is:

```text
4b48add76c813441cd6578bf5b677bf9f8e5581152d3a1ca80d762389d1ef2fa
```

| Artifact path | Evidence |
| --- | --- |
| `ci-upload/acceptance.json` | Complete outcome, candidate errors, event participation, and provenance |
| `ci-upload/indexing.json` | Complete trajectory preservation and index report |
| `ci-upload/product/browser/` | Browser receipt, screenshots, trace, and downloaded original |
| `ci-upload/product/http-jobs/bfe6866813b34141a2ed84d64612110a/` | Actual request, original MP3, discovery, search, refinement, decision, and result |
| `ci-upload/evaluation/` | Original Parquet, opaque-ID mapping, generator record, and evaluation truth |
| `ci-upload/implementation/` | Exact implementation snapshot and file hashes |
| `ci-upload-environment/` | Source identity, dependencies, pytest log, and JUnit result |

This is one synthetic development scene with an exact supplied clock and synthetic terrain/geoid data. The run used a prepared complete synthetic flight index. It did not establish live historical-data acquisition, real receiver coverage, independent real-recording accuracy, or calibrated confidence.

The small leading-candidate error remains a diagnostic result. The actual supported-location outcome remains false, and the preserved inconclusive decision remains authoritative.
