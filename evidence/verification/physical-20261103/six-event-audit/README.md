# Independent audit of the six-event CLI replay

The saved pipeline result remains **inconclusive / ambiguous_locations**.
Independent checks agree with all 297 native candidate records and all 76,328
coarse checkpoints. The leading product point is 0.06125 m from synthetic truth.
This point error does not establish an accepted localization.

This audit uses the existing terminal outputs and restored inputs. It does not
repeat the national search, alter its decision, or add a real-recording success.

## Exact sources and restored artifacts

| Item | Frozen identity |
| --- | --- |
| Runtime source | `39634c3fc565a3d025a661f90eddae54430591f9` |
| Original evidence commit | `0ea65162092f854ad0f872133ae12b83a127edea` |
| Exact runtime wheel SHA-256 | `62d310e01d4a4e26317ad11b686e604bb79551c934efc73b02f6fc89bf1c28a8` |
| Evidence archive SHA-256 | `e801c5d463a2bf7586a4aaae297573b3ad006eaabcf9df6cd88396b4eb6c566e` |
| Canonical six-event archive SHA-256 | `a6d79edca1407324ad77fee6b97812eb11f7a84cdb2308d12bd8f2663d4b396c` |
| Native job | `33632675dc964547bb2c5626e55a10e4` |

