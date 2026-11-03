# Bird-feed audio benchmarks

The user requested birdwatching feeds as a source of better ambient audio. This
batch uses the normal public HDOnTap embeds for
[Hanover Eagles](https://hdontap.com/stream/204942/hanover-eagles-nest-live-cam/) and
[Dulles Greenway Eagles](https://hdontap.com/stream/216179/dulles-greenway-eagles-nest-live-cam/).
It measures capture quality and automatic event proposals. Neither source has an
established sample-zero UTC or microphone coordinate with a measured uncertainty
in this batch, so neither is a location-accuracy benchmark.

Capture a fresh clip in a new directory:

```bash
python scripts/capture_camera_audio.py --provider hdontap \
  --page 'https://hdontap.com/stream/204942/hanover-eagles-nest-live-cam/embed/' \
  --camera hanover-eagles --duration-s 300 \
  --output results/bird-hanover-new
```

The adapter reads JSON `player-data` from the public embed. It executes no page
JavaScript and uses no account credentials. Unlike the EarthCam metadata, this
JSON does not establish whether an audio track exists; the actual decoder/probe
must confirm that. The capture preserves the source A/V timeline as described in
[the public-camera benchmark](PUBLIC_CAMERA_BENCHMARK.md). Stream query parameters
are omitted from published receipts. Raw media and decoder logs remain local.

## Frozen automatic analysis

The complete five-minute clips are processed at product/main integration
`e227c5db20427f6753a141f369da69a51ab9d4f2`, using the globally approved discovery
defaults, including contrast 2.5. No detector setting is fitted to these clips.
The actual persistent CLI job receives the whole MP3 without selected event
windows, frequency bands, aircraft IDs, camera location or guessed recording
clock. No event-count cap is added by this benchmark.

Hanover captured exactly 300.0 s of decoded audio, SHA256
`79fa9c864151890c3dcf7077271ae6a0fe3167444d803ddfcfd0404835ed1a46`.
Capture wall time was 281.79 s, from 02:03:25 to 02:08:07 UTC on 2026-11-03;
buffered stream content makes these receipt times unsuitable as recorder UTC.
The inspected initial media playlist supplies no program date/time. Its full
16 kHz mono audio measured -53.44 dBFS RMS, peak 0.04228 of full scale and zero
samples at or above full scale. This is digital level, not calibrated sound
pressure. Its RMS is about 32 dB above the earlier Times Square capture.

| Full recording | Decoded duration | RMS dBFS | Proposed groups | Automatic outcome |
| --- | ---: | ---: | ---: | --- |
| Hanover Eagles | 300.0 s | -53.44 | 1 | Recording time required; no coordinate |
| Dulles Greenway Eagles | 300.0 s | -48.93 | 7 | Recording time required; no coordinate |

The whole-clip job proposed one harmonic group from 215.0 to 230.5 s, spanning
78.30–95.29 Hz. Median contrast was 3.358 and observed support fraction 0.857.
The saved ridge descends about 14.42 Hz. This is an unconfirmed acoustic proposal;
no aircraft label, flight association or detection precision/recall is established.
The job returned `needs_input / recording_time_required`, with no coordinate.
It took 5.58 s wall time and 165.59 MiB peak RSS; the source hash was unchanged.

Dulles also captured exactly 300.0 s, SHA256
`ee92c8daee24b77d068ecc29ab2c27b5cc66b86608f723824e1284798989cdb0`.
Capture receipt times were 02:15:28–02:20:16 UTC on 2026-11-03, with 288.34 s
wall duration. Its initial playlist also lacks program date/time. The full clip
measured -48.93 dBFS RMS, peak 0.07285 of full scale, and zero clipped samples.
The actual automatic job took 7.88 s and 204.58 MiB peak RSS, returned
`needs_input / recording_time_required`, and preserved the source hash.

All seven Dulles proposals occur between 249 s and the end of the recording:

| Proposal | Interval, recording seconds | Measured band, Hz |
| --- | --- | --- |
| event-0001 | 249.0–264.5 | 449.63–513.78 |
| event-0002 | 250.5–279.0 | 647.75–1256.36 |
| event-0003 | 252.5–276.5 | 696.23–1246.90 |
| event-0004 | 253.5–272.5 | 774.98–1241.76 |
| event-0005 | 270.5–300.0 | 569.05–782.88 |
| event-0006 | 273.0–291.0 | 1164.05–1436.83 |
| event-0007 | 282.0–300.0 | 138.84–149.75 |

These algorithm-assigned groups are not seven confirmed independent flyovers.
Several tracks overlap. Proposals 2/3, 2/4 and 3/4 have shared-time RMS frequency
differences of 10.72, 15.45 and 17.62 Hz, respectively; the complete pairwise audit
and every plot are retained. No independent source labels establish whether these
are distinct sources, related tones or tracking fragments. The detector settings
remain unchanged and no proposal is silently removed from the saved result.

The separate 12 s Hanover smoke capture measured -51.85 dBFS RMS. The separate
12 s Dulles smoke also decoded completely, measured -61.85 dBFS RMS and had
nonzero audio. These smoke captures are retained alongside the full recordings;
they are not substituted for the five-minute test inputs.

## Source-access outcomes

Every attempted source is retained. The California hummingbird feeder embed
returned HTTP 200 but exposed no JSON `player-data` or usable public stream for
this adapter. No recording or detector test resulted. A separate Cornell
FeederWatch page-access check returned HTTP 403. The other upload verifier owns
Cornell/Hellgate stream capture; this lane does not duplicate that acquisition.
A saved EarthCam Marco Island eagle page advertised no audio; no capture was
attempted from that source. These are source-access outcomes, not acoustic
detection misses.

The capture receipts, source/code hashes, digital audio measurements, exact
automatic requests/results, provenance and plots are in
[the bird-feed receipt directory](bird-feed-20261103/). The missing recording
clock and reference uncertainty prevent reporting location errors at 100, 500 or
1,000 m. Neither an unconfirmed proposal nor abstention establishes real national
geolocation performance.

The HDOnTap adapter and its JSON parsing control passed the complete local suite:
200 tests and six subtests in 63.76 s, with one existing pandas warning. The
adapter source SHA256 and exact command are recorded in `test-receipt.json`.
