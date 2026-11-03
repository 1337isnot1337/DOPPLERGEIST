# Independent four-flyover fixture

Generate into a new directory:

```bash
PYTHONPATH=src .venv/bin/python scripts/make_multievent_benchmark.py --output results/four-events-new
```

This emits a 520-second MP3/WAV with four independent emission-domain flyovers,
1,812 trajectory rows spanning twelve opaque flight IDs in three distant regions,
a normal upload request and a separate truth directory. Seed 502013 is fixed.
The first two events have similarly shaped distant decoys; later decoy timings
and geometry differ. All events share one recording clock. Harmonics remain one
flyover. The inverse search physics is never imported by the renderer.

`inputs/request.json` contains only audio, the explicit synthetic recording clock
and CONUS coverage. It contains no event windows, bands, chosen flight IDs, receiver
coordinate or search box. `inputs/flights.csv` is the entire toy flight universe;
build the operator's FlightIndex from all rows without an aircraft allowlist.
Declare it synthetic complete input coverage, not an actual historical receiver
archive. Constant 122 m ground is a synthetic terrain fixture. The true recorder
coordinate and expected associations occur only in `truth/labels.json` and must
be unavailable to the upload backend. The global search grid remains independent
of the recorder. This is a development case, not a new held-out real recording.

Measured generation output is local at `results/w4-four-event-20261103`.
The actual W1 discovery adapter ran with both truth directories masked under
bubblewrap, using the approved unchanged defaults. Post-run evaluation found
**4/4 events, 0 misses, 0 false alarms**, with four distinct harmonic groups. Full
predictions and labels remain separate. A discovery-only result is inconclusive
for location; these counts do not establish association or localization accuracy.

The normal product upload must use all four supported groups, with one shared
clock/location. If a configured event or work budget prevents this, record
incomplete evidence; do not silently keep a smaller subset. The input and generator
hashes are pinned in the generated provenance. MP3 byte identity also depends on
the installed encoder; retain each generated hash rather than overwriting a run.
