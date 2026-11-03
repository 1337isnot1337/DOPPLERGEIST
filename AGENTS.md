# DOPPLERGEIST agent instructions

## Objective and starting points

Implement the automatic MP3-upload-to-location pipeline. The user's updated target
is **up to 1,000 m error acceptable, with 100–500 m or better preferred** on supported
real recordings. Report benchmark outcomes at 100, 500 and 1,000 m; preserve old
reports with their original thresholds. Read
`docs/AGENT_TASKS.md`, `docs/HANDOFF.md`, the assigned GitHub issue and relevant
source before editing. The configured research CLI takes manual event settings;
that does not describe the status of the whole project. Whole-recording intake,
automatic discovery and bounded tiled search are implemented on `main`. Check
the README, a pinned source revision and current PR state before describing the
product integration or an acceptance gate as complete or missing. The
[2026-11-03 verification note](docs/VERIFICATION_2026-11-03.md) separates these scopes.

## Coordination

- Use the [agent discussion board](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39)
  as the **default way to talk to other agents**. Discuss design choices, shared
  interfaces, dependencies, blockers, experiments and handoffs there. Reply in the
  existing topic to keep conversations together. Issues track tasks; PRs track
  code review. Link board decisions from the relevant issue/PR and update durable
  documentation when a decision changes an interface or scientific rule.
- Communicate before overlapping work or changing a shared contract. Identify
  your worker role and issue/PR; include the branch or source version when needed.
  Name the role whose input
  you need. All agents may share one GitHub account, so account mentions alone do
  not identify a worker. Ask a concrete question and acknowledge requests to your
  role at the next board check. Resolve disagreements with evidence and record
  the agreed next action; do not leave questions buried under status updates.
- Post findings that affect another worker promptly, including failed experiments
  and changed assumptions. Announce ready dependencies, blockers and handoffs.
  During long work, post a concise update at least every 15 minutes when there is
  new evidence or a changed plan. Include measured results and limits, not just
  activity; keep making independent progress while awaiting a response.
- Claim one bounded issue with your agent identity, branch/worktree and owned files.
  Issue #1 remains the task index and historical log. Keep one active branch/PR per
  workstream where practical; append related fixes and results to it. Do not create
  a new branch or PR for every verification run. Announce ownership on the board.
- Refresh remote state with `git fetch origin` before starting, before integrating
  dependencies, before pushing/opening a PR, and at least every 10 minutes during
  long work. Read new board topics/replies and comments on your issue/PR at those
  boundaries, and check the board before changing shared interfaces or merging.
  Do not rely on a stale local `main`, board or issue snapshot.
- Start from current `origin/main` in your own worktree. Prioritize landing small,
  tested, useful increments on **main**, including independently ready parts of a
  larger task. Do not leave finished work on branches while accumulating reports.
  The primary coordinates landings. Include the issue number in PRs. Rebase
  or merge only your own branch, preserving changes; coordinate integration when
  another agent has changed the same interface.
- Respect the contract and ownership plan in `docs/AGENT_TASKS.md`. Coordinate
  overlapping edits to `audio.py`, `search.py`, `pipeline.py`, `terrain.py` and
  dependency declarations before changing a shared interface.
- Preserve user/concurrent changes. Do not force-push shared branches or silently
  replace another agent's implementation.
- **Do not launch subagents yourself.** The user controls worker deployment.
  Record new workstreams as concrete GitHub issues, announce them on the board,
  and leave them available for workers the user chooses to launch. A proposed
  independent workstream is not permission to spawn a worker.
- Keep the worktree clean between checkpoints. Inspect `git status` and the diff
  before every commit; stage only owned files. Never use broad cleanup, hard reset,
  checkout/restore or stash operations to hide or discard someone else's work.
  Do not commit virtual environments, caches, credentials or unrelated files.
- Dependencies are integration gates. Prepare tests/fixtures/adapters while waiting,
  but do not close an issue on a mock or a plan.

## Cut audit and provenance overhead

**Working code and meaningful experiments are the deliverables. Heavily reduce
provenance paperwork and passive auditing.** This instruction supersedes older
documentation that asks for exhaustive receipts, hashes or audit packages.

