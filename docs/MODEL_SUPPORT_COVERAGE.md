# Model-support loss in the tiled search

The source data's spatial/time availability and the model's usable support are
separate. The search report retains `data_scope_complete` for the former and adds
`model_support_complete` for the latter. Any typed unsupported CPA trajectory or
unclassified scoring envelope makes model support false, search status partial
and finite-search evidence incomplete. Its unknown competitors have no optimistic
maximum discarded score. A completed tile does not establish complete evidence.

The additive `model_support` report contains these integer work counts:

- `unsupported_cpa_track_evaluations`: trajectory/stage CPA failures, including
  repeated evaluations in different coarse/refinement stages.
- `unclassified_score_candidates`: candidate envelopes whose work is unknown.
- `evaluated_trials`, `rejected_trials`, `unknown_trials`: totals explicitly
  reported by robust scorer assessments.
- `unreported_trial_envelopes`: interrupted or missing/malformed trial accounting;
  its unknown trial count must not be inferred as zero.

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
