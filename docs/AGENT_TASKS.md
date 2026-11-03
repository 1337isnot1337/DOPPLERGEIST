# Agent swarm task plan

The goal is a real MP3-upload-to-location workflow with automatic Doppler-event
discovery. Approximately **100 m location error** counts as success on supported,
independently evaluated real recordings. Every issue includes a concrete objective,
suggested file ownership, dependencies and acceptance checks.

**Coordination and completion tracking:** [issue #1](https://github.com/1337isnot1337/DOPPLERGEIST/issues/1).
These are unassigned work packages; agents should claim them when deployed. No
additional agents have been launched by this planning step.

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

## Suggested seven-agent deployment

| Agent role | Task sequence | Responsibility |
| --- | --- | --- |
| Integration lead | [DG-01](https://github.com/1337isnot1337/DOPPLERGEIST/issues/2) → [DG-12](https://github.com/1337isnot1337/DOPPLERGEIST/issues/13) | Own shared contracts first, coordinate PR order, then run final acceptance. |
| Evaluation and confidence | [DG-02](https://github.com/1337isnot1337/DOPPLERGEIST/issues/3) → [DG-08](https://github.com/1337isnot1337/DOPPLERGEIST/issues/9) | Build fixtures/independent truth first; validate abstention and false matches after matching/search are available. |
| Audio | [DG-03](https://github.com/1337isnot1337/DOPPLERGEIST/issues/4) → [DG-04](https://github.com/1337isnot1337/DOPPLERGEIST/issues/5) | Implement intake, then full-recording event discovery and harmonic grouping. |
| Data and scale | [DG-05](https://github.com/1337isnot1337/DOPPLERGEIST/issues/6) → [DG-06](https://github.com/1337isnot1337/DOPPLERGEIST/issues/7) | Provide cached/indexed inputs, then bounded-memory national search. |
| Matching | [DG-07](https://github.com/1337isnot1337/DOPPLERGEIST/issues/8) | Improve uncertain event-to-flight association and physical refinement; preserve locked clocks. |
| Product | [DG-09](https://github.com/1337isnot1337/DOPPLERGEIST/issues/10) → [DG-10](https://github.com/1337isnot1337/DOPPLERGEIST/issues/11) | Build the actual service/CLI path, then upload UI; use contract fixtures while dependencies mature. |
| Packaging | [DG-11](https://github.com/1337isnot1337/DOPPLERGEIST/issues/12) | Own install/CI/dependency coordination and checksum-verified artifact restoration. |

With fewer agents, combine matching with integration and packaging with product.
With more agents, split benchmark acquisition from its evaluation runner, or API
from UI, after agreeing on ownership and contracts. Do not have several agents
independently rewrite `audio.py`, `search.py` or `pipeline.py`.

## Ready-to-copy assignment prompt

Replace the task/role placeholders with one row above:

```text
Work in https://github.com/1337isnot1337/DOPPLERGEIST as the <ROLE> agent.
Implement <TASK ISSUE URL>, followed by its next task only when dependencies allow.
Read AGENTS.md, docs/AGENT_TASKS.md, docs/HANDOFF.md and the issue before editing.
Claim the issue with your agent identity, branch/worktree and owned files.
Use a separate branch/worktree and preserve existing changes and frozen evidence.
Coordinate shared interfaces and conflicting file ownership in issue #1.
Implement the task, run meaningful verification, and open a focused linked PR.
Report exact commands, commit, artifacts, measured results and unresolved limits.
The product must discover Doppler events automatically from uploaded audio.
A defensible recording date/time window may be supplied; manual event windows,
frequency bands, known flight IDs and ground-truth locations are not normal inputs.
A 100 m result counts as success, but do not claim that from regional-only,
synthetic-only, mocked, selected, or ground-truth-assisted evidence.
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

