# Experimental episode repair after PR #356

This is an acoustic development comparison. Accepted frequency patterns do not
establish aircraft identity, physical source motion, or a single physical emitter.
The experimental scanner remains opt-in. Production `discovery.py`, automatic
upload routing, flight search and localization algorithms are unchanged.

The [original report](ACOUSTIC_EPISODES_REPORT.md) and
[original observations](../benchmarks/acoustic-episodes-349/) are preserved. This
follow-up uses separate output directories. PR #356 was merged by another
controller during repair; this work is a separate **draft, unmerged follow-up**.

## Pins and fixed evaluation

At task start PR head was `3447e33ec6760d55f3fc2457c616d559b1a49944`;
comparison baseline was `451b67f01dcd1dfe44d47c42407f404706a5a9b7`.
The published comparison is `05548ed1cb0954db8fac960523e39300dc97308d`.
Starting main was `81082211f2194c7bbe370696b25d963b30f7d223`.
The follow-up branch starts from main `6eeacc62e036f699fa0121b826c6172b394aeee3`,
after experimental-module isolation and consumer repairs. Detector replay is
pinned to `9b4ea5839638d17cb3127071c294a48a4b644972`.

All 32 original inputs were fixed before repair evaluation: twelve AeroSonicDB
clips, DLR's seven-second excerpt, all eighteen full DEMAND channel-1 recordings,
and the hour-long reference. All 31 non-hour inputs also receive 40–6000 Hz
analysis. No recordings were added or removed, and no per-recording parameters,
filenames or publisher labels enter detection. Original hashes, rights and
processing remain in [the source manifest](../benchmarks/acoustic-episodes-349/manifest.json).
No media is redistributed here. AeroSonicDB attribution is Downward/Nordby,
CC BY-NC 4.0; DEMAND is Thiemann/Ito/Vincent, CC BY-SA 3.0; DLR is CC BY 4.0.
Reference-audio redistribution permission remains unestablished.

Before candidate evaluation, raw spectra without detector overlays showed
coherent descending contours in all six lost reference intervals, a rising family
in case-0013 around49–59s, and broadband-dominated DLR audio without a clearly
resolved moving-tone reference in the inspected40–6000Hz range. DLR's publisher
flyover label and original zero output remain unchanged: it is still a presence
miss under that label, not a demonstrated true negative. This inspection does
not establish an aircraft count or replace labels with detector output.

Scoring uses the frozen legacy groups as **retention references**, not exhaustive
ground truth. Hungarian assignment matches each canonical proposal to at most one
reference. Eligibility requires at least three exact-time frequency agreements
within `max(1 Hz, .006*f)` and at least25% overlap of observed temporal cells.
Assignment maximizes retained-point fraction, using temporal overlap only as a
tie-break. Misses, matched-point coverage, temporal overlap, endpoint differences,
additional reference-compatible proposals and other extras are separate outputs.
A proposal compatible with two references is flagged as possible merging; old
fragments can themselves describe one acoustic event. Thus these counts are
review flags, not calibrated grouping-error or aircraft false-alarm rates.
The independent case-0013 rising observation is assessed separately, not silently
added to the legacy reference set. Publisher/background labels stay intact.

## Causal diagnosis

The first failure of each originally lost path is identifiable on **identical PR
decoded samples and spectra**. The original linker can track these contours;
the hard prediction gate splits them before episode acceptance. The table gives
the largest piece's retained reference observations. Replacing prediction alone
keeps normalization, selected peaks, assignment, decoding and gap settings fixed.
Motion checks are then applied separately to the same resulting measurements.

| Legacy child | Reference points | Hard gate largest piece | Prediction-only largest piece | Old / repaired continuity q95 on prediction-only piece |
| --- | ---: | ---: | ---: | ---: |
| event-0001,293.5–308.5s |23|7|17|5.585 /0.742|
| event-0002,314–333.5s |26|6|16|3.480 /0.512|
| event-0004,676–690s |21|10|6|0.169 /0.217|
| event-0009,1265.5–1282s |23|7|21|2.522 /0.582|
| event-0014,3101–3119s |25|13|24|1.011 /0.424|
| event-0016,3454–3469.5s |28|19|27|1.270 /0.525|

Prediction alone worsens one target and does not recover whole events. Width
uncertainty, bidirectional hypotheses, gap penalties and episode-level acceptance
are material. This ablation is not a claim that a looser gate is sufficient.
The independent [six-band raw spectrum](../benchmarks/acoustic-episode-repair-20261104/reference-six.png) and per-target trace summaries are linked
from the new benchmark directory.

