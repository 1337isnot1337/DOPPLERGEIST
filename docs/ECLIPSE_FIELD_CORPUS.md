# Eclipse Soundscapes field-audio screening

This is a scanner-only collection from public Eclipse Soundscapes datasets on Zenodo; [ESID 890](https://zenodo.org/records/22084065) is one example. Each selected source supplies a site metadata file and timestamp-named AudioMoth WAV audio. The screen uses the earliest 600 continuous seconds on 8 April 2024, selected before listening or observing scanner results. Separate sites are selected in Zenodo publication-search order; this is a convenience sample, not a random or representative population sample.

Each real source is decoded to an MP3 and scanned with automatic discovery only. No ADS-B data, flight IDs, location estimates, event hints or geographic bounds enter the scanner. Site metadata is kept in a separate `truth/` directory; a publisher-supplied coordinate is a location label, not a surveyed accuracy guarantee. A descending tone is a moving-tone proposal, not proof of an aircraft.

The first run selected 50 sites: 45 clips scanned, five acquisitions failed, 18 produced proposals and 27 produced none. A second non-overlapping run selected another 50: nine clips scanned, four produced proposals, five produced none, and 41 acquisitions failed with HTTP 503 responses. All 22 proposal-bearing sites have publisher coordinates; 21 report a time-chime setup, while one says its clock needs manual setting. Visual review found descending tonal bands in at least one proposal from 20 of the 22 clips; the other two had weak or discontinuous support. Individual position and clock errors are not quantified, and the sources of the tones are unconfirmed. These are candidates for further review, not validated aircraft geolocations. See the portable [first-batch manifest](../benchmarks/eclipse-field-screen-20261103.json) and [second-batch manifest](../benchmarks/eclipse-field-screen-batch2-20261103.json). Audio and large archives are not committed.

The 41 initially failed cases in the second batch were retried separately:
36 scanned and five did not produce a successful scan, with 17 proposal-bearing clips and
19 without proposals. The [retry table](../benchmarks/eclipse-field-retry-20261103.csv)
records all 41 final outcomes, source links, audio hashes and review notes;
the earlier failure records remain in the original second-batch manifest.
Across both disjoint 50-site batches, 90 clips scanned and ten did not produce
a successful scan. The scanner produced proposals in 39 of the 90; a visual review
selected 24 site-labeled clips with clear descending tones as
[candidate leads](../benchmarks/real-candidates-known-site-20261103.csv).
Their aircraft identities remain unconfirmed. A separate
[unknown-exact-location shortlist](../benchmarks/real-candidates-unknown-point-20261103.csv)
contains five scanner-only leads, of which one is ambiguous and one is an
edited compilation. These are not 29 validated geolocation benchmarks.

[Project instructions](https://eclipsesoundscapes.org/my-audiomoth-location/)
ask for registration at the recorder but permit registering as close as
possible later when cell service is unavailable. The project also asks
participants to set clocks using a [time chime](https://eclipsesoundscapes.org/field-researcher/).
[AudioMoth documentation](https://www.openacousticdevices.info/config-app-guide)
describes possible clock drift absent regular GPS correction. None of these
instructions establishes the actual position or clock error for an individual
clip, and generic device drift is not a per-recording uncertainty bound.

The initial collector called a filename-derived timestamp `clip_start_utc` and used a generic clock note that mentioned a time chime even for manual-clock sites. Those original run records are preserved, but neither statement independently verifies recording time. The current catalog reports the timestamp as a filename claim and reads each site's publisher-reported clock setting separately. Long compressed WAV members are read only far enough for the clip; their publisher full-file SHA-512 is recorded but not verified. A SHA-256 of extracted PCM and a hash of the resulting MP3 are retained for each successful clip.

The research scripts require `ffmpeg` and the optional `remotezip` package (the recorded run used version 0.12.6), in addition to the project's normal Python dependencies. To replay the fixed first-batch selection without relying on a changing search order:

```bash
mkdir -p results/eclipse-field-replay
cp benchmarks/eclipse-field-selection-20261103.json results/eclipse-field-replay/selection.json
PYTHONPATH=src python scripts/collect_eclipse_audio.py --root results/eclipse-field-replay --sites 50
python scripts/export_eclipse_audio.py --root results/eclipse-field-replay
```

To select additional, non-overlapping sites, provide `--exclude-selection` for each earlier `selection.json` and `--exclude-site` for any other site IDs. Selection, scan results, failures and separate site metadata are written incrementally; the export creates a dated snapshot. Never use the reference coordinates to restrict a geolocation search. Source licensing and redistribution terms remain those of each Zenodo record.

The current collector stops after an HTTP 429 or 5xx source failure and records remaining sites as not attempted. The second historical batch predates that safeguard, so its 41 HTTP 503 failures are retained as acquisition failures, not scanner negatives.
