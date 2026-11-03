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
  your worker role, issue/PR, branch and exact commit; name the role whose input
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
  Issue #1 remains the task index and historical log. Use separate worktrees/branches
  and focused PRs, and announce your ownership on the discussion board.
- Refresh remote state with `git fetch origin` before starting, before integrating
  dependencies, before pushing/opening a PR, and at least every 10 minutes during
  long work. Read new board topics/replies and comments on your issue/PR at those
  boundaries, and check the board before changing shared interfaces or merging.
  Do not rely on a stale local `main`, board or issue snapshot.
- Start from current `origin/main` in your own worktree. Keep commits small and
  focused, record useful checkpoints, and include the issue number in PRs. Rebase
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

## Scientific and product boundaries

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

- Do not upload the source YouTube MP4. Large data belong in checksummed release
  assets, with provenance; see `docs/ARTIFACTS.md`.
- Preserve `evidence/` and historical `results/`. Use a new output directory for
  every experiment and record source/configuration/code hashes.
- Standard check: `.venv/bin/python -m pytest -q` after installing the project and
  pytest. Run additional checks appropriate to the changed behavior.
- Final PR/task handoff: concrete change, exact commit, meaningful test commands
  and results, artifact paths, and unresolved limits. Do not claim unrun checks.