Other distinct causes:

- The old continuity rule normalizes a transition differently from linking.
  Shared elapsed-time prediction fixes that disagreement without removing a
  frequency-rate bound or allowing arbitrary missing-time extrapolation.
- Sustained paths with12s of extent but fewer than12 observed seconds were
  forced into the strong brief path. Sustained acceptance now requires12s
  extent, at least7.8 genuinely observed seconds and65% support. A long gap
  cannot become evidence duration. Brief acceptance retains its separate gates.
- A loop variable overwrote child observed duration with a boolean. Main's
  integration already fixes this diagnostic; original artifacts retain the
  incorrect historical values. Episode duration was separately computed.
- A broad fixed-band normalization experiment could suppress low-frequency
  measurements even without peak-budget starvation. The repair preserves a
  stable40–1600Hz normalization tile and allocates additional coverage its own
  tiles and peak budget. Lower extension uses0–40Hz separately. On identical
  PCM, widening the request does not change the original tile's normalization.
- Shared peaks alone did not make two paths safe to union: extra interleaved
  measurements could contradict a valid track and cause its later rejection.
  Actual reference observations reproduce this failure. Such paths now remain
  explicit alternatives if gap observations disagree or lack local support.
- Brief-path raw prominence alone also licensed sustained stationary sections
  joined by a pitch step. Immediate frame slopes count spectral jitter as
  motion. A new regional check requires resolved changes across at least two
  of three transitions between four elapsed-time regions, using observed
  support and independent-window uncertainty. A recorded DEMAND pitch-step
  regression exercises this check.

The original and PR decoders differ by one terminal sample in the hour cache.
Relative PCM RMS difference is0.00642; maximum absolute difference is0.000752.
The original linker retains the missing contours on PR PCM, so this resampling
change is not their first blocking stage. Full comparisons still re-decode the
same original recordings through each version's own intake, rather than assuming
identical decoder output.

## Implementation and computational bounds

Measured tracks include per-point spectral-width uncertainty, local raw spectral
prominence, actual hop/window widths and original amplitude. These are diagnostics,
not calibrated SNR, posterior probabilities or physical-source error bars.
Prediction uses recent measured rates, rate dispersion, residual scatter,
measurement uncertainty, history extent, salience and actual elapsed time.
Linking, fragment scoring and later continuity use the same predictor. A missing
observation incurs a penalty; no intermediate ridge samples are manufactured.

Each chunk has2s/.5s and.5s/.125s analysis paths. The shorter path's primary peak
allocation scales with hop duration:15 versus60 per normalization band under
default settings, keeping primary candidates per second comparable. Up to12
additional prominent raw tonal peaks per short frame allow weak time-whitened
signals into provisional association. These receive ordinary measured contrast,
not an inflated weight. They must pass episode acceptance. Unsupported source
Nyquist, time grids, spectral-cell and association budgets remain explicit
failures. Effective coverage and per-chunk profiles remain reproducible.

Fragment candidates come from bounded time/frequency neighbourhoods. Endpoint
predictions are cached. At most16 contenders receive detailed scoring per left
fragment and8 enter joint selection; two sweeps restart from original fragments
so later context can retract a previous choice. Ambiguous runner-up scores remain
unresolved. Joint models are cached by their immutable fragment membership,
chains have at most64 fragments, and the chain-array LRU is32MiB. The configured
maximum is16,384 joint refits and1,000,000 charged association operations.
Cheap neighbourhood inspections and pruned contenders are counted separately.
This is bounded approximate association, not a global maximum-likelihood solver.

IfF fragments haveE retained edges, sorting costs `O(E log E)`, withE bounded by8F;
coarse time-neighbour generation still depends on local fragment density.
Each sweep uses cached joint fits instead of refitting after every retry. All
retained candidates/observations remain bounded by32,768/1,000,000. Exceeding a
bound produces `status=failed`, not an apparently exhaustive negative result.
Earlier versions exhausted association budgets; those experiments are retained
as failures and excluded from successful-comparison totals.

Pooled total variation previously counted child-to-child measurement jitter
repeatedly. Joint episodes now use the worst measured child variation ratio,
retaining the naive pooled value as a diagnostic. Joint residual, shape, motion
and support checks remain active. The recorded40-second chunk experiment
reduced20 single-child proposals to5 canonical episodes while preserving23
measured children; the120-second4-episode result stays unchanged.

