# Compatible subset margin control

This is a bounded logical confidence-policy experiment, not an acoustic/search
benchmark. It supplies perfect controlled fit evidence to the actual unchanged
matching score helper and confidence consumer. No audio, flight archive, location
truth, manual event-selection hint or accuracy evaluation is involved.

Reproduce in a new output file:

```bash
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python \
  evidence/product-20261103/check_compatible_subset_margin.py \
  /new/path/compatible-subset-margin-control.json
```

The artifact records the exact source and harness hashes. Inputs are immutable.
All required coverage, clock, finite accounting, support and full leading profile
controls are satisfied in this abstract fixture. Both rows share the identical
point and clock. Every common event maps to the same flight. The nested subset
only omits the final event; it assigns no contradictory flight.

| All groups | Other groups | Score gap per maximum group | Actual decision |
| --- | --- | --- | --- |
| 4 | 3 | 0.25 | succeeded |
| 5 | 4 | 0.20 | inconclusive / ambiguous_flight_match |
| 6 | 5 | 0.1666667 | inconclusive / ambiguous_flight_match |
| 6 | 6, identical mapping | 0 | succeeded |
| 6 | 5, moved to the discard bound | 0.1666667 | inconclusive / retention_may_hide_alternatives |

One fully supported event contributes at most one support unit. At the same
fixed state, adding a supported event therefore increases this score by at most
one. Dividing that difference by N gives at most 1/N; for N >= 5 it cannot exceed
the conservative 0.2 near-tie margin. An otherwise identical retained N-1 subset
is treated as a different association. A generic score-only discard bound also
cannot distinguish this compatible nested representation from a contradictory or
distant alternative.

This identifies a decision/accounting question for W4/W2 and the primary under
the existing all-supported-event requirement. It does not authorize lowering a
margin, deleting real competitors, relabelling unknown trials or promoting any
historical result. A resolution needs a declared distinction between a provably
compatible nested representation at the same complete model state and a genuinely
competing flight/clock/location hypothesis. Producer identity and exact fitted
state matter; shared flight names alone do not prove dominance. Until owners
resolve that distinction, the recorded conservative outcomes remain authoritative.
