# Complete trajectory support for the synthetic fixture

The optional `full-coverage` fixture adds recorded trajectory samples before and
after every original aircraft segment. It preserves the original 271 samples per
aircraft, including time, position, supplied velocity, identity, type and altitude
basis. It retains all aircraft and distractors. The emitted audio and labels do
not change.

The default `local-segments` fixture remains available. Its short trajectories
can leave alternative event associations without acoustic support. Those cases
must remain unknown. A good leading location does not justify rejecting an
alternative whose model could not be evaluated.

## Added samples

The generator reconstructs each endpoint's ECEF position and velocity. It adds
one-second samples along that endpoint's constant-velocity tangent. It does not
continue the original cubic path or ask the solver to extrapolate. Every
aircraft receives the same predeclared emission interval. The shared endpoint
positions and velocities give C1 joins in the recorded Hermite trajectory;
acceleration can change at a join.

After Parquet serialization, the generator reads the values back. It checks all
original observations, the complete time grid, join errors, and continuous
speed. It also requires finite coordinates and heights between 121 and 20,000
metres above the reference ellipsoid. The fixture ground is 120 metres. Actual
height and speed ranges are recorded for each aircraft in the generation report.
These checks do not certify the performance limits of a real aircraft type.

## Nominal acoustic support bound

The analytic certificate applies to nominal coarse and fine CPA receivers within
the declared 20,000-metre range. It does not claim support for every refined or
perturbed receiver. The existing runtime fit and acceptance gates still check
those evaluations.

Let the audio duration be `D`, right padding be `Q = 300 s`, range be
`R = 20,000 m`, speed bound be `V = 137.2 m/s`, and minimum sound speed be
`c = 338 m/s`. The generator declares

```text
P = ceil((R + V * (D + Q)) / (c - V)) + 2 seconds
emission interval = [-P, D + Q] relative to sample zero
```

For a receiver within `R` of any trajectory point, the distance from the first
point is at most `R + V * (D + Q + P)`. The same bound holds for a sampled CPA
chord, by convexity. Therefore, the first arrival is earlier than sample zero:

```text
-P + (R + V * (D + Q + P)) / c < 0
```

The last arrival is at least `D + Q`, which is later than the audio end. The
strict subsonic speed bound makes arrival time monotone. These endpoint bounds
provide temporal support throughout the audio interval for the stated receiver
domain. They do not establish a unique location, calibrated uncertainty, or
numerical convergence of an acoustic solve.

The continuous speed check uses the quadratic Bezier controls of each Hermite
segment's velocity:

```text
v0, 3 * (p1 - p0) / dt - v0 - v1, v1
```

Their maximum norm bounds the entire segment by convexity. The certificate uses
the actual serialized positions and velocities, rather than endpoint speeds
alone. The generator imports no `aircraft_geoloc` code.

## Replaying the variant

```bash
python scripts/ci_http_replay.py \
  --output results/http-full-coverage-new \
  --events 4 --seed 20261103 \
  --fixture-variant full-coverage \
  --expect-status succeeded --timeout-s 1800
```

The protocol and indexing receipt record the selected variant. The indexer
requires every aircraft's full one-second grid and retains all non-ID values.
The request, producer, scores, thresholds and acceptance policy remain the same.
Any unsupported trial or resource-limit outcome still prevents acceptance.

MP3 bytes and decoded WAV samples remain identical between the variants. The
WAV container includes a libsndfile `PEAK` creation timestamp, so independently
generated WAV files need not have identical container bytes. Preservation checks
allow only that timestamp field to vary; historical files are never rewritten.

This fixture is a finite synthetic development test. It is not evidence of real
national traffic coverage, live acquisition, or accuracy on independent real
recordings.
