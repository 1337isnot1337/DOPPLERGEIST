# Bounded robust-clock trial accounting

`search.score_candidate` returns `scoring_assessment` for `robust_ridge` mode:
`complete`, `evaluated_trials`, `rejected_trials`, `unknown_trials` and `reasons`.
These fields describe every clock trial actually requested by the existing
bounded sweep. They do not change the clock grid, fitted source model, scores,
association ordering or score thresholds.

A complete, finite ridge fit at every selected event is an evaluated trial.
When that fit exceeds the existing subset acoustic-loss limit, it is a known
rejection, including an envelope whose every trial is rejected. Missing ridge or
trajectory support and nonfinite model work remain unknown. A finite best row
cannot hide another unknown trial. An empty clock domain is unassessed rather
than vacuously complete. Completion requires zero unknown trials.

`geometry.AcousticSupportError` is a `ValueError` subclass with string attributes
`track_id` and `reason`. Its message is `"<track_id>: <reason>"`. The existing
nonpositive emission-to-arrival derivative failure now uses reason
`non_monotone_arrival`. The scorer catches only this typed model-support failure
and counts the trial as unknown; unrelated `ValueError`s still propagate.
W2's outer driver can use the same type to preserve other track rows while
marking unsupported coverage partial. This increment does not perform that outer
isolation, audit every continuous speed interval, normalize historical traces or
establish complete real-track coverage; those remain #64 work.

W2's finite ledger consumes these exact fields and exposes only classified core
seed IDs. W4's finite-grid consumer and W5's explicit assessment mapping still
apply all coverage, competing-mode, profile and ambiguity gates. Legacy modes
and historical jobs are unchanged. This accounting is not a probability,
continuous-space uniqueness claim or accepted physical replay.

Regression commands and native outputs are retained in the accompanying W1
integration evidence. The controls include a finite best with an unsupported
competing clock, all-trial acoustic rejection, a typed real `Track` failure,
unrelated exceptions and an empty clock domain.
