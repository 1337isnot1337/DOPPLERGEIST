# Six-event isolated CLI replay

The actual installed CLI/job pipeline finished **inconclusive** with reason
`ambiguous_locations`. It automatically detected all six synthetic events,
searched the declared finite population, refined candidates and ran the decision
stage. Post-run evaluation found that the leading candidate matched all six true
flights and was 0.06125 m from synthetic truth. That candidate error is not an
accepted pipeline estimate or independent real-world accuracy.

The frozen runtime is `39634c3fc565a3d025a661f90eddae54430591f9`; wheel SHA256 is
`62d310e01d4a4e26317ad11b686e604bb79551c934efc73b02f6fc89bf1c28a8`.
It integrates the then-published product and all-event search changes. Its full
suite passed 196 tests. All 23 installed package/static files still match their
frozen hashes after the run. Later producer fixes were not substituted into this
job. The complete source/command/inputs and initial startup failure are in the
[protocol](SIX_EVENT_PROTOCOL.md) and [receipts](six-event-20261103/).

## Actual execution and scope

The input is the canonical 1,400 s six-event MP3 from release
`multi-event-fixtures-2026-11-03`, SHA256
`1ab55fb23eb2dff907ef48d81e3dabb33524b34af12c58e714b96212b9f69aee`.
The normal request supplies CONUS coverage and the fixture's explicit exact UTC
start. No true location, observer bounds, flight whitelist, event windows or
frequency bands enter the request. All 18 opaque full trajectories, including
distractors, are available. This is a complete *finite synthetic population*,
not a real national traffic dataset. The supplied clock is not independently
recovered by this experiment.

The backend executes an installed wheel in an input-only filesystem/network
namespace. Inputs are read only. Home, authentication environment, generator,
renderer, truth and the full checkout are absent. The dependency version inventory
and actual import path are recorded. The experimenter knows the public generator;
this is runtime truth separation, not a sealed experimenter-blind holdout.

All 76,328 coarse tiles completed, with no tile failures or unsearched tiles.
The track-envelope queries led to 15,488 evaluated coarse receiver points; fine
refinement evaluated 1,681 points and skipped 15,129 already-covered overlap
points. Search reports all six event groups considered, no event-count limit
applied, no refinement failure and available declared finite input coverage.
The bounded 100-candidate retention still does not establish exhaustive
alternative-mode assessment. That limitation remains in the original result.

The whole job took 2,872.448 s (47 min 52 s); search took 2,776.022 s. Search-stage
native peak RSS was 365.512 MiB. Exact full-job peak RSS is unavailable: GNU Time
outside this namespace measured the launcher, reporting 1,960 KiB and zero CPU.
Those raw values are retained and are not attributed to the scoring worker.
A separate 64 MiB allocation control reproduced the accounting boundary:
inside-namespace Time and native `ru_maxrss` both measured 76,128 KiB, while the
outer wrapper measured 2,092 KiB. Future full-job measurements need the timer
inside the namespace. No native speed claim is made from these receipts.

## Post-run evaluation

The original job finished at 03:02:03.893774 UTC on 2026-11-03. The predeclared
score-participation check then completed without labels. Truth was first opened
at 03:04:15.774185 UTC, in a separate evaluation directory outside every backend
mount. Its hash matches the release manifest:
`e514bb0c2e8bc2ad23733817fbc82c830bbd5c14b378247debc4e62941f84bb9`.
The first attempted lookup used the wrong archive member name and read no label
bytes; that lookup is recorded in the access receipt.

| Diagnostic candidate stage | Best point error | Within 100 m | Within 500 m | Within 1,000 m |
| --- | ---: | --- | --- | --- |
| Completed coarse grid | 353.451 m | No | Yes | Yes |
| Completed fine grid | 21.886 m | Yes | Yes | Yes |
| Leading product candidate | 0.06125 m | Yes | Yes | Yes |

These rows evaluate candidate points. **The accepted-localization outcome remains
inconclusive at every threshold.** No coordinate was asserted as a supported
answer. All 106 product candidate records are retained and evaluated, rather than
selecting the closest one after truth access. They contain 29 six-group, 62
five-group and 15 four-group records. Every reported subset association matches
the post-run labels. Their point errors range from 0.05253 to 289.818 m. Multiple
records represent nearby or duplicate spatial hypotheses; 106 is not a count of
independent trials or distinct modes.

