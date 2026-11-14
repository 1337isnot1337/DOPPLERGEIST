# Data provenance and attribution

External materials retain their upstream rights and terms. This private checkpoint
does not relicense them, and contains no blanket license for third-party data.

- **Method/source:** colsto, [source video](https://www.youtube.com/watch?v=UytYrhYLOKI).
  The original description says no code or tools are being released. Captions are
  automatically generated and uncorrected. Still frames support parameter reading.
  The source MP4 is excluded from this repository and its release at the user's
  request; its original checksum remains in `data/source/source_manifest.json`.
- **Reference audio:** colsto, [Unknown location - raw audio](https://www.youtube.com/watch?v=4CxVxuMVkMc).
  The decoded WAV is retained for reproducibility; rights remain with its source.
- **Historical flight data:** [ADSB.lol globe_history_2026](https://github.com/adsblol/globe_history_2026),
  daily release `v2026.09.08-planes-readsb-staging-0`. The archive is distributed
  under ODbL; derived Parquet files retain that provenance. The upstream release
  metadata and ingestion reports are included.
- **Aircraft types:** [tar1090-db](https://github.com/wiedehopf/tar1090-db),
  `db/icao_aircraft_types.js`. The downloaded dictionary and normalized CSV are kept.
  [readsb format documentation](https://github.com/wiedehopf/readsb/blob/dev/README-json.md)
  explains trace field decoding.
- **Terrain:** Copernicus DEM GLO-30/GLO-90 public tiles and the EGM96 geoid raster
  from [PROJ data](https://cdn.proj.org/). Tile names/catalogue and cached files are
  retained; consult the providers' applicable attribution and redistribution terms.
- **Independent acoustic benchmark:** Praveen Pathak,
  [Aircraft speed and height from Doppler-shifted sound and flight-track data](https://zenodo.org/records/23424278),
  CC BY 4.0 according to the included Zenodo record. Its 40 recordings, flight
  tracks, measurements and supporting papers are checksum verified.
- **Regional evaluation reference:** the publicly mapped platform at
  [OspreyWatch nest 3916](https://app.osprey-watch.org/nest/3916). Its rounded
  coordinate is not surveyed microphone ground truth.

Original implementation: the Python package, synthetic renderer, tests and
orchestration scripts in this repository were written independently. The local
reference notes from the MIT-licensed
[Hermes implementation](https://github.com/mojomast/hermes-aircraft-doppler-geolocation)
are included as source investigation, not represented as our implementation.
For a source-pinned comparison with the independent MIT-licensed
[Dopplerprint](https://github.com/Hexay/dopplerprint) project, including its
benchmark and search limitations, see [the November 3 review](DOPPLERPRINT_REVIEW_2026-11-03.md).

## Independent archive comparison — 14 November 2026

Issue [#62](https://github.com/1337isnot1337/DOPPLERGEIST/issues/62) now has an
executed native-observation comparison using the [ADS-B Exchange monthly
evaluation samples](https://adsbexchange.com/data-products/sample-data/) and
[ADSB.lol's 1 April 2024 prod-0 release](https://github.com/adsblol/globe_history_2024/releases/tag/v2024.04.01-planes-readsb-prod-0).
The cohort, window and matching tolerance were posted in the issue before
cross-source outcomes. The first 24 sorted confirmed non-jet addresses in the
18:00 snapshot's standard CONUS envelope were selected; this is a source-conditioned
cohort, not a random aircraft sample. The comparison window is 18:00–18:10 UTC.

The daily ADSB.lol archive was streamed once (1,819,279,360 bytes) while retaining
only the selected native traces. Its size matched the release; that older asset
has no provider digest. Raw inputs and per-aircraft results stay local under the
providers' terms. The [readsb format](https://github.com/wiedehopf/readsb/blob/dev/README-json.md)
defines the altitude flags and separate geometric fields used here.

| Observed outcome | Result |
| --- | ---: |
| Selected confirmed non-jet aircraft | 24 |
| Missing second-source daily trace | 3 |
| Daily trace present, no points in the fixed window | 7 |
| Aircraft compared with matching native type | 14 |
| Unique, nonstale native pairs within 0.25 s | 1,068 |
| Horizontal difference: median / 95th percentile / maximum | 0 / 8.65 / 232.22 m |
| Absolute geometric-altitude difference: 95th percentile / maximum | 7.62 / 106.68 m |
| Absolute barometric-altitude difference: maximum | 30.48 m |

Reproduce with the installed project dependencies:

```bash
python scripts/compare_independent_archives.py --root /path/to/new-local-study --acquire
```

Acquisition freezes the cohort before downloading the other provider. Subsequent
offline comparisons can use `--output /path/to/new-comparison.json`; existing
outputs are refused. JSON compression is detected from bytes, because HTTP
delivery may already decompress a file bearing a `.gz` name. Unavailable sources,
empty windows, duplicate/stale epochs and missing/conflicting types remain explicit.
Pressure and geometric altitude are never compared against each other. No temporal
interpolation or fitted clock shift is used.

The pairing rule walks ADS-B Exchange's native order and takes the nearest unused
ADSB.lol sample within the fixed tolerance. These remain different epochs;
horizontal differences include motion. Paired rows are correlated, counts per
aircraft are unequal, and shared feeders or transponder errors are unresolved.
The median agreement does not establish independent measurement accuracy or
source interchangeability. The sample includes ADS-B, ADS-R, TIS-B and MLAT
origins. This is a native-data study, not a source-swap localization or independent
location-error benchmark; those #62 requirements remain open.

The potential [ClickHouse source](https://github.com/ClickHouse/adsb.exposed/blob/main/airplaneslive.sh)
also requires care: the inspected airplanes.live loader retains the snapshot's
`now` timestamp but omits per-position `seen_pos`. That representation alone
cannot establish the last position's observation epoch.
