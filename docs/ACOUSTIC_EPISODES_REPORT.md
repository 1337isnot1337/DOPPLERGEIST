# Acoustic episodes: implementation and real-recording comparison (#349)

This changes the acoustic proposal model, fragment ordering, elapsed-time checks
and frequency-coverage contract. It does **not** demonstrate better aircraft
recall, physical-source identification or localization. Some real baseline
signals regress, and wider coverage returns additional confusing-source proposals.

Starting `origin/main`: `451b67f01dcd1dfe44d47c42407f404706a5a9b7`.
Worktree: `/home/cinna/dopplergeist-acoustic-episodes`, branch
`feat/acoustic-episodes`. Current-main integration is pinned in benchmark commit
`05548ed1cb0954db8fac960523e39300dc97308d`; detector code is frozen in a separate
validation checkout. The subsequently merged optional coherent adapter retains
its legacy helpers and passes its own recorded Michigan-trace tests. That
adapter was not used to supplement or improve this comparison.

## Engineering choices

The canonical episode catalog references all measured children. Constant-scale
fits replace a ratio-dictionary/base-ridge grouping decision. They require
resolved shared motion and temporal support; noninteger relationships also need
measured envelope agreement. Multi-component groups need multiple witnesses and
one consistent scale model over every supported pair. This intentionally leaves
some related fragments split when their relationship cannot be resolved without
single-link chaining. An unresolved relation is not evidence of source independence.

Provisional four-observation paths survive through chunk deduplication and
continuation association before duration rejection. Observation cells, gaps,
prediction residuals, uncertainty and episode support determine acceptance.
Brief events have a stronger, separately exposed path. Linking and rejection use
actual seconds in both directions, with a one-turn allowance rather than a
compulsory descending template. Source motion remains unconfirmed.

A bounded higher-rate single-spectrum path avoids band-duplicate accounting and
selects decoding rate before discarding frequencies. Defaults stay 40–1600 Hz;
20 Hz lower coverage and 6000 Hz upper coverage were exercised separately.
Coverage, work limits, failures, input/code identities and runtime are explicit.
Normal noise diagnostics aggregate counts and measured/threshold ranges. Group
plots render once, and the matching adapter consumes fitted scales once per
canonical episode, retaining the legacy path for old events. See
[the full contract and thresholds](AUDIO_DISCOVERY.md).

## Inputs, expectations and inspection

The [32-input manifest](../benchmarks/acoustic-episodes-349/manifest.json) includes
SHA-256, public source, rights, processing, context and predeclared expectations.
No new media is committed. Unique source duration is approximately 157 minutes:

- First two publisher-aircraft and first two publisher-background clips in each
  location stratum of the existing seed-20261103 AeroSonicDB sample: six 60-second
  aircraft-context clips and six 10-second background-context clips. Downward
  and Nordby, [AeroSonicDB v1.1.2](https://zenodo.org/records/10215080), CC BY-NC 4.0.
- The existing seven-second center-microphone DLR RECORD139 excerpt, with the
  documented constant gain: [source and exact extraction](../benchmarks/dlr-record139-scanner-check-20261103.md),
  [publisher record](https://zenodo.org/records/20494053), CC BY 4.0.
- All 18 available full, unpadded, channel-1 DEMAND recordings, about 300 seconds
  each, including home machinery, nature, public spaces and transport. Thiemann,
  Ito and Vincent, [DEMAND](https://zenodo.org/records/1227121), CC BY-SA 3.0.
  Existing extracted 16 kHz media were reused and individually identified by
  checksum; upstream ZIP integrity was not rechecked during this task.
- The existing hour-long public-reference WAV from the source release, identified
  separately from its MP3 representation. Redistribution permission for the
  original source is unestablished; only derived measurements are saved here.

Every fixed case is retained, including zero and unfavorable results. No filename
exceptions, flight data, coordinates or trajectory fits enter discovery. Context
labels do not certify source identity or aircraft absence. The selection is a
small development set, not a sealed holdout or a calibrated false-positive sample.

Before judging final replays, spectra without proposal overlays were reviewed
for the six aircraft-context clips. The clear family in case-0001, the descending
family in case-0033, and the clearly rising structure at about 50–59 seconds in
case-0013 are useful acoustic checks. Cases 0002, 0039 and 0008 have broadband
masking or weak continuity; their ambiguity remains explicit. These visual
judgments are qualitative, not exhaustive event annotations. They did not change
the frozen expectations to match output counts. Detailed views of the reference
proposals and transport/nature controls were also inspected. No audio playback
or physical-source labeling was used.

## Measured behavior

All 32 default cases and all 31 wider-coverage cases completed. The hour-long
input was not run at 6 kHz in the wider arm. The complete
[case table](../benchmarks/acoustic-episodes-349/comparison.csv) and compressed
[measured observations](../benchmarks/acoustic-episodes-349/observations.jsonl.gz)
retain the negatives, child tracks, canonical memberships, diagnostics and code
identities. Counts below are acoustic proposals.

| Input/context | Old groups / children | New default episodes / children | Wider 40–6000 Hz |
| --- | ---: | ---: | ---: |
| Six aircraft-context clips | 2 / 6 | 2 / 9 | 3 / 12 |
| Six background-context clips | 0 / 0 | 0 / 0 | 0 / 0 |
| DLR seven-second flyover | 0 / 0 | 0 / 0 | 0 / 0 |
| Eighteen DEMAND contexts | 2 / 2 | 7 / 10 | 14 / 19 |
| Hour-long reference | 16 / 18 | 30 / 38 | Not run |

The wider arm still proposes in the **same two of six** aircraft-context clips;
its third proposal is additional multiplicity in case-0001, not recovery of a
third clip. The old 12-second gate made its background zeros inevitable on
10-second clips. The new brief path is duration-eligible there, but six zero
results still do not estimate a population false-alarm rate.

Case-0001 has six measured children in one episode, versus three in the old
output. The bounded family model reports orders `[4,3,2,5,6,5]`, compatible with
an unobserved fundamental; no fundamental ridge is invented. Fourteen supported
pair comparisons agree with the joint scale model, worst residual 0.541 of its
limit, and minimum two resolved-motion witnesses. Observed support extends from
36.5 to 50.0 seconds. This is useful component consolidation, not proof of one
physical source. Missing/fragmented order-5 observations remain separate measured
children in that episode.

![One canonical family with six measured children](../benchmarks/acoustic-episodes-349/family-episodes.png)

The reference has three brief-path proposals: 900–909 s, 2149–2154.5 s and
2163–2169 s. The latter two lack ten total samples and are marked acoustic-review
only. Gaps are preserved. DEMAND car/bus contexts contain retained rising and
turning tonal trajectories; their engine/environment context illustrates why
motion acceptance cannot be called aircraft detection. Near-unison reference
trajectories remain separate when they do not satisfy the common-motion model.

![Separate source-ambiguous vehicle-context trajectories](../benchmarks/acoustic-episodes-349/vehicle-episodes.png)

Regressions are material:

- Default proposal-positive aircraft clips remain 2/6. The visibly rising
  case-0013 remains missed, including a separate 0.5-second-window / 0.125-second-hop,
  20–6000 Hz replay. DLR's seven-second excerpt is also still missed. Supporting
  brief events does not guarantee recovery of fast, broadband or weak passages.
- In the reference, only 628/805 old measured points (78.0%) have a coincident
  new observation within `max(1 Hz, 0.006*f)`. This overlap measure uses actual
  timestamps and is **not recall**. Six old groups have no such retained points:
  293.5–308.5, 314–333.5, 676–690, 1265.5–1282, 3101–3119 and 3454–3469.5 seconds.
  The 1265.5–1282-second ridge is the documented faint-passage regression.
- The old reference groups around 2100–2178.5 and 3060.5–3121 seconds each map
  onto two new groups. Thus partial-family reconciliation remains conservative,
  and the new representation does not solve all fragmentation. Unresolved
  associations and source multiplicity must not be counted as certified
  independent sources.
- The union of reference observed time across all accepted tracks grows from 353.0 to 599.5 seconds, but additional
  accepted tones are unverified. DEMAND gains nature, bus and car proposals and
  loses its old metro proposal. These are confusing-source positives and a lost
  baseline control, not aircraft successes. Wider coverage adds living-room and
  river-context proposals too.

No obviously incompatible trajectory was found within the reviewed case-0001
family, but the data provide no certified simultaneous-source truth. An accidental
physical-source merging rate cannot be estimated here. Mathematical controls
exercise different simultaneous evolution, near-unison retention, failed weak
bridges and later multi-witness reconciliation. They do not establish aircraft
identification or empirical merge accuracy.

## Coverage, boundaries and operational cost

With identical 40–1600 Hz analysis, case-0001 decoded at 4 and 16 kHz retains one
episode and six children. Across 275 coincident measurements, the 90th-percentile
frequency difference is 4.42e-7 Hz (well below resolution). Its 40/20-second
chunk/overlap replay retains one episode but five children; changing the lower
limit to 20 Hz also retains one episode/five children. Chunk whitening and band
normalization can change marginal components. IDs are stable for fixed measured
content, not promised invariant across different configurations. The high-rate
path has no band seam; overlapping chunk observations have raw provenance and
one canonical catalog. Frequency requests above available decoding/source
coverage, too narrow to form a peak, or on an unsupported sample/hop grid fail
explicitly. Under-window real excerpts are valid zero-observation results;
corrupt media and execution/budget failures are separate failures.

| Replay | Sum wall time (s) | Peak RSS (MiB) | Total discovery output (KiB) |
| --- | ---: | ---: | ---: |
| 31 inputs, old 40–1600 Hz | 120.58 | 173.3 | 1400.0 |
| 31 inputs, new 40–1600 Hz | 247.29 | 146.2 | 1503.9 |
| 31 inputs, new 40–6000 Hz | 421.57 | 267.6 | 1618.1 |
| Hour, old 40–1600 Hz | 39.99 | 172.7 | 321.3 |
| Hour, new 40–1600 Hz | 54.11 | 163.1 | 527.3 |

Times include intake, hashing, discovery and one summary plot, in separate case
processes on a contended host. These are single-arm operational observations,
not causal speedups. The default living-room case is a notable runtime regression
because retained noise fragments require reconciliation. The reference retained
2,541 provisional paths / 22,966 observations and used about 14.5k association
work units, below configured budgets. Normal output has no file per rejected
fragment. The 6 kHz arm demonstrates the additional FFT/candidate cost; it is not
the default or a calibrated better detector.

## Reproduction and checks

Restore the real media to the manifest paths and verify the supplied hashes.
The original reference WAV can be restored from the repository's source-only
release asset as described in [artifacts](ARTIFACTS.md); no ADS-B archive is
needed. AeroSonicDB filenames, DEMAND archive names and the DLR transformation are
in the manifest. Then use a fresh directory for each actual run:

```bash
git worktree add --detach /tmp/dg-old 451b67f01dcd1dfe44d47c42407f404706a5a9b7
git worktree add --detach /tmp/dg-new 05548ed1cb0954db8fac960523e39300dc97308d

.venv/bin/python scripts/validate_acoustic_episodes.py \
  --manifest benchmarks/acoustic-episodes-349/manifest.json \
  --source-root /tmp/dg-old --output results/episodes-old
.venv/bin/python scripts/validate_acoustic_episodes.py \
  --manifest benchmarks/acoustic-episodes-349/manifest.json \
  --source-root /tmp/dg-new --output results/episodes-new

# Same 31 inputs for the wide arm; the full hour was predeclared outside this arm.
python - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('benchmarks/acoustic-episodes-349/manifest.json').read_text())
m['cases']=[c for c in m['cases'] if c['id']!='whole-reference']
Path('/tmp/episodes-wide-inputs.json').write_text(json.dumps(m))
PY
.venv/bin/python scripts/validate_acoustic_episodes.py \
  --manifest /tmp/episodes-wide-inputs.json --max-frequency-hz 6000 \
  --source-root /tmp/dg-new --output results/episodes-wide
.venv/bin/python scripts/summarize_acoustic_episodes.py \
  --manifest benchmarks/acoustic-episodes-349/manifest.json \
  --baseline results/episodes-old --new results/episodes-new \
  --wide results/episodes-wide --output results/episodes-comparison

PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_episodes.py \
  tests/test_real_discovery_normalization.py tests/test_real_upload_verification.py \
  tests/test_contracts.py tests/test_job_resume.py tests/test_real_coherent_discovery.py \
  tests/test_real_episode_artifact.py
```

After the frozen comparison, a reporting-only patch replaced the combined
episode-rejection reason with explicit failed gates on both acceptance paths.
The final matching adapter consumes the joint scale model without reimposing a
single-base overlap requirement. All 63 new/default-wide observed outputs adapt
successfully (50 matchable canonical episodes), with no trajectory fitting.
A current-code real replay matched the frozen rich-family clip's complete
`events` and `episodes` exactly and exposed the new rejection ranges.

69 focused checks passed after integrating current main. They cover grouping
order/determinism, witness reconciliation, unsupported bridges, gap accounting,
symmetric motion/turns, modulation/stationary/tone-switch rejection properties,
explicit budget/coverage/execution errors, real measured-child consumer
compatibility, legacy coherent-adapter compatibility, and checkpoint behavior.
No synthetic audio suite was run. Compilation, CLI help, benchmark-instrumentation
checks and an installed wheel's episode module, coherent adapter, high-rate
configuration and web assets passed. All signal-level runs used the genuine
recordings above; coordinate-array tests are mathematical software checks only.

The remaining limits are measured recall losses, ambiguous source multiplicity,
fragment splits, uncertain peak/contrast models, and uncalibrated confidence and
confusing-source rates. A future detector change needs separate real controls;
this evidence does not establish flight identity, localization accuracy or a
nationwide end-to-end result.