Each of the six detected groups overlaps a different truth event, with interval
intersection-over-union from 0.821 to 0.960. No truth event is left unmatched in
that diagnostic join. The leading record includes all six correct flights and
preserves the supplied shared clock exactly. These are results for this one
development fixture, not calibrated discovery recall or real-audio accuracy.

The score-participation check selected the leading *search* row, with all six
groups, before opening truth. Its recomputed score differs by 1.89e-11. Its six
positive normalized support contributions are 0.95687, 0.95842, 0.95451, 0.93773,
0.91970 and 0.96285. All groups respond to the fixed 100 m geometry offsets;
groups five and six change their residual scores by up to 0.681 and 0.664 Hz.
The shared clock and flight assignment stay fixed. These support units are
ranking heuristics, not probabilities. This checks participation of later
flyovers; it is not leave-one-flyover-out prediction.

## Why it remains inconclusive

The frozen `engineering-v3` decision identifies a same-association alternative
21.945 m from the leading point, with a score gap of 0.03593 support units per
group. It compares that separation with the leading uncalibrated sensitivity
radius of 14.431 m and returns `ambiguous_locations`. The current 1,000 m target
does not by itself repair finite-mode accounting or justify changing this
historical decision. The competing-point geometry is supplied to the existing
finite-ledger/spatial-union workstream for assessment under its explicit policy.

The initial valid MP3 was also incorrectly classified `invalid_media` when the
first namespace lacked a BLAS library symlink. Its full failure and the corrected
read-only system mount are preserved. A separate one-cell runtime diagnostic
found 384 ridge fits for six distinct inputs; a bounded-cache control reproduced
every returned candidate exactly with six actual fits. Neither experiment changes
the original job or establishes a full-pipeline speedup.

The final end-to-end goal remains open: this run supplies genuine installed-CLI
and all-event participation evidence, while finite decision semantics and an
independently timed, GPS-referenced real corpus remain separate acceptance gates.
The real-source trajectory-support gate also remains outside this synthetic run.
The [bird-feed tests](https://github.com/1337isnot1337/DOPPLERGEIST/pull/76) add real capture/discovery evidence
with their clock/reference limits; they do not replace those gates.

## Restore the evidence

The checksummed bundle is published as the prerelease
[`six-event-cli-replay-2026-11-03`](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/six-event-cli-replay-2026-11-03).
It contains these receipts, the exact pure-Python wheel and derived index/operator
file, every coarse checkpoint in a nested verified archive, and the per-checkpoint
hash ledger. It includes no source media, virtual environment or Python cache.
Original MP3/terrain/track inputs come from the canonical fixture release above.
The separate external manifest inventories every bundle member by hash and size.

The evidence bundle contains post-run labels. For backend replay, restore only
`inputs/` from the canonical fixture and the supplied index/operator files to a
dedicated input directory; mount only that directory and the installed wheel and
dependencies. Keep the evidence/label directories outside the namespace. The
actual namespace command, manifests and runner are saved in the terminal receipt.
Host paths in the historical runner need to be mapped to the new installation;
they are implementation paths, not scientific search constraints. Install the
nine pinned runtime dependencies from the attached
`runtime-requirements-active.txt` or the corrected Git `runtime-requirements.txt`.
The first bundle's export included both the system Requests 2.31.0 metadata and
the active private Requests 2.34.2 metadata as simultaneous pins. The original
bundle is preserved; `dependency-pin-correction.json` records the correction and
the actual imported module paths/versions. The executed replay used private
Requests 2.34.2, and the wheel/input/results are unchanged. The full metadata
inventory remains useful provenance, but is not a list of active imports.

The portable evaluator in `six-event-20261103/evaluate_candidate_points.py`
reproduces all six event joins and all 306 retained product/fine/coarse candidate
records exactly. It requires a terminal job and refuses to overwrite its output:

```bash
python docs/verification/six-event-20261103/evaluate_candidate_points.py \
  --job results/six-event-cli-isolated-v2-20261103/jobs/33632675dc964547bb2c5626e55a10e4 \
  --truth results/six-event-postrun-evaluation-20261103/truth.json \
  --output results/six-event-postrun-evaluation-20261103/new-evaluation.json
```
