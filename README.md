# DOPPLERGEIST

An independent reconstruction of the aircraft-sound geolocation method described
in [colsto's video](https://www.youtube.com/watch?v=UytYrhYLOKI). The pipeline
measures Doppler curves, compares them with historical ADS-B trajectories, accounts
for terrain and sound travel time, and ranks candidate recording positions.

**The target is automatic MP3-to-location analysis, with 100 m error counting as
success. Independent national real-audio accuracy is not yet verified.** Automatic
event discovery, historical-data indexing, tiled search, partial event matching
and physical sensitivity checks are implemented. The upload service and decision
rules are being integrated in [PR #19](https://github.com/1337isnot1337/DOPPLERGEIST/pull/19).
The configured `run` CLI remains available for research replays. A defensible
recording date or bounded time window is needed to select historical flight data;
an undated audio file does not itself establish that clock.

## Verified results

| Case | Result | Scope |
| --- | --- | --- |
| Independent synthetic two-event audio | 21.89 m error; correct flight pair | Unknown recording start; three candidate regions; truth withheld from search |
| Independent synthetic 60-second event | 40.87 m error; correct flight | Known recording start; manually selected event |
| Original recording, two events | 43.86 m from published public-platform coordinate | Regional search; source-informed windows and bounds; reference coordinate is not surveyed ground truth |
| Original recording, faint 60-second event | 357.47 m from the same reference | Regional search; clock borrowed from the two-event result; does not meet the 100 m target |
| Separate 40-passage acoustic dataset | 33 detections; median speed error 6.85%, slant error 15.37% among detections | Annotation-assisted frequency bands; feature benchmark, not location validation |

These are the original configured checkpoints. The independent clean replay
reproduces the real two-event winner exactly; its synthetic two-event run yields
15.40 m with changed ridge measurements, recorded as `baseline_changed` rather
than silently replacing the 21.89 m result. See the
[complete clean replay evidence](docs/verification/CLEAN_REPLAY.md).

Automatic discovery processed all 40 separate public WAVs without supplied event
windows or bands: 28 recordings produced proposals, 12 did not, with 102 proposals
in total. Those proposals are not certified aircraft detections. The fixed
synthetic detection controls recorded 8 hits, no misses and no false alarms across
14 cases. [All outcomes and source revisions](docs/AUDIO_DISCOVERY.md) remain
available. Automatic national synthetic runs also retain distant competing modes
and inconclusive results in [the integration evidence](docs/verification/INTEGRATION.md).
Scores and finite sensitivity checks are not calibrated location probabilities.

For parallel implementation, start with the [agent task plan](docs/AGENT_TASKS.md)
and [discussion board](https://github.com/1337isnot1337/DOPPLERGEIST/discussions/39).
The [tracking issue](https://github.com/1337isnot1337/DOPPLERGEIST/issues/1) indexes tasks.
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