A later group union must pass the same episode evidence gates if either parent
already qualifies. Unaccepted provisional groups may still accumulate evidence.
This prevents a failed late extension from erasing a valid core. The shared
evaluation is used for reconciliation and final acceptance, with cached boolean
summaries and bounded diagnostics. Every supported pair still has to fit the
joint model; accepted parents are not fused merely because their intervals overlap.

Grouping still checks every supported pair against one constant-scale model,
requires multiple witnesses for larger groups, and assesses harmonic complexity
with orders bounded1–12. A noninteger relation requires envelope evidence. Scale
residual and correlation limits now account for measurement uncertainty. Failed
joint motion/support can retract a group to its measured children, preserving
unresolved membership alternatives rather than discarding every child. Shared
motion remains evidence for an acoustic episode, not a proven common emitter.

Acceptance pools genuinely observed support across compatible components while
counting coincident profiles once. Boundaries use observed hop cells; spectral
window uncertainty is separate. No window padding extends event support to a
recording edge. Regional checks do not irreversibly discard partial components
before reconciliation. Duration/contrast gates still apply after reconciliation.

The one-turn shape model uses [SciPy isotonic regression](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.isotonic_regression.html) with a bounded set of candidate turns.

Periodic context requires at least three non-overlapping, similarly shaped
frequency/envelope occurrences with regular timing. Context is selected
automatically around brief candidates. This conservative diagnostic does not resolve
all music, machinery, animal calls or irregular modulation; isolated smooth
mechanical ramps can be acoustically indistinguishable. They remain counted,
source-ambiguous proposals. It is not a trained aircraft classifier.

## Results and limitations

Final all-case tables and the exact retained observations are in
[the repair benchmark](../benchmarks/acoustic-episode-repair-20261104/).

All 32 default-band runs and all 31 selected wider-band runs completed under the
predeclared final1800-second external watchdog. The original baseline and PR
before repair were freshly replayed on the same original files. The detector
implementation hash is uniform across all 63 repaired runs. Later reporting-only
commits label measurement instances and correct failed-gate diagnostics; exact
accepted-event/episode parity was checked on the real rich-family recording.

| Input/context | Original groups / children | PR before repair | Repaired40–1600Hz | Repaired40–6000Hz |
| --- | ---: | ---: | ---: | ---: |
| Six aircraft-publisher clips |2 /6|2 /9|12 /51|20 /74|
| Six background-publisher clips |0 /0|0 /0|1 /5|1 /5|
| DLR7s |0 /0|0 /0|0 /0|0 /0|
| Eighteen DEMAND recordings |2 /2|7 /10|79 /143|96 /180|
| Hour reference |16 /18|30 /38|92 /200|Not attempted|

Proposal-positive aircraft-publisher recordings increase from 2/6 to 4/6, and 5/6
with wider coverage. These are recording-presence counts, not aircraft recall.
The10-second backgrounds are eligible for the brief path; one now has a proposal.
DEMAND positives increase from 3/18 before repair to 12/18. These are material
confusing-source outputs, not additional aircraft successes.

Under one-to-one matching, the repaired standard-band catalog retains 19/20
legacy proposal references versus 13/20 before repair. In the hour alone it
retains 15/16 versus 10/16. Matched-point coverage increases from 546/805 to 730/805;
the separate many-to-one measurement-overlap statistic increases from 628/805 to
756/805. The latter is the statistic used in the original report. Neither is
population recall. The six documented losses are all matched again:

| Legacy child | Repaired matched points | Observed temporal overlap |
| --- | ---: | ---: |
|0001|23/23|95.1%|
|0002|23/26|100%|
|0004|17/21|85.1%|
|0009, faint|23/23|95.7%|
|0014|25/25|100%|
|0016|28/28|100%|

Case0013 now has a rising episode spanning47.5625–59.5625s, with8.75 observed
seconds and two measured children. It has7.625 observed seconds within the
independently specified49–59s interval. Gaps remain explicit. A separate brief
turning hypothesis overlaps its end. This is recovery of a supported rising
pattern with partial support and unresolved multiplicity, not complete extraction
of every visible harmonic or proof of independent emitters.

The remaining hour retention miss is legacy0008,1028.5–1053.5s. Its cropped44-point
ridge passes motion checks, but the fuller measured80-point track at1021–1063s
has two resolved reversals against the one-turn limit. The
[independent980–1100s spectrum](../benchmarks/acoustic-episode-repair-20261104/event8-context.png)
shows a persistent carrier with several dips. A recorded-context regression
checks the crop/full distinction. The original reference is retained in the
16-reference denominator and still counted as a miss. This is evidence for the
contract rejection, not a corrected physical-source label or proof the baseline
proposal was false.

