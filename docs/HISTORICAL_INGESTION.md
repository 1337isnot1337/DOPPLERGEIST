# Historical derived-Parquet ingestion

`scripts/ingest_adsblol_day.py` normalizes each potentially relevant aircraft's
**full native trace**, then selects aircraft whose gap-split trajectory envelopes
intersect the requested geographic box and time window. It writes the whole
normalized trace for each selected aircraft, including rows outside those bounds.
This preserves altitude calibration, segment boundary derivatives and passages
that cross a query between recorded samples. The conservative continuous bounds
and 30-second gap limit match the default `FlightIndex` build; a differently
configured gap limit requires a new selection. The report records that limit.
New Parquet files also embed the selection box, time interval, aircraft-type scope
and gap limit. `FlightIndex.from_parquet` rejects coverage claims beyond those
limits or an index gap that differs from the selection gap. Older or generic
Parquet files without this metadata still rely on the caller's coverage evidence.

The ingestion report records
`normalization_scope: full_native_trace_before_segment_selection`. Existing output or
report paths raise `FileExistsError`; use a new `--output` name. Historical
Parquet files, indexes and scientific results are not rewritten by this repair.
The normalizer's interpolation, missingness and altitude labels are unchanged.

The actual-script regression streams a two-part tar containing a gzip readsb
trace. Geometric observations lie outside the selected time window, geographic
box, or both. Two retained barometric observations have an independently specified
450 ft / 137.16 m calibration offset: old ingestion loses it and produces 1524 m;
the corrected script produces 1661.16 m with `ellipsoidal_interpolated` labels.
The existing software test checks full-trace retention, altitude labels, source
hashes and refusal to overwrite the result.
No network access or recorder coordinates enter this control.

Older derived Parquet files used pointwise clipping and cannot be assumed to
contain complete segments. Regenerate them before claiming complete query
coverage. The automatic `FlightCache` already normalizes full native traces; this increment
does not change its normalizer/index format, certify bad motion intervals,
establish terrain/altitude datum uncertainty or close the complete #64 gate.
