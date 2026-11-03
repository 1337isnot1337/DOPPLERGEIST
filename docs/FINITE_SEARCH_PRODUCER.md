# Finite receiver-grid evidence producer

This is the W2 side of the agreed
[finite-search contract](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39#discussioncomment-19363838).
It does not change the strict request, candidate or JobResult dictionaries.
W4 interprets the artifact and W5 forwards it with ID mappings.

Each finite core row carries `mode_id` and its original `mode_seed`. Identity
contains exact event indices, flight IDs and pass emission times, receiver
coordinates/elevation and the best shared recording clock. No approximate
coordinate/time rounding or association-only collapse is an exact duplicate.
Refinement/profile may preserve the seed ID while returning a new representation;
the original seed remains explicit. A mismatched ID/seed fails validation.

`retention.sqlite` is an input/code/run-bound disk ledger. Before every tile,
global, coarse or fine top-k truncation, it records each distinct finite scored
seed, units and maximum score. Exact duplicate IDs retain their maximum and are
counted separately. The final distinct discarded count and maximum discarded
score include modes removed at any level, excluding IDs still retained at the end.
Per-phase occurrence/dedup/retention/drop counts are in the report; individual
stage records remain on disk. Writes and audits use bounded stage buffers,
SQLite's file-backed temporary storage and streaming stage checks rather than an
in-memory national list. A missing ledger causes affected cached tiles to be
rescored; changed/corrupt/unaccounted stages cannot become zero discards.

The report exposes `finite_search_evidence` with the agreed version-one fields:
scope `evaluated_finite_grid`, completion/pruning flags, score kind, resolutions,
maximum independent-group count, retained ID/score/group records, distinct drop
count, best discarded bound and limitations. It also records the exact optimizer
inputs and pinned implementation hashes, plus `core_assessed_mode_ids`.
W5 provides `candidate_mode_ids` parallel to wire candidates and actually assessed
IDs in matching diagnostics; it must retain all seed identities and baseline
scores, including distinct spatial/clock competitors with the same flights.

The point score is an envelope over the declared bounded shared-clock and
frequency/drift evaluations at that fixed location/pass association. Lower known
clock trials there need not be separate geolocation rows. This does not establish
a unique clock, continuous optimum, off-grid uniqueness, or a bound under another
context/scoring model. Unperformed refinements and profiles have no inferred
upper score. The leading result still needs the complete declared sensitivity,
datum, support and boundary evidence required by W4.

W3's `scoring_assessment` must distinguish complete evaluated/admissibly rejected
trials from unknown model/support/optimizer work. Missing or malformed metadata,
or any unknown trial, makes that envelope unassessed even if its best returned row
is finite. W2 withholds its assessed ID and any optimistic discarded bound and
marks finite evidence incomplete. A fully classified poor fit may be rejected
without pretending an unknown failure was measured. The old
`alternative_modes_exhaustively_assessed` flag stays false and old outcomes remain
frozen.

The robust-ridge scorer now reports every scheduled shared-clock trial, including
duplicate clocks already present in its existing schedule. `evaluated_trials`
counts complete finite event fits; `rejected_trials` is the subset rejected by
the existing association residual limits. `unknown_trials` counts missing or
invalid model/support/fit evidence. Thus `scheduled_trials = evaluated_trials +
unknown_trials`, and `rejected_trials <= evaluated_trials`. One unknown trial
keeps the envelope incomplete even when another trial produces a finite winner.
An empty direct scoring domain has zero trial counts and remains incomplete;
it is not labelled an acoustic rejection. Legacy brightness/ridge scores do not
receive this certificate. Existing scores, clock schedules, thresholds, ranking
and exception behavior are unchanged. This reports completion of the existing
scoring procedure and recorded support, without adding an optimization or
continuous-uniqueness guarantee.

Tests compare the tiled discard bound with a full untiled reference, verify
resume/missing/corrupt-ledger behavior, exercise exact identity and repeated
approaches, and prevent a successful best row from hiding unknown clock trials.
