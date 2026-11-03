# Proposed finite-search decision evidence

This additive consumer is a proposal for W2/W4/W5 agreement in
[the finite-search topic](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39#discussioncomment-19363838).
W2 owns computing search/retention evidence, W5 owns stable mode mappings and
actual assessment completion, and W4 owns this interpretation. It does not change
the version-one request/candidate/JobResult contract or flip the old exhaustion
flag. Existing runs remain frozen.

The distinction is deliberate: the complete evaluated grid and its recorded
refinements can support a qualified finite-search estimate. They do not prove
uniqueness across continuous space or calibrated coverage. The normal residual,
clock, input-coverage, association, actual-radius, all-supported-event and full
sensitivity checks still apply.

## Producer object

W5 forwards W2's object verbatim as `matching_diagnostics.finite_search_evidence`:

```json
{
  "schema_version": 1,
  "scope": "evaluated_finite_grid",
  "complete": true,
  "score_kind": "matched_group_support_minus_normalized_residual",
  "spacing_m": 1000.0,
  "refine_spacing_m": 100.0,
  "max_event_groups": 4,
  "retained_modes": [{"mode_id": "stable-mode-id", "score": 3.8, "event_groups": 4}],
  "discarded_count": 0,
  "best_discarded_score": null,
  "pruning_accounted_for": true,
  "limitations": ["Evaluated grids and refinements only; continuous-space uniqueness is not established."]
}
```

Every retained spatial/clock/association seed has one unique stable ID. Preserve
that ID through its refinement. `event_groups` counts independent flyovers,
including all supported later events; harmonics/fragments count once.
`max_event_groups` bounds every retained or discarded evaluated hypothesis.

`complete` requires the declared finite work to finish without unresolved budgets
or missing scope. `pruning_accounted_for` requires every pruning/retention step to
have recorded its limits. `discarded_count` covers all scored retention drops,
including tile, global, coarse and fine merges; `best_discarded_score` is their
maximum higher-is-better score. It is null exactly when no candidate was discarded.
Exact duplicate stable IDs merged while retaining their highest score are not
competing retention drops. Count deduplications separately if needed; association-
only or approximate spatial collapse cannot be treated as exact duplication.
It bounds evaluated parameter points only, not unvisited positions or unperformed
refinements. Missing accounting cannot become zero discards or complete evidence.

## Assessment mappings

W5 also supplies `assessed_mode_ids` for actual completed comparable assessments,
and `candidate_mode_ids` parallel to the returned candidate array. Raw and refined
representations may share a stable ID. Association-only deduplication cannot drop
a distant spatial or clock mode. Failed or unvisited modes remain unassessed.

Every retained mode must be assessed and represented in the candidate array; all
candidate mappings must resolve. Group counts must agree. At least one returned
representation must retain or improve each mode's original score, within numerical
tolerance. These checks prevent a mapping or normalization error from hiding a
better original grid hypothesis.

For this narrow scope, a completed, fully supported core score at the frozen
position/shared-clock/association/event subset and declared model counts as an
assessment. Joint refinement of every retained point is not required. Failed,
unvisited or unsupported core evaluations are unassessed. Unperformed refinements
are explicit limitations, not an inferred continuous score bound. The leading
estimate still needs successful complete measurement/model sensitivity profiles;
all retained seeds remain in the ambiguity comparison. Do not turn on the old
exhaustion/refinement boolean using this narrower meaning.

## Decision interpretation

A supplied finite object takes precedence over an optimistic legacy boolean.
Incomplete scope, lost pruning accounting, omitted modes, inconsistent mappings or
an unbounded near-tied discard yield explicit inconclusive outcomes. Malformed
producer metadata yields `failed / invalid_evidence`.

For a nonempty discard set, the normalized gap is
`(best_final_score - best_discarded_score) / max_event_groups`. It must exceed the
predeclared policy margin: 0.2 support units for the subset score, or 0.5 Hz for
the declared raw robust loss. These engineering margins are not probabilities or
empirical calibration. Score kinds must agree. Every retained candidate also
undergoes the existing position/association near-tie checks against the actual
returned radius. Full measurement/model sensitivity and optimizer/boundary guards
remain mandatory.

An accepted finite object uses policy version `engineering-v4-finite-grid` and
records its grid resolutions, counts, bound, limitations
and `continuous_space_uniqueness: not established` in the decision artifact. A
passing result supports only these declared assumptions. There is no new claim
that an uncalibrated radius guarantees the 1,000 m benchmark target.

Without the new object, the existing compatibility gate stays in force. No old
inconclusive result is silently promoted. Producer agreement and actual integrated
execution remain required before this proposal is considered deployed.
