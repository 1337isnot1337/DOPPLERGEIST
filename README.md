# DOPPLERGEIST

An independent reconstruction of the aircraft-sound geolocation method described
in [colsto's video](https://www.youtube.com/watch?v=UytYrhYLOKI). The pipeline
measures Doppler curves, compares them with historical ADS-B trajectories, accounts
for terrain and sound travel time, and ranks candidate recording positions.

**The target product is an MP3 upload followed by automatic event discovery and
location estimation, with 100 m error counting as success. That product is not
implemented yet.** The current CLI requires selected event windows, frequency
bands, flight data, and search configuration. A recording date or bounded time
window is also needed to select historical flight data; an undated audio file does
not itself provide that information.

## Verified results

| Case | Result | Scope |
| --- | --- | --- |
| Independent synthetic two-event audio | 21.89 m error; correct flight pair | Unknown recording start; three candidate regions; truth withheld from search |
| Independent synthetic 60-second event | 40.87 m error; correct flight | Known recording start; manually selected event |
| Original recording, two events | 43.86 m from published public-platform coordinate | Regional search; source-informed windows and bounds; reference coordinate is not surveyed ground truth |
| Original recording, faint 60-second event | 357.47 m from the same reference | Regional search; clock borrowed from the two-event result; does not meet the 100 m target |
| Separate 40-passage acoustic dataset | 33 detections; median speed error 6.85%, slant error 15.37% among detections | Annotation-assisted frequency bands; feature benchmark, not location validation |

The real two-event result has been reproduced with the faster CPA implementation
at the same winning point and score. No blind nationwide real-audio run has been
completed. Scores are ranking statistics, not calibrated probabilities.

For parallel implementation, start with the [agent task plan](docs/AGENT_TASKS.md)
and [tracking issue](https://github.com/1337isnot1337/DOPPLERGEIST/issues/1).
Then read [the implementation handoff](docs/HANDOFF.md),
[current evidence](docs/PROGRESS.md), and [the reconstructed methodology](docs/METHODOLOGY.md).
Readable reports and plots are checked into [evidence/results](evidence/results).
Large inputs and complete outputs are in the
[checkpoint release](https://github.com/1337isnot1337/dopplergeist/releases/tag/checkpoint-2026-11-02).
See [artifact download and verification instructions](docs/ARTIFACTS.md).
The YouTube MP4 is intentionally excluded.

## Install and run

Python 3.11+ and `ffmpeg` are required. Python 3.14 was used for this checkpoint;
the recorded dependency versions are in [evidence/runtime.json](evidence/runtime.json).
See [clean installation, pinned dependencies and selective restoration](docs/SETUP.md)
for a fresh checkout.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/make_synthetic_cases.py
.venv/bin/aircraft-geoloc run data/synthetic/two-events.json --output results/replay-two-events
.venv/bin/aircraft-geoloc run data/synthetic/known-time-minute.json --output results/replay-known-minute
```

After restoring the release data, reproduce the real regional case with:

```bash
.venv/bin/aircraft-geoloc run data/source/reproduce-local.json --output results/replay-reference
```

Use a new output directory to preserve the original evidence. Historical reports
retain their original paths and implementation hashes; those paths are provenance,
not requirements for a new checkout. Configuration paths resolve relative to the
configuration file.

## Inputs and model

Canonical CSV/Parquet columns are `flight_id,time_s,lat,lon,alt_m,typecode`.
Timestamps are Unix seconds or UTC ISO strings; heights and speeds use SI units.
Optional `east_mps,north_mps,up_mps` provide flight velocity. KML `gx:Track` and
readsb/ADSB.lol traces have importers. Track gaps are split; extrapolation is
disallowed. Known-jet exclusion is configurable through the supplied type database.
The faint reference event requires retaining jets.

For aircraft position **x** at emission time tau and receiver **o**, the solver uses:

```
t_received = tau + norm(x(tau) - o) / c
frequency = f0 * c / (c + dot(velocity(tau), x(tau)-o)/norm(x(tau)-o))
```

Positive range rate means the aircraft is receding. All events share one recording
clock adjustment; rest frequency is fitted separately for each event. Scoring
uses either spectrogram contrast along the predicted curves or measured-ridge
residuals. Terrain and aircraft heights must use a consistent vertical datum;
the supplied real configurations include a geoid correction.

## Sources

This is independently written code, not a release from the video author.
External data retain their own licenses and attribution requirements, described
in [data provenance](docs/DATA_SOURCES.md). No blanket license for those assets is
implied by this repository.
