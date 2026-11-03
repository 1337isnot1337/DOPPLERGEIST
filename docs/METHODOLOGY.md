# Method reconstructed from the supplied video

The original implementation is unavailable. This is an independent reconstruction
of its described algorithm, with source observations separated from implementation
choices. The source is the supplied 1751.53-second MP4 and its timestamped captions.
Its SHA256 and local path are in `data/source/source_manifest.json`.

## Source observations

| Source time | Operation |
| --- | --- |
| 02:42-04:13 | Obtain an entire day's ADS-B flights; remove known jet aircraft using ICAO aircraft type designators, retaining unknown types. The shown client is `stiles/pyfr24`. |
| 04:18-07:48 | Lay a 200 m candidate grid; calculate the 3-D closest approach and the arrival time of its sound. The initial broad radius is 10 km. |
| 08:28-11:10 | Fit approximate constant-velocity Doppler shapes to bound speed and closest slant distance. Use generous ranges because actual aircraft turn and accelerate. |
| 10:35 frame | Event 1: 130-154 m/s, 4300-7800 m slant. Event 2: 88-110 m/s, 1390-4690 m slant. The measured separation is about 920 s. |
| 12:12 frame | Reject candidates with additional intervening propeller flyovers closer than max(event-1 slant, event-2 slant). No distance multiplier. This is a hearing heuristic, not a guaranteed audibility law. |
| 14:10-18:09 | Model exact curves from each actual trajectory, including sound travel time. Use radial velocity at emission, not reception. |
| 18:14-20:10 | Score spectral brightness along model curves. Sweep uncertain rest frequencies and a common placement of event 1. Event 2's placement remains locked to the flight-derived time difference. |
| 20:12-22:39 | Expand to 100 m scoring resolution, keep the best point per flight combination, then refine the leading geometry. |
| 22:53-24:11 | Known-time one-minute alternative: search relevant flight segments, score against a manually traced faint ridge rather than brightness. The stated known time is 20:37 UTC. |
| 26:09-28:09 | Assess persistence through finite high-pass attenuation, masking sounds and a phone link; discuss editing and stronger noise reduction. These demonstrations are not universal guarantees about arbitrary filters/codecs. |

The linked source audio is one hour long. Its prominent curves appear near 2156 s
and 3076 s; some source-video interfaces use a timeline 3600 s larger. Captions are
automatic and can contain errors; parameter values above were read from frames.

## Physical model and sign convention

Let the stationary receiver be o, aircraft position x(tau), velocity v(tau), and
sound speed c. Positions are three-dimensional WGS84 ECEF. All heights must first
be put in a consistent vertical datum.

```
r(tau) = norm(x(tau) - o)
u_r(tau) = dot(v(tau), x(tau)-o) / r(tau)   [positive when receding]
t = tau + r(tau)/c
f(t) = f0 * c / (c + u_r(tau))
```

The solver inverts the arrival-time equation. Replacing tau with receiver time or
adding one constant delay changes the curve's shape and is not equivalent.

Closest approach minimizes r(tau), and its delayed CPA is tau_CPA+r_CPA/c. For
initial filtering the code calculates segment-wise minima of a densely sampled
trajectory; full scoring evaluates a cubic Hermite trajectory directly. Imported
flight gaps are split and no extrapolation is permitted.

## Reproduction choices and limits

- An equal-area CONUS grid (EPSG:5070) replaces the video's unspecified grid CRS.
  Its scale is not exactly one everywhere; corridor construction includes padding.
- Numeric spectrogram contrast removes stationary tonal baselines and normalizes
  the noise floor. The video does not specify its exact brightness normalization,
  FFT window or plotting color transformation; numerical score magnitudes therefore
  are not expected to equal its reported scores.
- Automatic tracing uses a bounded-slope Viterbi path, with optional supplied manual
  ridge CSV. This replaces manual visual measurements while retaining inspectable
  diagnostic plots. A forced best path is not automatically accepted as a detection.
- The rest tone may refer to a chosen harmonic, not necessarily the actual engine
  fundamental. It must remain consistent within that event.
- The common timing adjustment is selected by combined event score. Every event
  keeps its actual absolute flight clock; there is no independent second-event shift.
- Historical aircraft data uses the open ADSB.lol archive, not the video's paid
  Flightradar24 archive. Coverage, timing and geometry can differ between providers.
- Readsb's GNSS altitude is ellipsoidal. Its documented geometric field is used,
  with explicitly labelled interpolation or barometric fallback. Ground DEM heights
  receive a geoid correction where configured. Geoid model differences and GNSS/
  pressure altitude errors remain uncertainty sources.
- Constant sound speed, stationary microphone, source tone stability and adequate
  timestamp/sample-rate accuracy are assumptions. Wind, refraction, terrain
  obstruction, microphone response and changing propeller RPM can break matches.
- Silence is a configurable heuristic: missing ADS-B or a quieter aircraft can
  invalidate a hard rejection. Its separate counts are retained for ablation.
- Raw scores are ranking statistics, not calibrated location probabilities.

## Verification layers

1. Analytic constant-velocity solution versus the numerical retarded-time solver,
   including full Unix timestamps and no extrapolation.
2. Filter tests for silence, incorrect offsets, known jets, unknown types and gaps.
3. A scoring regression proving that a mismatched second event cannot get its own
   time adjustment; noise-only audio must not produce an accepted event.
4. An independent emission-domain audio renderer produces the synthetic cases;
   their ground truth is held out of the entire search.
5. The original source audio is measured and checked against historical tracks.
6. A separate 40-passage research dataset checks acoustic feature recovery against
   ADS-B reference speeds and ranges. It is not treated as an exact-location test
   because an explicit recorder coordinate and audio-sample clock are not supplied.