The hour has four duplicate-reference review flags and73 other extras, versus
two and18 before repair. There is one possible-merging flag involving legacy
0006/0007; their measured children and gaps remain available. The acoustic data
cannot certify whether these are independent physical events. Redundant-proposal
reduction is therefore not demonstrated globally, and no physical-source
merging rate is estimated. Improved retention comes with substantially more
unverified/confusing proposals. This repair does not establish a general
precision improvement.

### Wider-band and boundary controls

On identical16kHz PCM, case0039's narrow scan preserves all340 lower-band
measurements from its4kHz scan. Before the supported-parent guard, widening on
those same16kHz samples retained162/340 and lost its early group: a larger
constant-scale group failed episode acceptance and its fallback lost the valid
subgroup. The guard restores the early group with98% temporal overlap and
277/340 lower-band measurements overall. The
[independent early-band spectrum](../benchmarks/acoustic-episode-repair-20261104/case39-context.png)
and unchanged measured parent/union fixtures support this diagnosis.

The final narrow-to-wide one-to-one table leaves one unmatched narrow proposal
in case0039 and one in DEMAND metro. Each has an eligible match when scored
individually; competing narrow references consolidate into wider proposals.
This remains flagged in the table. Raw measurement retention is277/340 and
1761/1909 respectively. Thus stable normalization/allocation does not imply
invariant raw tracks, boundaries or canonical multiplicity. Remaining measurement
loss and grouping uncertainty are visible rather than treated as exhaustive
negative results.

The recorded rich-family control produces4 episodes/26 children at both4kHz
and16kHz decoding. Across2433 coincident measurements, the90th-percentile
frequency difference is0.00000152Hz. Repeated same-configuration discovery has
exactly equal measurements, canonical IDs and membership. With40s chunks/20s
overlap, the correlated-variation correction changes20 single-child proposals
to5 episodes/23 children; ordinary120s chunks retain4 episodes. Chunk settings
still affect grouping. A separate20–6000Hz run retains4 episodes/26 children.
These controls demonstrate exercised coverage and boundary behavior, not complete
frequency-independent or chunk-independent detection.

### Operational cost and software verification

| Standard-band arm | Sum of per-case wall time,32 inputs | Hour wall time | Maximum RSS | Discovery output,32 inputs |
| --- | ---: | ---: | ---: | ---: |
| Original |66.79s|15.28s|169.7MiB|1.68MiB|
| PR before repair |115.56s|34.27s|152.5MiB|2.02MiB|
| Repaired |1908.91s|662.91s|211.0MiB|9.99MiB|

Repaired CPU time sums to1670.70s, including604.24s for the hour. The31 wider
runs sum to2423.66s per-case wall time and2193.57s CPU, peak341.2MiB RSS and7.06MiB
discovery output. Costs exclude the disk-backed intake cache from output volume;
mono float32 cache storage is4×sample-rate×duration bytes. Per-case wall time includes input hashing, intake, discovery and summary plotting,
starting after initial detector imports. RSS covers the process lifetime. CPU
time covers catalog construction inside discovery, excluding intake, final JSON
serialization and plots. Runs shared a host and used
bounded process concurrency with one BLAS thread per process; these are observed
operational costs, not isolated microbenchmarks.

Earlier1,000,000-association-budget failures and600s external-watchdog failures
are preserved separately. Increasing the final external watchdog to1800s applied
to every selected repaired input; detector association/refit limits were not
raised for an individual recording. The final hour still exceeds600s, so a
600s deployment budget would fail. Peak linking dominated instrumented CPU;
fragment stitching was smaller. Symmetric incoming/outgoing limits bound dense
link compatibility retries. Memoizing unchanged active histories preserved every
raw path in a recorded-PCM control, with roundoff tolerance across numerical
stacks. A same-PCM dense-family timing pair regressed12.32→13.45 CPU seconds,
while the full-hour development pair improved753.94→628.08 CPU seconds. The
cache does not provide a universal speedup. Runtime is a substantial regression
relative to the original scanner.

The final hour retains17,779 provisional paths/209,896 observations, charges
714,101 association operations and4057 joint refits, and exports92 episodes/200
children. No candidate-noise trace dump is enabled. Large overview legends are
bounded to preserve a readable plot. The supported-parent diagnostics have a
separate20-entry bound so early noise decisions cannot consume that entire
explanation budget.

