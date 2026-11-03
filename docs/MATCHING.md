# Physical matching

`matching.prepare_events(detected_events)` adapts the shared detected-event
records into the existing `(events, measurements)` search arguments. It uses
subsonic speed and a declared maximum audible distance rather than excluding
tracks using a straight-pass speed/slant estimate. It does not filter aircraft
type. The 20 km default is an explicit search envelope, not guaranteed acoustic
coverage. The outer search must use these same bounds when acquiring tracks and
constructing corridors. Increasing a filter tolerance after corridor generation
cannot restore already excluded data.

Compatible integer harmonic ridges in a `harmonic_group_id` contribute to one
pass and one event clock. Each ridge has equal aggregate weight. Ratios must be
consistent with an integer multiple of the lowest observed ridge. Unsupported
groups fail explicitly; discovery should split them rather than invent a
fundamental or treat them as independent flyovers. `event_ids` on the prepared
internal record maps the merged evidence back to original contract events.

`search.rank_candidates(..., mode="robust_ridge")` fits the actual trajectory at
emission time. One recording start is swept for every event together. A bounded
linear source-frequency change can absorb modest engine drift, with a weak
zero-drift penalty; it cannot fit an arbitrary curve or a separate event clock.
The pseudo-Huber residual reduces the influence of tracing outliers. Every
positive-weight measured sample requires trajectory support. Results include
per-event RMSE, outlier fraction, drift parameters/boundary flags and support.
The score is negative penalized robust residual in Hz, summed over independent
event groups. Higher is better; values and gaps are not probabilities, nor are
they interchangeable with the legacy brightness/RMSE score scales.

Numeric `quality` settings used by matching are `frequency_loss_scale_hz` (default
1 Hz), `source_drift_fraction` (default 0.02 over the event, maximum 0.1),
`cpa_tolerance_s`, `speed_tolerance_mps` and `slant_tolerance_m` (default zero).
`prepare_events` sets CPA tolerance to span the detected window. These are
measurement/proposal settings, not post-hoc parameters selected using truth.
It consumes discovery's `frequency_uncertainty_hz` as a loss scale with a 1 Hz
floor when no explicit scale is supplied and preserves the diagnostic key;
this is not a calibrated noise model. `frequency_sigma_hz` remains a legacy
alias for explicitly supplied loss scales, without claiming statistical sigma.
Pairing intersects the permitted recording-start intervals of all events,
including any absolute-time constraint, so pairwise compatibility cannot
manufacture a joint clock. Legacy scoring modes are preserved for replay.

`matching.refine_candidate(candidate, track_lookup, events, measurements,
terrain)` refines position and a shared recording clock in a bounded local
search. It repeats the fit over declared relative-height scenarios (default
-150/0/+150 m) and returns `sensitivity` profiles and boundary flags. This
tests vertical-datum/altitude degeneracy; it is neither a calibrated confidence
interval nor a complete spatial ambiguity assessment. The nominal result's
score remains evaluated at the actual terrain height. Missing profiles and
boundary optima must be considered by confidence handling. Competing flight
associations and distant spatial modes still need the outer search.
Pass `recording_start_window_s=(lo, hi)` from the trusted request to constrain
all nominal and sensitivity clocks. A point window fixes the clock exactly and
optimizes position only. The local clock radius is intersected with the window;
disjoint bounds fail explicitly. `refinement_clock_bounds_s` records the bounds
actually used. Spatial and nonzero-width clock boundary flags are separate.

Verification:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/benchmark_matching.py \
  --source-root /path/to/restored/data/source --output results/new-matching-run
```

The benchmark replays both original regional cases in the original scoring mode
and robust mode. It refuses to overwrite its output directory, hashes inputs and
implementation, and reads evaluation coordinates only after every search has
finished. Those source-informed windows, bands, region and the faint event's
derived clock remain development limitations. Both failures and successes must
be reported. Automatic full-recording discovery and independent real/national
acceptance are integration gates, not established by these replays.

## Unmatched proposals

`matching.association_candidates(table, events, ..., min_events=1, max_events=3,
max_candidates=20000)` proposes subsets instead of requiring every acoustic
proposal to be an aircraft. It examines subsets up to the declared event count
and fails explicitly when candidate/work budgets are exceeded. The outer driver
must mark that search incomplete. All original proposals remain in the event
artifact. Each hypothesis carries ordered `event_indices`, and
`score_candidate`/`refine_candidate` consume the complete event/measurement lists
and select the corresponding subset internally. Scored rows expose matched and
unmatched event IDs; repeated approaches retain their separate emission times.

Partial associations use a separate score kind,
`matched_group_support_minus_normalized_residual`. A matched group contributes
`1 - robust_loss/(3*frequency_loss_scale_hz)` and must have loss below that threshold.
This rewards multiple consistent independent events without promoting a perfect
single-event fit over a good joint fit. It is an explicit ranking heuristic,
not a likelihood, probability or calibrated false-match test. Different score
kinds must not be mixed in a ranking. Confidence must still consider competing
locations, matched group count, omitted proposals, source coverage and residual
diagnostics. Single-event candidates remain available for a defensible known
clock, and do not by themselves establish a supported location.

## Full sensitivity scenarios

`matching.profile_candidate(candidate, track_lookup, all_events,
all_measurements, terrain, recording_start_window_s=...)` reruns the leading
association under declared perturbations. It returns the nominal refined
candidate with a `sensitivity` artifact containing every scenario, failed
scenario, boundary flag, tested source and maximum displacement from nominal.
It checks each matched ridge with positive/negative frequency offsets and
linear tilts at the declared loss scale, a constant-source alternative, allowed
clock endpoints, relative-height offsets (default 150 m), and sound-speed
offsets (default 5 m/s). Every scenario uses one shared clock and stays inside
the request window. An exact clock remains fixed. Defaults are declared
engineering ranges, not estimated meteorology, a survey, or statistical coverage.

`complete` requires finite support for every scenario and successful local
optimization. `boundary_limited` remains separate. A missing/failed scenario
cannot silently shrink the envelope; confidence must abstain when evidence is
incomplete or exceeds its declared precision. This finite envelope does not
cover every possible model error, and distant competing modes still require
the outer search. The bounded source-frequency solve uses the exact optimum
of its two-variable convex box problem; regression tests compare it against
SciPy's independent constrained solver, including boundary optima.

Altitude scenarios include both common observer-height shifts and independent
positive/negative biases for every matched flight segment. A constant geodetic
height bias adjusts the trajectory derivatives by the derivative of that height
displacement, preserving the original measured motion and never mutating the
source track. The receipt records each flight's altitude basis and bias. Unknown,
barometric, unspecified or mixed non-geometric bases keep sensitivity incomplete;
a generic height envelope cannot establish a common datum. The trusted terrain
and flight heights must already share a defensible ellipsoidal datum. Geometric
interpolation remains labelled and subject to the declared perturbation range.
Terrain must expose an applied geoid conversion or an explicit ellipsoidal-datum
declaration; an unlabelled constant/raster surface keeps the envelope incomplete.

`predict_fitted_ridge(track, observer_ecef, absolute_receive_times_s,
event_diagnostics)` evaluates the frozen fitted model, including source drift at
emission time. Diagnostics retain `source_reference_emission_time_s` and
`source_span_s`; a drifting fit without its reference fails explicitly.
Unsupported times remain NaN. The legacy replay plotter uses this helper for
the scored curve. Older historical PNGs that drew only `f0 * factor` remain
unchanged and are approximations when their associated fit includes drift.
