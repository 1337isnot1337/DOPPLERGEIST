# Automatic synthetic CI evidence, 2026-11-03

The complete automatic computational pipeline ran. This recording did **not** pass localization acceptance. Its actual result was **inconclusive / ambiguous_flight_match**.

## Source and execution

Detailed evidence comes from [run 41557059642](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41557059642), [job 125658395623](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41557059642/job/125658395623), at commit db9e5bd1233c7eb518571ebcc7b2be2a28e9c567. The [integration manifest](https://github.com/1337isnot1337/DOPPLERGEIST/blob/db9e5bd1233c7eb518571ebcc7b2be2a28e9c567/evidence/ci-automatic-integration.json) pins every producer input.

A clean, full-history checkout used Python 3.12.15 and passed dependency checks. Repository tests reported **139 passed and eight subtests passed in 30.93 seconds**, with one pandas warning. Preflight, independent generation, indexing, MP3 encoding, and the actual CLI all returned zero. The harness returned one because scientific acceptance failed, without a recorded harness exception.

The actual command was:

```bash
python scripts/ci_automatic_replay.py --output results/ci-automatic --timeout-s 1800
```

## Observed execution

| Check | Result |
| --- | --- |
| Complete recording | 1,180 seconds, encoded to MP3 |
| Trajectories and samples | All seven; 1,617 samples |
| Aircraft classes | Six C172 tracks and one A320 track retained |
| Index | Version 2; seven segments |
| Discovery | Two events and two independent harmonic groups |
| Search tiles | 4,940 / 4,940; zero failures or unsearched tiles |
| Scored grid points | 26,624 |
| Final candidate records | 106, including raw/refined/profile duplicates |
| Provenance and stage checks | All eight passed |
| Search / CLI / total time | 144.223 / 157.210 / 164.402 seconds |

The normal request supplied audio, CONUS scope, and the generator clock. It supplied no selected events, frequency bands, flight IDs, or receiver coordinates. Every trajectory sample remained. Evaluation truth was opened after clean CLI termination. Separation is procedural; generator source and evaluation files were not OS-isolated.

Runtime provenance checked 18 top-level modules. The broader Git-tree comparison also included the nested web initializer.

## Ranking and decision

Errors are post-analysis horizontal WGS84 geodesic distances.

| Rank | Error, m | Correct flight pair | Final score |
| --- | ---: | --- | ---: |
| 1 | 1,046,023.7708583066 | No | -0.17275185711088512 |
| 2 | 1,046,023.7708583066 | No; duplicate association and position | -0.17275185711088512 |
| 3 | 1,046,023.7708583066 | No; different association | -0.17275185711088512 |
| 4 | 5.5421237626251205 | Yes | -0.17373829502931443 |
| 5 | 1,052,003.4293853391 | No | -0.18599611423334134 |

The decision records a competing flight association with zero spatial separation and zero score gap. The leading distant mode also exceeds the correct-pair score by only 0.0004932 per event, inside the policy's 0.5-per-event near-tie threshold. Scores are not probabilities.

Four retained records are within 100 m, at ranks 4, 7, 12, and 21. These are alternatives for one recording, which produced **zero accepted localizations**. The correct mode was retained; numerical refinement changed the final ranking.

The leading candidate's full sensitivity profile contained 17 records across five sources. It reported complete, no boundary limitation, no failures, and **115.0019628501904 m** radius. The correct rank-four candidate had only an ordinary relative-altitude profile in the printed evidence, with **109.828522293865 m** radius. Its nominal 5.5421 m error does not establish supported sub-100 m uncertainty.

Search explicitly reported alternative_modes_exhaustively_assessed=false; matching reported alternatives_evaluated=false. Complete tile traversal does not change those declarations.

Discovery retained 62 ridge points over 144–179.5 s and 122 over 1039.5–1111 s. Each harmonic group had one retained member. Short cores and near-tied fits are consistent with insufficient discriminating information, but no rejected-path audit or acoustic-context counterfactual was performed. Discarded weak wings remain a hypothesis, not an established cause.

## Repeat identity and retained evidence

The earlier [run 41556154751](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41556154751), at commit 068c84c1d77cd44199443a4b1d40dce23f8022b9, also reported inconclusive. Only its short summary was inspected; its detailed candidate errors are not inferred here.

All **50 Python files** were identical between runs: 19 package files, 11 scripts, and 20 tests. Only workflow evidence printing changed. Each invocation generated fresh opaque flight IDs and track order, changing trajectory and index hashes. These are repeated executions of the same fixture definition, not independent accuracy cases or byte-identical input replays.

- acceptance.json is transcribed from the workflow's verbatim marked output.
- stage-summaries.json contains bounded logged summaries, not complete original stage files.
- observed.json records source, test, execution, and artifact metadata.
- first-run-observed.json retains the limited first-run observations.

[Artifact 13195232875](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41557059642/artifacts/13195232875) contains 20,589,616 bytes and expires on 2026-12-03. GitHub reports SHA-256:

```text
46258648e88015251de0223c9becfd6c60cda68e01e196342e35945eeb5b050a
```

The ZIP was not independently rehashed locally. The committed records preserve inspected findings beyond artifact expiry.

## Resource and scientific limits

Search self-reported a **372.47265625 MiB** RSS high-water mark at search completion. The wrapper recorded only 20,807,680 bytes. Its original sampler inspected main-thread children only and could miss workers launched by another thread. That wrapper value does not establish whole-worker or whole-job peak memory. Historical fields remain unchanged.

Coverage applies to the declared seven-track simulation. This run does not establish independent real microphone coordinates or recording-clock accuracy, real altitude-datum accuracy, live acquisition, real nationwide completeness, or HTTP/browser acceptance. No scoring rule or acceptance threshold was changed using evaluation truth.

## Threshold context

This report preserves the run's original strict 100 m acceptance criterion. [Project instructions at af05dad5](https://github.com/1337isnot1337/DOPPLERGEIST/blob/af05dad5e762235da29284ac83551c5bb36c72c3/AGENTS.md) now specify up to 1,000 m acceptable, with 100–500 m preferred. The following post-run distance readout does not recompute the decision or change the historical receipt.

| Distance threshold | Leading candidate within threshold | Retained correct-pair records within threshold | Recorded supported localizations |
| --- | --- | ---: | ---: |
| 100 m | No | 4 | 0 |
| 500 m | No | 26 | 0 |
| 1000 m | No | 26 | 0 |

The retained-record counts are diagnostic alternatives for one recording. They are not successful independent trials. The leading candidate fails all three distance thresholds.
