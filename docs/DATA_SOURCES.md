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
