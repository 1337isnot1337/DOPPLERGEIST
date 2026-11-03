# Finite-search audit of the frozen four-event upload

Recorded on 2026-11-03 at 01:54:18 UTC, before this auditor observed any numerical outcome from [run 41562469268](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41562469268).

**This is an audit of existing code. It changes no producer, policy, threshold, expected status, or acceptance criterion.** The run remains frozen at commit `e2bb3dce63591ff7c92a0f985b40dd6a01a24cec`, tree `4db8aec1e8fc0f3b41b18e9d43a9ab07f608247f`. Its four-event outcome is not inferred here.

## Source identity

The GitHub tree response was complete, with `truncated=false`. These are the actual blobs in the frozen tree.

| Module | Git blob | Relevant functions and lines |
| --- | --- | --- |
| [tiled_search.py](https://github.com/1337isnot1337/DOPPLERGEIST/blob/e2bb3dce63591ff7c92a0f985b40dd6a01a24cec/src/aircraft_geoloc/tiled_search.py) | `96d9a919c25e9ba254486f9c92268a0f63715c92` | `_key` / `merge_candidates`, 48–63; `_score`, 123–189; `search_national`, 192–353 |
| [automatic.py](https://github.com/1337isnot1337/DOPPLERGEIST/blob/e2bb3dce63591ff7c92a0f985b40dd6a01a24cec/src/aircraft_geoloc/automatic.py) | `acc6add579f57c97e62b8a913ac25fa8fe293404` | `_search`, 93–142; `_coverage`, 145–160; `_comparable_refinement`, 163–172; `_decide`, 175–286 |
| [matching.py](https://github.com/1337isnot1337/DOPPLERGEIST/blob/e2bb3dce63591ff7c92a0f985b40dd6a01a24cec/src/aircraft_geoloc/matching.py) | `3f958983651fa85cb8143aed48ce70f21dc8264f` | `association_candidates`, 69–157; `association_score`, 160–172; `fit_ridge`, 231–276; `refine_candidate`, 295–370; `profile_candidate`, 373–476 |
| [search.py](https://github.com/1337isnot1337/DOPPLERGEIST/blob/e2bb3dce63591ff7c92a0f985b40dd6a01a24cec/src/aircraft_geoloc/search.py) | `0fb3e83125d0154b29127d4270b11cafdddcb711` | `score_candidate`, 217–277 |
| [confidence.py](https://github.com/1337isnot1337/DOPPLERGEIST/blob/e2bb3dce63591ff7c92a0f985b40dd6a01a24cec/src/aircraft_geoloc/confidence.py) | `92a5938fcefb1a88d60d863f5dfaa093180ef736` | `DecisionPolicy`, 16–35; alternative comparison and assessment gate, 158–181; sensitivity gates, 182–207 |
| [ci_upload_replay.py](https://github.com/1337isnot1337/DOPPLERGEIST/blob/e2bb3dce63591ff7c92a0f985b40dd6a01a24cec/scripts/ci_upload_replay.py) | `47c22391784c3da7565a99afd3c4d958c0d7f7fb` | Frozen transport, input-isolation, post-termination truth join, and participation checks |

The tiled driver combines published W2 all-event source from `50c01271fc4edc0c4743959b442234a9da46e570` with main's refinement-grid union fix from `0ec20b906ab47d58187bc68136b20e5e2049e13c`. The automatic adapter combines W5 `a0dd8403f304f28ff581dfb87fabf5734f8fd152` with the profile-authority block from PR52, `de6c9ae2dd18481d1238121acd52be294057fb14`. Independent static comparison found only those intended changes. No numerical sweep was executed for this audit.

## What completed search work establishes

The search manifest binds the source and input hashes, acoustic measurements, receiver bounds, projection, grid spacing, clock settings, filters, and budgets. The driver visits the coarse grid tiles and evaluates the union of selected fine-grid rectangles. Its complete status requires all coarse tiles, no tile or refinement failure, sufficient declared input coverage, and no limiting event cap. Association-budget exhaustion remains a visible failure. See `search_national` and `association_candidates` above.

This is a finite computational scope. It uses the supplied flight population and the declared CPA sampling, event filters, slant range, and clock samples. `score_candidate` tests a finite set of shared-clock values; it does not give each event its own clock. Continuous local refinement is a later operation.

`grid_points_searched` counts evaluated coarse nodes in tiles with queried tracks. A visited tile with no tracks contributes no scored nodes. It is therefore incorrect to describe that counter as the size of every geometrical receiver node across the requested area. A completed tile traversal also does not prove that an archive captured every real aircraft.

The fine-grid union fix records searched and duplicate-skipped point counts. It prevents repeated scoring of overlapping requested refinement cells. It does not make the selected refinement rectangles cover all possible spatial modes.

## What retention evidence is available

Each coarse tile retains a payload with CPA and association counts, ranked candidates, grid-point count, track count, and hashes. The counts include per-event survivors, hypotheses examined, work units, and generated candidates. They do not separately count clock-rejected, nonfinite-scored, finite-scored, duplicate, and discarded rows. Fine-stage `_score` counts are not retained in the final report.

`merge_candidates` sorts finite scores and keeps the largest `top_k` distinct keys. Conditional on complete evaluation of the declared raw candidate set, the retained kth score is an upper bound on the scores of discarded distinct raw rows. Applying the same rule per tile and globally preserves this property. If fewer than `top_k` distinct finite rows remain globally, this truncation has not omitted another distinct finite row from that evaluated set.

That bound concerns the scored rows returned to `merge_candidates`. `score_candidate` first reduces its clock samples to one best clock per location/association, so the bound is not a certificate that every competing clock solution was retained. It is also **not** an upper bound on what a discarded seed could achieve after continuous refinement. Nor do retained-row counts identify how many physical modes exist. The frozen driver accordingly sets `alternative_modes_exhaustively_assessed` to false; the automatic adapter does not override it.

## Observed reason to distinguish raw and refined rankings

The earlier, separate two-event run [41557059642](https://github.com/1337isnot1337/DOPPLERGEIST/actions/runs/41557059642), at `db9e5bd1233c7eb518571ebcc7b2be2a28e9c567`, actually reordered associations between its saved grid-search output and final refinement output:

| Association identified after execution | Grid-search score / rank | Final score / first rank |
| --- | --- | --- |
| Correct flight pair | `-0.24252868892896837` / 1 | `-0.17373829502931443` / 4 |
| Distant decoy pair | `-0.42706391882847883` / 4 | `-0.17275185711088512` / 1 |

The final leading point had horizontal error `1046023.7708583066` m; the highest-ranked correct-pair point had error `5.5421237626251205` m. The actual decision was inconclusive with reason `ambiguous_flight_match`. The [preserved stage summaries](https://github.com/1337isnot1337/DOPPLERGEIST/blob/48955d9e665fe61bb5cf2234c73b145917158082/evidence/verification/ci-automatic-20261103/stage-summaries.json), [observed metadata](https://github.com/1337isnot1337/DOPPLERGEIST/blob/48955d9e665fe61bb5cf2234c73b145917158082/evidence/verification/ci-automatic-20261103/observed.json), and original run logs support these values.

Both associations were retained in that run. This example demonstrates a ranking reversal; it does not demonstrate that a discarded candidate won. It also does not predict the current four-event outcome. The historical run used negative robust-loss scores, while the current subset path uses normalized group support. No causal improvement or cross-version score comparison is claimed.

## Distinct spatial modes are not fully counted

The tiled driver's final candidate key includes event indices, flight IDs, pass times, coordinates, and recording start. Its fine-refinement selection key is narrower: flight IDs and rounded pass times. The latter omits both receiver position and event indices.

The automatic adapter's `approach` key adds selected event indices, but still omits receiver position and recording-clock basin. It refines one encountered row per such key, subject to its finalist budget. Two distant seeds with the same association and approach times can therefore share a selection key. A count of these keys cannot establish that every distinct spatial mode was refined. This is a source-level limitation, not a claim that a particular mode was lost in the pending run.

## Conditional support bound under the exact W4 formula

For the current physical scorer, each robust loss is nonnegative: `fit_ridge` returns the negative square root of a nonnegative residual loss plus drift penalty. `association_score` converts a supported group to `1 - loss / (3 * frequency_scale)`. A valid hypothesis with `m` matched independent groups consequently has normalized score at most `m`. Harmonic ridges do not increase the independent-group count.

Let the leading candidate have score `S_b` and `n` matched groups. W4 compares an alternative of score `S_a` and `m` groups using:

`gap = (S_b - S_a) / max(n, m)`

For normalized subset scores, the declared near-tie threshold is `0.2`. A near tie is disqualifying when its position lies outside the returned ambiguity radius **or** its event-to-flight association differs. The ambiguity radius is the smaller of the policy target and the leading candidate's returned radius, when present; otherwise it is the policy target. The comparison uses `gap <= 0.2`; equality remains a near tie. These are existing rules in `confidence.py`, lines 163–180.

The score ceiling alone excludes an `m`-group alternative from this near-tie condition only if:

`S_b > m + 0.2 * max(n, m)`

Thus a four-group leader with score strictly greater than `3.8` excludes alternatives with at most three groups through this bound. It cannot exclude unrefined four-group alternatives: the corresponding sufficient condition would be `S_b > 4.8`, while the four-group score ceiling is `4`. This deduction assumes the frozen physical score construction and correctly counted independent groups. It is not a new acceptance threshold, evidence that all four-group modes were assessed, or proof that any other decision gate passes.

## Minimum scope for a future finite-search evidence contract

A future certificate should name its finite receiver, clock, and association universe and retain a ledger of evaluated, rejected, duplicate, retained, and omitted hypotheses. Omitted-score bounds need declared units and group cardinalities. Refinement coverage needs seed identities, spatial locations, clock intervals, outcomes, failures, and boundary flags. A raw-score cutoff cannot certify unseen refinement gains without a valid gain bound or actual evaluation of all relevant declared seeds.

The adapter profiles the then-leading row, replaces that exact hypothesis, and reranks. The full profile stays attached to the hypothesis that produced it. If another mode becomes the final leader, that mode must satisfy its own full sensitivity gate; it cannot borrow the previous leader's profile. The wrapper reads the actual final leader. Profile settings, selected event indices, frequency scenarios, per-flight altitude scenarios, clock endpoints, sound-speed scenarios, optimizer outcomes, failures, and boundary flags remain inspectable. Scenario presence alone does not establish optimizer success. Profiling one leader does not assess all competing basins. The radius describes finite engineering perturbations and is not a calibrated confidence region.

The smallest supported statement from the frozen architecture is that its declared search work completed, if the receipt establishes that fact, and that its retained and explicitly refined hypotheses were compared. Alternative-mode completeness remains unestablished. Any later finite-grid contract must retain that declared scope and must not imply continuum exhaustiveness, probabilistic calibration, complete real traffic, or independent real-recording accuracy.

## Fixed interpretation of the pending four-event run

Transport/UI success, leading-point error, and supported localization remain separate outcomes. The frozen wrapper checks the leading point at 100, 500, and 1,000 m, with the older strict-below-100 m readout also retained. It joins truth only after producer termination. It requires all four true flyovers, valid used groups and temporal correspondence, the exact supplied recording clock, bound internal/public candidate identity, and nominal diagnostics for the selected groups. Profile participation remains descriptive evidence under the pinned implementation, not an empirical leave-one-out experiment.

The workflow's expected inconclusive status can satisfy the transport check. It cannot make supported localization pass. The actual producer decision, all provenance and coverage checks, and the unchanged scientific gates still govern that outcome. This remains one synthetic development scene with a known clock; the independently timed real-field corpus and sealed holdout requested in [issue 53](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53) are separate requirements.
