# Physical verification follow-up

These receipts preserve two real-recording replays and a second complete
automatic MP3 run. They do not establish independent national real-audio
accuracy. No source recording or large trajectory dataset is added here.

## Results

| Run | Source tree | Result | Time |
| --- | --- | --- | --- |
| Original regional configuration, released Parquet | `043eec047e89cbf546d95a463faebab982e785a9` | Same fitted location, clock and flight identities as the frozen baseline; score differs by one floating-point ULP | 50.912 s |
| Same configuration, freshly normalized raw traces | `043eec047e89cbf546d95a463faebab982e785a9` | Entire best row exactly matches the released-input replay | 42.252 s |
| Automatic complete synthetic MP3, all CONUS tiles | `6e284fdcc92f10e151cda00181bed8880308acf1` | `inconclusive / ambiguous_locations` | 226.108 s |

Both regional replays give the same 43.858471 m distance from the published
[nest-platform reference](https://app.osprey-watch.org/nest/3916). The reference
has four decimal places and does not establish a surveyed microphone position.
The replays retain the historical manual event windows, frequency bands,
regional bounds and downstream known-jet filter. No recording clock is supplied;
the shared two-event fit estimates it. These are historical reproduction checks.

The second automatic run ranks the true synthetic association first. Its
post-search position error is 0.643593 m. The distant competing association is
approximately 1,046 km away, with only 0.021467 Hz/event loss separation under
the policy used for this run. The returned outcome remains inconclusive.

For comparison with the updated project criteria, both regional point estimates
and the synthetic leading candidate are within 100, 500 and 1,000 m of their
respective references. This point-error comparison does not turn the automatic
candidate into an accepted estimate or make the real replays independent tests.
The recorded historical decision policy retains its original 100 m target.

## Complete automatic path

The real CLI job manager copied the MP3, decoded all 1,180 seconds, discovered
two independent event groups, loaded all seven opaque-ID trajectories, searched
all 19,278 CONUS tiles, refined candidates and ran the decision policy. No event
windows, frequency bands, true flight IDs or receiver coordinates were supplied.
The declared clock is the exact synthetic generator epoch.

Search took 211.544 s and reached 283.051 MiB process peak RSS. All tiles finished,
with no tile or refinement failure. The final candidate list has 111 rows.
Coverage refers to this complete finite synthetic population. A completed finite
grid does not establish continuous-space mode recall or real archive coverage.

The implementation hashes and input hashes match the saved provenance. Truth
and the opaque identifier map were read only for post-search evaluation. This
run did not enforce filesystem isolation from those evaluation files.

The leading candidate exposes a 42.841986 m altitude-only sensitivity radius.
Its full 21-profile duplicate ranks second by approximately 2.99e-13 score units
and reports an unestablished ellipsoidal terrain datum. Therefore this radius
is not a complete uncertainty bound. The artifacts preserve both rows and their
limitations; the product integration finding is recorded in
[PR #19](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19#issuecomment-6592780368).

The executed local commit is `87143f5db99454f14541d736be6e5338b5d2ee76`.
The published snapshot is
[`98b14955741f32cf6fb7592bbf44df050a5bd309`](https://github.com/1337isnot1337/DOPPLERGEIST/commit/98b14955741f32cf6fb7592bbf44df050a5bd309).
Both have exactly the same Git tree. Commit metadata and parents differ.

With restored inputs and paths adjusted to the local checkout, the automatic
invocation is:

```bash
PYTHONPATH=/path/to/pinned-checkout/src python -m aircraft_geoloc.cli analyze \
  /path/to/synthetic-complete.mp3 \
  --start-utc 2026-09-21T14:13:20Z \
  --end-utc 2026-09-21T14:13:20Z \
  --time-source 'Controlled independent synthetic generator epoch; exact-clock integration regression' \
  --config /path/to/operator-v2.json \
  --jobs /path/to/new-output-directory
```

The saved operator, request, index receipt, intake, discovery, search, refinement,
decision, result and provenance are in `automatic-synthetic-87143f5/`. All original
tile checkpoints remain in the local job directory; the committed search report
and manifest preserve the completion result. The earlier automatic result in
`automatic-synthetic-98081e7/` remains unchanged.

## Raw-data replay

The fresh normalization scans all 79,044 source traces and 106,492,920 raw
samples from the two checksummed daily archive parts. A declared broad regional
box selects aircraft by any observed point. The normalizer keeps each selected
aircraft's full trajectory, all times and all types, including out-of-box rows.
It does not filter by flight identity or recording time.

The resulting Parquet has 12,609,152 rows from 6,561 aircraft and is 573,526,453
bytes. Its SHA-256 is
`38d1ee70f6f7b92957d5301e57e7fbf4c74e702438a8438673acbd4c3a08af29`.
The input preserves 73,452 rows with at least one missing velocity component.
The configured replay exercises segment-local velocity inference for 2,478 east,
2,478 north and 1,632 vertical components. Measured zeros remain measured zeros.

The production normalizer still omits nonnumeric altitude samples. The receipts
count those omissions, retain altitude provenance and record duplicate times.
The regional selection and original downstream jet filter remain explicit.

The reproduction script, declared selection, source hashes, code hashes and
normalization report are in `real-fresh-raw/normalization/`. The configured
replay outputs and exact comparison are in `real-fresh-raw/`; the released-input
comparison is in `real-release-parquet/`. The large regenerated Parquet and raw
trace-selection ledger remain local, reproducible intermediates.

The archived normalization script preserves the executed workspace paths. For a
new replay, set its `OUTPUT`, `ROOT` and `ORIGINAL` globals to a new experiment
directory, the pinned source checkout and the restored input checkout. Rebase
the part paths in a copy of `raw-restoration.json` and verify both recorded
SHA-256 values before running it. Do not execute it inside this evidence folder
or overwrite the recorded receipts.

## Tests and remaining acceptance work

The combined executed source passes **158 tests, with zero skipped**, in 29.63 s.
This includes all four independent decision controls from
[PR #36](https://github.com/1337isnot1337/DOPPLERGEIST/pull/36). The test log and
JUnit XML are saved alongside this file. One existing pandas dtype warning remains.
The focused radius-fix suite passes 22 tests; its XML is also preserved.

These checks verify complete execution, source integrity, historical reproduction
and honest abstention. They do not complete the updated acceptance requirement.
That still needs an automatic upload using at least four supported independent
flyovers, an auditable assessment of competitive retained modes, and independent
real-recording evaluation with defensible clock and microphone references.
