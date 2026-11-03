# Independent multi-flyover development fixtures

These cases exercise the requirement to use three, four and more independent
flyovers under one recording clock and location. They are synthetic development
fixtures, not the real field corpus or sealed holdout requested in issue #53.

The generator at `1f0342594bdc7fc7089a075b6dbf26aca9342711` does not import the
production acoustic, Doppler or search implementation. It transports source
oscillators from emission time to receiver time using WGS84 slant distance and
343 m/s still-air sound speed. Curved trajectories have varying headings, speeds
and heights. Noise, stationary tones and second harmonics are present. Model
velocity is independently differentiated and expressed in local ENU coordinates.
The synthetic terrain and geoid establish a declared common height datum.

Every case includes the complete finite synthetic traffic population with opaque
IDs. Two remote regions contain distractor trajectories. Their first two passes
are similar to the true region; later passes differ in timing and geometry. Jets
and unknown types are retained. No receiver coordinate, manual event window,
frequency band or correct flight ID is present in the search request.

## Reproduce or download

```bash
.venv/bin/python scripts/make_multi_event_case.py --events 4 --output data/new-four-event-case
.venv/bin/python scripts/discover_audio.py data/new-four-event-case/inputs/recording.mp3 --output results/new-four-event-discovery
```

Choose `--events 3`, `4` or `6`; the default seed is `20261103`. Existing output
directories are refused. The generated WAV preserves the renderer output; the
MP3 is encoded with FFmpeg/libmp3lame. The manifest records exact media/code
hashes and encoder command/version.

The [checksummed fixture release](https://github.com/1337isnot1337/DOPPLERGEIST/releases/tag/multi-event-fixtures-2026-11-03)
contains all three generated cases. Verify the bundles against `SHA256SUMS`, then
each extracted file against `manifest.json`. The source YouTube MP4 is excluded.

For a blinded product run, expose **only `inputs/`**: MP3, trajectory Parquet,
terrain/geoid rasters, coverage declaration and request with a known synthetic
clock. Build the flight index from that complete Parquet and coverage declaration.
Do not expose `truth/`, `renderer/`, `generation.json` or the generator source to
the search process. Join `truth/labels.json` after predictions are frozen. The
initial discovery checks below did not supply labels, but did not assert a
filesystem isolation boundary.

## Frozen discovery results

The first runs used unchanged default settings, including contrast 2.5, with no
retuning after generation or after observing results. Labels were read afterward
for interval matching at IoU 0.3; harmonics count once.

| Independent flyovers | Duration | Groups found | Hits / misses / extra groups | Runtime |
| --- | --- | --- | --- | --- |
| 3 | 740 s | 3 | 3 / 0 / 0 | 8.26 s |
| 4 | 960 s | 4 | 4 / 0 / 0 | 9.30 s |
| 6 | 1,400 s | 6 | 6 / 0 / 0 | 13.09 s |

[Complete measurements, plots and receipts](../evidence/verification/multi-event-20261103/summary.json)
retain every generated case. Recorded peak RSS was 343,792 / 1,648,608 / 398,472
KiB respectively; the four-event outlier is preserved without an established
causal explanation. The generator's analytic tests check both approaching and
receding constant-velocity Doppler frequency, propagation delay and invalid
arrival ordering. The combined clean Python 3.14 suite passed 125 tests in
36.60 seconds, with one existing pandas future-dtype warning.

These results establish event discovery on these fixtures. Flight associations,
location error, ambiguity and actual accepted/inconclusive decisions require the
subsequent full pipeline run, reporting 100/500/1,000 m thresholds. No location
success is claimed from detection counts or from known synthetic terrain alone.