Twenty recorded-data/software tests pass locally, covering observation unions,
fragment reordering, raw prediction-cache parity, interleaved conflicts,
stationary pitch steps, fuller modulated context, parent-group preservation,
coverage normalization, corrupt intake, explicit resource failure, CLI routing
and all 63 final artifact contracts. The existing consumer packages all301
canonical proposals across63 runs without changing measurements or fitting a
trajectory. Installation, compilation, CLI help and packaged browser assets
were checked. Software checks also run on GitHub's Python3.11/3.14 jobs.


This is development-set repair, not held-out generalization. Signal-level
checks use genuine recordings; unit tests reorder or split actual observations,
check recorded PCM normalization, exercise measured conflicting tracks and
corrupt an actual recorded-audio container. No chirps, flyovers, coordinate
curves or invented recording outcomes are generated. Software CI remains a
software gate, not aircraft identification or localization validation.

## Reproduction

Restore the existing real media using the original manifest's sources and
checksums. Use absolute local `path` entries when running the following commands;
input checksums are checked before decoding. Do not overwrite existing outputs.

Create local absolute-path manifests from the unchanged source manifest after
restoring its media paths:

```bash
python - <<'PYCODE'
import json
from pathlib import Path
m=json.loads(Path('benchmarks/acoustic-episodes-349/manifest.json').read_text())
for case in m['cases']:
    case['path']=str(Path(case['path']).resolve())
Path('/tmp/dg-all-cases.json').write_text(json.dumps(m,indent=2)+'\n')
m['cases']=[case for case in m['cases'] if case['id']!='whole-reference']
Path('/tmp/dg-non-hour-cases.json').write_text(json.dumps(m,indent=2)+'\n')
PYCODE
```

```bash
git worktree add /tmp/dg-old 451b67f01dcd1dfe44d47c42407f404706a5a9b7
git worktree add /tmp/dg-pr-before 3447e33ec6760d55f3fc2457c616d559b1a49944
git worktree add /tmp/dg-repaired 9b4ea5839638d17cb3127071c294a48a4b644972

# The historical runner selects discovery.py in each historical checkout.
python /tmp/dg-pr-before/scripts/validate_acoustic_episodes.py \
  --manifest /tmp/dg-all-cases.json --source-root /tmp/dg-old \
  --output /absolute/new-legacy
python /tmp/dg-pr-before/scripts/validate_acoustic_episodes.py \
  --manifest /tmp/dg-all-cases.json --source-root /tmp/dg-pr-before \
  --output /absolute/new-before
python scripts/replay_acoustic_repairs.py --jobs 4 --timeout-s 1800 \
  --manifest /tmp/dg-all-cases.json --source-root /tmp/dg-repaired \
  --output /absolute/new-repaired
python scripts/replay_acoustic_repairs.py --jobs 4 --timeout-s 1800 \
  --manifest /tmp/dg-non-hour-cases.json --source-root /tmp/dg-repaired \
  --max-frequency-hz 6000 --output /absolute/new-wide
python scripts/compare_acoustic_repairs.py --manifest /tmp/dg-all-cases.json \
  --legacy /absolute/new-legacy --before /absolute/new-before \
  --repaired /absolute/new-repaired --wide /absolute/new-wide \
  --output /absolute/new-comparison

PYTHONPATH=src python -m pytest -q tests/test_real_episode_repair.py \
  tests/test_real_episode_motion.py tests/test_real_episode_artifact.py \
  tests/test_real_episode_cli.py
```

`all-cases.json` selects every entry of the original32-case manifest;
`non-hour-cases.json` selects the same entries except `whole-reference`.
No published input is selected or dropped based on detector output.

The public prediction-only ablation was also executed:

```bash
PYTHONPATH=src python scripts/ablate_acoustic_prediction.py \
  --before-root /tmp/dg-pr-before \
  --pcm-cache /absolute/new-before/whole-reference/intake \
  --references /absolute/new-legacy/whole-reference/discovery/discovery.json \
  --output /absolute/new-prediction-ablation
```

Use the same interpreter/dependencies across arms. The measured environment was
Python3.14, NumPy2.5.4, SciPy1.18.1 and FFmpeg n9.0.2. Exact versions are recorded
in detector/intake outputs. Content IDs are deterministic for unchanged measured
observations; a different numerical stack can change observations and their IDs.
