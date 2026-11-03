# DOPPLERGEIST agent instructions

## Objective and starting points

Implement the automatic MP3-upload-to-location pipeline. The user's target is
approximately 100 m error on supported real recordings. Read
`docs/AGENT_TASKS.md`, `docs/HANDOFF.md`, the assigned GitHub issue and relevant
source before editing. The current CLI still requires manual event settings.

## Coordination

- Claim one bounded issue with your agent identity, branch/worktree and owned files.
  Coordinate through GitHub issue #1; use separate worktrees/branches and focused PRs.
- Refresh remote state with `git fetch origin` before starting, before integrating
  dependencies, before pushing/opening a PR, and at least every 10 minutes during
  long work. Read new comments on your issue and the coordination issue at those
  boundaries. Do not rely on a stale local `main` or issue snapshot.
- Start from current `origin/main` in your own worktree. Keep commits small and
  focused, record useful checkpoints, and include the issue number in PRs. Rebase
  or merge only your own branch, preserving changes; coordinate integration when
  another agent has changed the same interface.
- Respect the contract and ownership plan in `docs/AGENT_TASKS.md`. Coordinate
  overlapping edits to `audio.py`, `search.py`, `pipeline.py`, `terrain.py` and
  dependency declarations before changing a shared interface.
- Preserve user/concurrent changes. Do not force-push shared branches or silently
  replace another agent's implementation. Do not spawn extra agents unless asked.
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

