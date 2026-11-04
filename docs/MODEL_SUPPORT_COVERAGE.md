# Model-support loss in the tiled search

The source data's spatial/time availability and the model's usable support are
separate. The search report retains `data_scope_complete` for the former and adds
`model_support_complete` for the latter. Any typed unsupported CPA trajectory or
unclassified scoring envelope makes model support false. Separately,
`model_assessment_complete` records whether every finite scoring envelope is
evaluated, rejected, or covered by a validated score bound. Unsupported CPA
trajectories, unreported clock trials, and unbounded alternatives keep the search
partial. A completed tile does not establish complete evidence.

For robust-ridge subset association with a bounded recording-start window and no
silence filter, an unsupported trajectory that starts strictly after every
possible event CPA arrival cannot participate in an association. Nor can one
whose latest emission plus the maximum sound-travel delay is strictly before
every possible event CPA arrival. Those tracks
are reported separately as `clock_excluded_unsupported_tracks` in stage
diagnostics and counted in `clock_excluded_unsupported_track_evaluations`; their
original motion failures and conservative clock bounds remain inspectable. The
bound includes the configured clock sweep, CPA and association tolerances, and
outward floating-point rounding. Overlap, missing or invalid clock information,
fixed-clock mode, other scoring modes, and silence filtering retain the usual
unsupported/partial behavior. This does not repair the source trajectory or
establish geographic coverage. The HTTP evidence verifier checks the recorded
inequality against the search clock and stage totals; it does not independently
reload the original aircraft index to verify the recorded emission endpoints.

The additive `model_support` report contains these integer work counts:

- `unsupported_cpa_track_evaluations`: trajectory/stage CPA failures, including
  repeated evaluations in different coarse/refinement stages.
- `unclassified_score_candidates`: candidate envelopes whose work is unknown.
- `evaluated_trials`, `rejected_trials`, `unknown_trials`: totals explicitly
  reported by robust scorer assessments.
- `unreported_trial_envelopes`: interrupted or missing/malformed trial accounting;
  its unknown trial count must not be inferred as zero.
- `bounded_score_candidates`, `unbounded_score_candidates`: the partition of
  unclassified scoring envelopes by whether every scheduled clock trial has a
  validated score ceiling or a supported-event rejection.

For the normalized subset score, an unknown event contributes at most one unit
because its robust loss is nonnegative. A validated complete event can tighten
that ceiling; an event exceeding its unchanged residual limit rejects that
association at that clock. The maximum bound across every scheduled clock is
persisted separately from measured scores. Raw missing-support diagnostics remain
unchanged. See [the finite-search decision](FINITE_SEARCH_DECISION.md).

The product accepts this accounting only when the raw counts, persisted bound
counts, completion flags, and combined discarded-score bound agree. It still
defers competitive bounds to the existing confidence decision. No bound repairs
missing flight coverage, invalid motion, omitted tiles, event caps, or an
incomplete sensitivity profile.

`diagnostics_directory` points to `support/`. Per-stage JSON files preserve every
affected track ID/reason and every unclassified candidate's receiver, event/flight
assignments, pass times, available clock bounds and scoring assessment. Coarse
checkpoints also retain these diagnostics; resumed counts replace work rather
than inflating it. Refinement failures use separate stage files. Per-stage lists
are bounded by the existing track/candidate budgets; the report aggregates counts
without collecting a national diagnostic list in memory.

Only `geometry.AcousticSupportError` is isolated. A CPA error conservatively
excludes that entire track's work for the receiver stage, including partial rows
from earlier chunks, and keeps valid other-track rows. The diagnostic labels the
whole track time span and receiver extent as a conservative loss envelope: this
narrow exception need not identify the exact unsupported interval. Optional
emission/receive intervals reported by the physical validator are preserved in
`reported_intervals`; they do not narrow the conservative coverage envelope. Original index
payloads are retained. Robust scoring classifies typed failures per clock trial;
the outer handler also preserves other candidates if a legacy scorer raises the
same typed error. An interrupted scorer's unreported trial count stays unknown.
Generic programming/configuration errors retain the existing explicit tile-failure
behavior.

This handling does not certify continuous total speed or Newton convergence,
repair historical missing derivatives or altitude clipping, identify the cause of
bad observations, or establish complete real-flight coverage. Issue #64 retains
those open gates and the historical 855/858 result. No old outcome is promoted.

The integrated W3 physical guard validates whole-source continuous motion at both
actual CPA call sites and time-local motion/convergence in direct acoustic
scoring. A real constructed indexed source with zero knot speeds and a >700 m/s
interior peak now reaches this outer typed boundary without a monkeypatch.
The mixed-source regression preserves the clean candidate identities/scores,
retains the original malformed source, and reports partial model coverage. This
verified connection does not repair source observations or establish real-data
acceptance; W3 documents the numerical support assumptions in MOTION_SUPPORT.md.

## Configured research runs

The configured `dopplergeist run` path also isolates `AcousticSupportError` at the
track and candidate boundaries. A failed CPA track leaves its whole source time
span and receiver stage unassessed. Other tracks retain their original CPA rows.
A typed scoring failure leaves that candidate's full proposed clock domain
unassessed. Generic programming and configuration errors still propagate.

`support/` retains the excluded track IDs, reported physical intervals, receiver
envelopes, candidate associations, clock domains, and available trial assessments.
`model-support.json` summarizes those stages. Counts include repeated evaluations
of the same track or candidate at different resolutions. Missing trial records
remain unreported work. They do not become zero unknown trials.

Legacy brightness and ridge scoring do not supply complete clock-trial records.
Their finite scores remain ranked hypotheses with `core_assessment_complete: false`.
Unsupported or unclassified work makes `model_support_complete` and
`model_assessment_complete` false. Original input provenance remains in the report.
The isolation does not repair velocities, observations, or physical model support.

The configured report declares `result_scope: configured_research_ranking` and
`accepted_location: false`. Empty ranking results retain `best: null` and the
support diagnostics. This path does not certify source coverage, eliminate missing
competitors, or make an automatic localization decision.
