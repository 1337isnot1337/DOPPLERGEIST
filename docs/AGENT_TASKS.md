# Agent swarm task plan

The goal is a real MP3-upload-to-location workflow with automatic Doppler-event
discovery. **Up to 1 km location error is acceptable; 100–500 m or better is
preferred** on supported, independently evaluated real recordings. Use every
supported independent flyover, including three, four or more, under one shared
clock/location; there is no default two- or three-event cap. Every issue includes a concrete objective,
suggested file ownership, dependencies and acceptance checks.

**Default agent communication:** [discussion board #39](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39).
Use threaded conversations for dependencies, design decisions, blockers and handoffs;
read and respond at the checkpoints in `AGENTS.md`.
**Task index and completion tracking:** [issue #1](https://github.com/1337isnot1337/DOPPLERGEIST/issues/1).
Workers are deployed by the user and claim work when launched. The primary and
other workers must not launch subagents themselves; create concrete issues for
new workstreams instead.

## Launch order

1. Start the integration lead on **DG-01** and the evaluation agent on **DG-02**.
   Other agents can inspect code/data and reproduce relevant evidence immediately.
2. Once the minimal contracts are settled, start **DG-03, DG-05 and DG-11**.
   The matching agent can start **DG-07** once contracts and evaluation fixtures
   exist. The product agent can prepare the API skeleton using the shared contract.
3. Continue audio work into **DG-04**, data work into **DG-06**, and matching work
   through integration with automatically detected events. Keep service integration
   moving as those interfaces become real.
4. Complete **DG-08** against the combined search/matching output. Finish **DG-09**
   and **DG-10** against the real backend, then **DG-12** from a clean checkout.

Dependencies are integration gates, not an instruction to spend days idle. Work
on fixtures, adapters, diagnostics and reproducible baseline checks while waiting.
Do not close a task using mocked outputs or a proposed design alone.

## Five swarm workers plus the primary integration agent

| Agent role | Task sequence | Responsibility |
| --- | --- | --- |
| Worker 1: Audio | [DG-03 / #4](https://github.com/1337isnot1337/DOPPLERGEIST/issues/4) → [DG-04 / #5](https://github.com/1337isnot1337/DOPPLERGEIST/issues/5) | Intake, automatic event discovery and harmonic grouping |
| Worker 2: Data and scale | [DG-05 / #6](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6) → [DG-06 / #7](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7) | Cached/indexed inputs and bounded-memory national search |
| Worker 3: Matching | [DG-07 / #8](https://github.com/1337isnot1337/DOPPLERGEIST/issues/8) | Event-to-flight association and physical refinement |
| Worker 4: Evaluation and confidence | [DG-02 / #3](https://github.com/1337isnot1337/DOPPLERGEIST/issues/3) → [DG-08 / #9](https://github.com/1337isnot1337/DOPPLERGEIST/issues/9) | Independent benchmarks, ambiguity and abstention |
| Worker 5: Product | [DG-09 / #10](https://github.com/1337isnot1337/DOPPLERGEIST/issues/10) → [DG-10 / #11](https://github.com/1337isnot1337/DOPPLERGEIST/issues/11) | Actual orchestration/API and upload UI |
| Primary integration agent | [DG-01 / #2](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-11 / #12](https://github.com/1337isnot1337/DOPPLERGEIST/issues/12), [DG-12 / #13](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) | Shared contracts, packaging/CI and final integration |

The user is launching five workers. This allocation supersedes the earlier
seven-role suggestion. Do not have several agents independently rewrite
`audio.py`, `search.py` or `pipeline.py`.

## Additional workstreams for user-deployed workers

| Priority / role | Task | Boundary and deliverable |
| --- | --- | --- |
| **Highest: independent field-data acquisition** | [#53](https://github.com/1337isnot1337/DOPPLERGEIST/issues/53) | Obtain a documented multi-device/environment corpus with independent GPS and sample-zero UTC, plus a sealed holdout. Separate from W4's evaluator. Requires actual collection or an eligible independently documented source; tooling alone does not complete it. |
| **High: end-to-end invariance verification** | [#61](https://github.com/1337isnot1337/DOPPLERGEIST/issues/61) | Replay evidence-preserving bitrate/rate/gain/channel/silence/chunk variants through the complete system. Predeclare consistency tolerances; retain all outcomes and flag accepted distant jumps. Separate from codec unit checks and destructive stress testing. |
| **High: independent historical-track audit** | [#62](https://github.com/1337isnot1337/DOPPLERGEIST/issues/62) | Compare genuinely independent ADS-B archives, then source-swap frozen localization replays. Report time/position/altitude/gap discrepancies and the resulting error budget; separate from W2 ingestion. |
| **Medium: actionable inconclusive guidance** | [#63](https://github.com/1337isnot1337/DOPPLERGEIST/issues/63) | Derive concise next steps from actual competing modes, clock, acoustic evidence, coverage and work limits. Coordinate additive product/decision contracts with W5/W4; guidance cannot change acceptance. |
| Atmospheric propagation audit | [#49](https://github.com/1337isnot1337/DOPPLERGEIST/issues/49) | Frozen-model falsification with independent wind/temperature/refraction fixtures and a measured error budget. No production changes or reference-case tuning. |
| Recording robustness audit | [#54](https://github.com/1337isnot1337/DOPPLERGEIST/issues/54) | Measure effects of phone processing, compression, microphone wind noise, reverberation, motion and rate changes. Report failure ranges before proposing correction models. |

These are task assignments, not worker launches. The primary-launched atmospheric
worker was stopped at the user's request; #49 is available for a user-deployed
owner. Coordinate these workstreams on discussion board #39. Preserve every
case and distinguish measured location error from model sensitivity and actual
acceptance/abstention. Report outcomes at 100, 500 and 1,000 m.

## Ready-to-copy assignment prompt

Replace the task/role placeholders with one row above:

```text
Work in https://github.com/1337isnot1337/DOPPLERGEIST as the <ROLE> agent.
Implement <TASK ISSUE URL>, followed by its next task only when dependencies allow.
Read AGENTS.md, docs/AGENT_TASKS.md, docs/HANDOFF.md and the issue before editing.
Claim the issue with your agent identity, branch/worktree and owned files.
Use a separate branch/worktree and preserve existing changes and frozen evidence.
Do not launch subagents; record additional tasks as issues for user deployment.
Use discussion board #39 as the default way to communicate with other workers.
Read it at least every 10 minutes; reply to questions directed to your role.
Discuss shared interfaces and conflicting ownership before changing them.
Post findings, failures, dependencies and blockers promptly; link relevant issues/PRs.
Implement the task, run meaningful verification, and open a focused linked PR.
Report exact commands, commit, artifacts, measured results and unresolved limits.
The product must discover Doppler events automatically from uploaded audio.
A defensible recording date/time window may be supplied; manual event windows,
frequency bands, known flight IDs and ground-truth locations are not normal inputs.
Up to 1 km error is acceptable; aim for 100–500 m or better and report all three
thresholds (100/500/1,000 m). Use all supported independent flyovers, including
3, 4 or more; harmonics/fragments count once and false proposals can stay unmatched.
Bound computational work explicitly instead of silently limiting matched events.
Do not claim national real-audio accuracy from regional-only, synthetic-only,
mocked, selected, or ground-truth-assisted evidence.
Do not upload the YouTube MP4. Do not overwrite historical experiment outputs.
```

## Issue index

| Work package | Integration prerequisites |
| --- | --- |
| [DG-01: Define pipeline contracts and compatibility rules](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2) | Ready now |
| [DG-02: Build a truth-separated benchmark corpus and evaluation runner](https://github.com/1337isnot1337/DOPPLERGEIST/issues/3) | Ready now |
| [DG-03: Implement whole-recording audio intake and trustworthy time metadata](https://github.com/1337isnot1337/DOPPLERGEIST/issues/4) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2) |
| [DG-04: Discover and trace Doppler events automatically across an entire recording](https://github.com/1337isnot1337/DOPPLERGEIST/issues/5) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-03](https://github.com/1337isnot1337/DOPPLERGEIST/issues/4) |
| [DG-05: Automate historical flight and terrain acquisition with reusable indexes](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2) |
| [DG-06: Add bounded-memory national search and deterministic candidate merging](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-05](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6) |
| [DG-07: Improve event-to-flight association and uncertainty-aware localization](https://github.com/1337isnot1337/DOPPLERGEIST/issues/8) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-02](https://github.com/1337isnot1337/DOPPLERGEIST/issues/3) |
| [DG-08: Add ambiguity, uncertainty and explicit inconclusive outcomes](https://github.com/1337isnot1337/DOPPLERGEIST/issues/9) | [DG-02](https://github.com/1337isnot1337/DOPPLERGEIST/issues/3), [DG-06](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7), [DG-07](https://github.com/1337isnot1337/DOPPLERGEIST/issues/8) |
| [DG-09: Connect automatic detection, data retrieval and search through CLI and job API](https://github.com/1337isnot1337/DOPPLERGEIST/issues/10) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-03](https://github.com/1337isnot1337/DOPPLERGEIST/issues/4), [DG-04](https://github.com/1337isnot1337/DOPPLERGEIST/issues/5), [DG-05](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6), [DG-06](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7), [DG-07](https://github.com/1337isnot1337/DOPPLERGEIST/issues/8), [DG-08](https://github.com/1337isnot1337/DOPPLERGEIST/issues/9) |
| [DG-10: Build the MP3 upload interface and inspectable results](https://github.com/1337isnot1337/DOPPLERGEIST/issues/11) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-09](https://github.com/1337isnot1337/DOPPLERGEIST/issues/10) |
| [DG-11: Provide reproducible installation, lightweight CI and artifact restoration](https://github.com/1337isnot1337/DOPPLERGEIST/issues/12) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2) |
| [DG-12: Integrate the swarm and prove the complete upload-to-location workflow](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2), [DG-02](https://github.com/1337isnot1337/DOPPLERGEIST/issues/3), [DG-03](https://github.com/1337isnot1337/DOPPLERGEIST/issues/4), [DG-04](https://github.com/1337isnot1337/DOPPLERGEIST/issues/5), [DG-05](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6), [DG-06](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7), [DG-07](https://github.com/1337isnot1337/DOPPLERGEIST/issues/8), [DG-08](https://github.com/1337isnot1337/DOPPLERGEIST/issues/9), [DG-09](https://github.com/1337isnot1337/DOPPLERGEIST/issues/10), [DG-10](https://github.com/1337isnot1337/DOPPLERGEIST/issues/11), [DG-11](https://github.com/1337isnot1337/DOPPLERGEIST/issues/12) |

## Shared interfaces and ownership

DG-01 publishes the request/event/result contracts before other agents finalize
them. Times must distinguish absolute UTC from audio-relative seconds, and all
distances, speeds and frequencies must carry explicit units. Evaluation-only
truth stays outside search inputs.

DG-04 owns event discovery; DG-07 owns scoring/association internals; DG-06 owns the
outer national-search driver; DG-09 owns orchestration and the API; DG-10 consumes
the API. DG-11 coordinates shared dependency and CI changes. The issue bodies
specify where existing files overlap and require coordination.

Each PR must include its issue, changed behavior, meaningful validation, exact
artifact paths and unresolved failures. A failed experiment is useful evidence;
preserve it with a clear label. Use new output directories and record code/input
hashes. Existing results live in Git under `evidence/` and in the checkpoint
release; do not quietly regenerate them in place.

## Completion evidence

The final report must exercise an actual MP3 upload through the real automatic
pipeline and show detection, acquisition, association, search, decision and result
display. Evaluate held-out real cases and the declared national coverage, with
ground truth inaccessible to search. Report every case, including misses and
inconclusive outcomes, reference-coordinate/time uncertainty, runtime and memory.

The existing 43.86 m regional reference result is a useful baseline. It does not
complete automatic discovery or nationwide validation. The faint-event result is
357.47 m off and remains an explicit development failure. See
[PROGRESS.md](PROGRESS.md) for all qualifications.

