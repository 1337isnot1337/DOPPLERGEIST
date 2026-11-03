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

Numeric `quality` settings used by matching are `frequency_sigma_hz` (default
1 Hz), `source_drift_fraction` (default 0.02 over the event, maximum 0.1),
`cpa_tolerance_s`, `speed_tolerance_mps` and `slant_tolerance_m` (default zero).
`prepare_events` sets CPA tolerance to span the detected window. These are
measurement/proposal settings, not post-hoc parameters selected using truth.
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