- Do not open standalone provenance, checksum, receipt or passive-audit PRs.
  Do not audit another audit, repackage existing evidence, or repeatedly verify
  unchanged files. Put a genuinely useful finding in the existing issue/PR.
- Do not generate routine SHA manifests for source files, documentation, plots,
  test output, stdout/stderr, intermediate attempts or other routine artifacts.
  Git history and a short test/experiment summary are normally sufficient.
- Use checksums only for a concrete integrity requirement, such as verifying an
  external download or identifying a cache input. Do not expand that requirement
  into hashes of every related file or layers of JSON receipts.
- Verification must answer a concrete question about behavior, fix a reproduced
  defect, or measure an actual result. End-to-end runs, physical-model controls,
  ranking/accuracy benchmarks and regression tests remain useful. Merely proving
  that archived bytes match other archived bytes is not a development workstream.
- Keep results compact: the command/settings, outcome, relevant failure and limits.
  Do not duplicate them across multiple JSON/XML/log/Markdown packages. Keep bulky
  diagnostic output local unless someone needs it to reproduce or fix a problem.
- Stop existing passive-audit-only work. Carry any actionable bug into the owning
  implementation task, then close redundant PRs. Preserve useful code and actual
  experimental findings; do not merge paperwork just to mark a task complete.
- Reduce branch/PR backlog after landing work. Remove merged or redundant branch
  names once active work and downstream dependencies are accounted for. Never
  discard unique useful changes or interfere with another worker's active checkout.

## Scientific and product boundaries

- **Real-world validation only.** The user directed: "NO MORE SYNTHETIC DATA!!"
  and "I want REAL WORLD tests, audio recordings, geolocations." Stop new synthetic
  data generation, benchmark experiments and replay runs, including active runs
  owned by your worker; preserve their existing outputs and honest status. Use
  actual recorded aircraft audio and independently established recorder locations
  and defensible UTC evidence for validation. Existing synthetic results remain
  historical and cannot satisfy the real-geolocation acceptance gate. Discovery
  on real audio alone is also insufficient to establish location accuracy.
- Audio-relative seconds and absolute UTC are distinct. File modification/upload
  times do not establish a recording clock. Ask the product user for a defensible
  date/time window when metadata do not supply one.
- The automatic workflow must not require manual event windows/bands, true flight
  IDs, true coordinates or a truth-derived search box.
- Keep emission-time sound propagation, consistent altitude datums, track-gap
  handling and locked multi-event timing. Unknown types and potentially audible
  jets cannot be unconditionally discarded.
- Use all supported independent flyovers, including three, four or more, to
  constrain one shared location and recording clock. Do not impose a default
  two- or three-event cap or silently discard later events. Harmonics/fragments
  count once; unconfirmed acoustic proposals may remain unmatched. Bound compute
  and memory explicitly and report incomplete search if budgets are exhausted.
- Distinguish measured benchmark location error from uncalibrated sensitivity.
  The relaxed distance target does not establish missing clock/coverage evidence
  or make ambiguous flight associations unique.
- Raw ranking scores are not probabilities. Return an explicit inconclusive result
  when events, coverage or constraints are insufficient.
- Never describe regional, synthetic, annotation-assisted or selected results as
  independent nationwide real-audio validation. Report all benchmark outcomes.

## Artifacts and verification

- Do not upload the source YouTube MP4. Use release assets for necessary large
  inputs; verify external downloads when needed. See `docs/ARTIFACTS.md`, subject
  to the lean-verification rules above.
- Preserve `evidence/` and historical `results/`. Use a new output directory for
  each actual experiment so failures are not overwritten. A short note of the
  source version, settings and result is enough; exhaustive hashes are not required.
- Standard check: `.venv/bin/python -m pytest -q` after installing the project and
  pytest. Run additional checks appropriate to the changed behavior.
- Final PR/task handoff: concrete change, relevant test command/result and remaining
  limits. Link necessary outputs rather than creating another receipt package.
  Do not claim unrun checks.

