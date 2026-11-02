# Aircraft-acoustic geolocation reproduction

This project reconstructs the method in [colsto's video](https://www.youtube.com/watch?v=UytYrhYLOKI):
measure aircraft Doppler curves, constrain flight geometry, account for sound travel
time and terrain, and score candidate recording positions against actual ADS-B tracks.

**Status:** the complete local pipeline is implemented. Independent synthetic
audio-to-location runs recover the correct flights with 21.9 m error for two events
with unknown recording start, and 40.9 m error for a known-time one-minute event.
Real-world location verification is in progress; these synthetic errors do not
establish the video's real-world or national-search claims.

## Run

Python 3.11+ and `ffmpeg` are required. The current local environment is `.venv/`.

```bash
python -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/python -m pytest -q
.venv/bin/python scripts/make_synthetic_cases.py
.venv/bin/aircraft-geoloc run data/synthetic/two-events.json --output results/two-events
.venv/bin/aircraft-geoloc run data/synthetic/known-time-minute.json --output results/known-minute
```

The generator writes truth separately. The search never loads it. Its audio
renderer transports an oscillator from emission time into receiver time without
calling the search's propagation model. Three widely separated regions contain
plausible flights; a known jet tests classification. Results include a ranked list
of points, the best point per flight combination, measured spectra, physical-model
overlays, filter counts, input hashes, and timings.

## Inputs and physical model

A JSON configuration identifies an audio/video file, flight-data files, event
windows/bands, terrain, a projected grid, filter tolerances and scoring settings.
Event speed, slant-distance and rest-frequency ranges may be set explicitly or
estimated from the measured curve. The video likewise uses manual event selection
and generous geometry bounds; fully unattended event discovery is not assumed.

Canonical CSV/Parquet columns are `flight_id,time_s,lat,lon,alt_m,typecode`.
Timestamps are Unix seconds or UTC ISO strings; heights and speeds are SI units.
Optional `east_mps,north_mps,up_mps` supply actual flight velocity. KML gx:Track
and readsb/ADSB.lol traces have importers. Gaps are split instead of interpolated
through. Unknown aircraft types are retained; only positively identified jet types
are removed. Readsb geometric-altitude fields and barometric fallbacks are labelled.

For aircraft position **x** at emission time tau and observer **o**, the code solves

```
t_received = tau + norm(x(tau) - o) / c
frequency = f0 * c / (c + dot(velocity(tau), x(tau)-o)/norm(x(tau)-o))
```

Range rate is positive for a receding aircraft. A shared recording-clock adjustment
is fitted across all events; each event can adjust its rest frequency, but a second
event cannot shift independently in time. Scoring uses either normalized spectral
brightness along the predicted curves or residual against a measured ridge.

DEM rasters are sampled in their actual CRS. An optional geoid raster converts
orthometric ground height to the ellipsoidal datum used by GNSS aircraft heights.
Without a geoid, both aircraft and observer must use one common height datum.
Constant terrain is available for explicit controlled tests, not an implied DEM.

## Evidence and next work

- [Current checkpoint](docs/PROGRESS.md)
- Source video captions, metadata, source frames and audio: `data/source/`
- Real paired research data: `scripts/fetch_research_data.py`
- Open historical ADS-B data: `scripts/fetch_adsblol_day.py YYYY-MM-DD`, then
  `scripts/ingest_adsblol_day.py YYYY-MM-DD`
- Local reports: `results/synthetic-two-events/` and `results/synthetic-known-minute/`

External recordings and large datasets stay outside Git. Downloaded research data
is checksum verified. The first real reproduction uses an area identified in the
video to validate data alignment before attempting a blind national search.
