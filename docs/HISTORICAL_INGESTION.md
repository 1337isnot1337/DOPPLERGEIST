# Historical derived-Parquet ingestion

`scripts/ingest_adsblol_day.py` keeps its existing geographic/time/type selection
and column schema. It first rejects aircraft with no requested raw points, then
normalizes each retained aircraft's **full native trace** before selecting output
rows. Geometric-minus-barometric calibration samples outside the selected box or
clock window remain available to the existing altitude normalizer. Output rows
still obey the requested bounds; the normalized full trace is not written.

The ingestion report records
`normalization_scope: full_native_trace_before_row_selection`. Existing output or
report paths raise `FileExistsError`; use a new `--output` name. Historical
Parquet files, indexes and scientific results are not rewritten by this repair.
The normalizer's interpolation, missingness and altitude labels are unchanged.

The actual-script regression streams a two-part tar containing a gzip readsb
trace. Geometric observations lie outside the selected time window, geographic
box, or both. Two retained barometric observations have an independently specified
450 ft / 137.16 m calibration offset: old ingestion loses it and produces 1524 m;
the corrected script produces 1661.16 m with `ellipsoidal_interpolated` labels.
The test checks retained rows, source hashes and refusal to overwrite the result.
No network access or recorder coordinates enter this control.

This repairs the historical script boundary identified by the #64 audit. The
automatic `FlightCache` already normalizes full native traces; this increment
does not change its normalizer/index format, certify bad motion intervals,
establish terrain/altitude datum uncertainty or close the complete #64 gate.