The [original replay PR](https://github.com/1337isnot1337/DOPPLERGEIST/pull/87)
contains the owner report and its limits. The
[evidence release](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/six-event-cli-replay-2026-11-03)
preserves the exact package, index, native outputs and checkpoint archive. The
[fixture release](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/multi-event-fixtures-2026-11-03)
preserves the canonical inputs, renderer output and separate truth.

All 62 evidence members and all nine canonical fixture members match their
published byte lengths and hashes. All 23 packaged Python/static files match
both the installed-runtime manifest and the frozen Git source. The index passes
SQLite integrity checking and all 18 segment payload hashes. Its source metadata
identifies the canonical Parquet hash.

The initial release request returned 404. That observation remains in
`git-source-audit.json`; publication subsequently completed and the archive was
downloaded successfully. The later receipts and complete archive audit resolve
that access issue.

## Candidate errors and association flags

The independent evaluator joins each detected event to a unique truth interval.
It recomputes WGS84 point distances, association flags, group counts, recording
clocks and distance-tier flags. These values agree with the native evaluator for
every saved record. Result candidates also agree exactly with the decision
artifact's candidates.

| Stage | Records | Correct reported associations | Leading point error | Points within 100 / 500 / 1,000 m |
| --- | ---: | ---: | ---: | ---: |
| Product | 106 | 106 | 0.06125 m | 42 / 106 / 106 |
| Fine search | 100 | 100 | 21.88553 m | 36 / 100 / 100 |
| Coarse search | 91 | 72 | 353.45100 m | 0 / 63 / 63 |

The 19 incorrect coarse associations are correctly labelled in the native
evaluation. Every product point lies within 289.819 m of the synthetic location.
All saved clocks equal the exact supplied synthetic recording epoch.

The archived owner document claims 306 records and 100 coarse records. The native
arrays contain **297 records: 106 product + 100 fine + 91 coarse**. This is a report
count error; the independent check does not replace or relabel native candidates.
The correction was reported on PR #87 and issue #13.

The saved decision cites a same-association competitor 21.94503 m away, with a
0.03592575 support-unit-per-group gap. Its checked sensitivity radius is
14.43117 m. The independent audit reproduces this cited pair. It does not run a
new confidence policy. Accepted localization remains false at all three tiers.

## Checkpoint accounting and participation

Every one of the 76,328 checkpoint members matches its external file hash,
internal payload hash and common run hash. Their counts agree with the native
report: 15,488 coarse points, no failed tiles and no unsearched tiles. Only five
tiles contain retained candidates. Their 91 rows merge exactly to the saved
coarse ranking under the frozen merge implementation. The native report also
records 1,681 fine points and 15,129 skipped overlap evaluations.

The independent participation check imports the hash-verified frozen package.
It fixes the leading search position and shared clock, then evaluates that point
and four 100 m offsets. Source-frequency fits use the original scoring code at
each fixed point. No truth labels, coordinate optimization or clock search enter
this check.

All six event contributions and every saved numeric participation value match
the native check exactly in this runtime. The recomputed leading search score is
`5.690080017045477`, differing from the stored score by approximately
`-1.89e-11`. Each event's residual changes with position; the six maximum changes
over these offsets range from 0.568 to 0.713 Hz. This establishes participation
in this fixed-state calculation, not independent statistical evidence or
calibrated geographic uncertainty.

## Motion assumptions on these frozen inputs

A separate numerical audit examines all 4,860 Hermite intervals across the
18 restored tracks. It checks interval endpoints and stationary roots of squared
speed, with a 33-point sample cross-check per interval. The largest speed is
113.025 m/s, below the frozen model's 343 m/s sound speed.

At the leading search state, all 2,185 selected ridge samples have finite,
positive Doppler factors. Their largest receive-time equation residual is
`1.508e-7` s, below one absolute-epoch floating-point spacing. These checks pass
for this finite synthetic input. They are numerical necessary-condition checks,
not formal interval certificates or fixes for the broader motion-support and
convergence defects tracked in #64.

## Restoration caveat

The archived `runtime-requirements.txt` is an inventory with conflicting exact
pins: both `requests==2.31.0` and `requests==2.34.2`. One fresh environment cannot
satisfy both pins. The inspected native distribution inventory does not identify
which version was imported. The owner was asked to preserve the historical file
and supply separate installation constraints or import provenance.

The successful independent numerical check used requests 2.34.2. Numerical
dependency versions are recorded in `participation-audit.json`. The audit does
not claim that the archived requirements file installs unchanged.

## Reproduce these checks

Use a separate working directory so the committed native receipts remain intact.
The Python environment needs the project's documented scientific dependencies;
the pinned numerical versions are recorded in the participation receipt. The
repository must contain the frozen runtime commit.

```bash
DOPPLERGEIST_REPO=/absolute/path/to/DOPPLERGEIST
DOPPLERGEIST_AUDIT="$DOPPLERGEIST_REPO/evidence/verification/physical-20261103/six-event-audit"
DOPPLERGEIST_WORK=$(mktemp -d)
cp "$DOPPLERGEIST_AUDIT/release-manifest.json" "$DOPPLERGEIST_WORK/"
cp "$DOPPLERGEIST_AUDIT/canonical-release-manifest.json" "$DOPPLERGEIST_WORK/"
curl -fL https://github.com/1337isnot1337/DOPPLERGEIST/releases/download/six-event-cli-replay-2026-11-03/six-event-cli-replay-20261103.tar.gz -o "$DOPPLERGEIST_WORK/release.tar.gz"
curl -fL https://github.com/1337isnot1337/DOPPLERGEIST/releases/download/multi-event-fixtures-2026-11-03/multi-event-6.tar.gz -o "$DOPPLERGEIST_WORK/canonical-six.tar.gz"
python "$DOPPLERGEIST_AUDIT/audit_archives.py" --root "$DOPPLERGEIST_WORK" --repo "$DOPPLERGEIST_REPO"
python "$DOPPLERGEIST_AUDIT/audit_saved_six.py" --evidence "$DOPPLERGEIST_WORK/restored/verification" --output "$DOPPLERGEIST_WORK/candidate-audit.json"
python "$DOPPLERGEIST_AUDIT/recompute_participation.py" --root "$DOPPLERGEIST_WORK"
python "$DOPPLERGEIST_AUDIT/audit_motion_conditions.py" --root "$DOPPLERGEIST_WORK"
```

The candidate audit was run against both the Git evidence and restored release.
The two outputs are byte-identical. The retained command receipts contain the
actual paths and outcomes. The archive audit extracts only the six canonical
input files; it hashes the canonical renderer and truth members without writing
them. The separate post-run evaluator explicitly reads the owner's already
published truth copy from the evidence release.

## Scope and preserved audit corrections

The runtime uses a finite synthetic population of 18 tracks under declared CONUS
bounds. This does not establish real national flight coverage. Native receipts
place first truth access after the terminal job and participation check. This
audit checks that recorded chronology; it is not a new witnessed blind holdout.

The native job took 2,872.448 s. Its search-reported main-process peak is
365.512 MiB; the full-job peak is unknown. The owner's namespace accounting
control shows why the outer timer did not measure the complete worker process.
No precise full-job memory claim is inferred from that timer.

Two development failures of this auditor remain under `attempts/`. The first
incorrectly required every coarse diagnostic candidate to have a true
association. Its receipt also repeated the document's incorrect record count.
The second exposed that count mismatch and corrected the first receipt's
description. The final auditor checks every native truth flag, including false
flags, and reports the actual 297 records. These were audit assumptions and a
documentation finding, not new pipeline failures.

No historical scientific outcome changed. The later finite-ledger, classified
scorer, motion-support and product adapters are outside this frozen runtime.
The independently measured recorder-GPS/sample-zero-UTC corpus in #53 remains
unmet. This evidence does not close #13, #53 or #64.
