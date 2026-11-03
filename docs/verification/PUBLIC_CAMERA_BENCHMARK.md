# Public-camera audio benchmarks

The user requested real-audio benchmarks from public webcams, beginning with
[EarthCam Times Square Street Cam](https://www.earthcam.com/usa/newyork/timessquare/?cam=tsstreet).
Capture audio with a new output directory:

```bash
python scripts/capture_camera_audio.py \
  --page 'https://www.earthcam.com/usa/newyork/timessquare/?cam=tsstreet' \
  --camera tsstreet --duration-s 300 \
  --output results/public-camera-timesquare-new
```

The tool uses the page's normal public HLS stream and saves MP3 audio plus a
capture receipt. It records source/playlist hashes, source segment timing if
provided, fetch and capture UTC, decoded duration, media hashes, implementation
hash and the provider's map marker. Transient stream query parameters are omitted
from the receipt. The local decoder log can contain expiring URLs and stays out
of Git.

The provider's map marker is an evaluation reference, with unquantified physical
uncertainty. It must not enter detection or search inputs. Capture UTC and HTTP
Date are receipt times. The tool leaves recording-start UTC unestablished, even
when a broadcaster supplies segment dates, until the first captured audio sample
is bound to that source clock with a defensible uncertainty.

## Preserve the source timeline

An audio-only FFmpeg transcode can discard a delay between the source video and
audio streams. A controlled eight-second MPEG-TS fixture with a tone starting at
two seconds becomes approximately six seconds long, with the tone near zero.
Adding a resampler alone does not restore that offset on the tested FFmpeg 6.1.1.

The capture command keeps source timestamps, rebases the mapped audio/video clock
together, pads timestamp gaps in audio, and copies video packets to a null output.
No video file is saved. Its regression preserves eight seconds and a tone onset
within 5 ms of two seconds. The tool measures decoded MP3 duration rather than
counting codec padding as sound; a duration discrepancy above 50 ms produces
`partial_capture`, preserving the clip and receipt.

## Verification scope

The Times Square metadata advertises audio and supplies a map marker at
40.75941552728725, -73.98521661758423. The inspected live HLS playlist contains no
`EXT-X-PROGRAM-DATE-TIME`, and the sampled video frame contains no visible clock
overlay. Neither a microphone-coordinate error bound nor source-to-receiver
latency was established.

The initial preserved audio-only prototype requested 300 s and produced
295.296 s of decoded audio, SHA256
`fb8be2a1ef326392734eb1a94cd3ab44acd4b9540266f377a5946c8c15b21789`.
Automatic analysis at product source `53fefe67425bb9e83ce1fa4c743500e9843c01d1`
used the complete opaque-named MP3, with no event windows, bands, aircraft IDs,
camera coordinate or recording-clock guess. It found zero supported proposals
and returned `needs_input / recording_time_required`. This is an observed
discovery/abstention outcome, not a labelled aircraft-negative or location test.

A corrected live 12-second capture decoded to exactly 12.0 s. The corrected
five-minute capture started at 01:00:47 UTC and finished at 01:05:34 UTC on
2026-11-03, with exactly 300.0 s decoded audio. Its SHA256 is
`6853afb5dd7967209a5c5adc529c48a582e67112a63ef04d3989970a88d781e4`.
The 286.90 s wall duration includes buffered HLS material, another reason not to
assign capture-start UTC to audio sample zero.

The globally approved discovery defaults were frozen at contrast 2.5 before this
batch was analyzed. Product/main integration `e227c5db20427f6753a141f369da69a51ab9d4f2`
processed the whole corrected clip and the preserved prototype separately. Both
returned zero proposals and `needs_input / recording_time_required`, with no
coordinate asserted. The corrected full automatic CLI job took 3.88 s and
162.0 MiB peak RSS. Its file hash was unchanged after processing. No manual event,
band, aircraft identity, map coordinate or guessed recorder clock entered either
request. The script's earlier 12 s smoke also remains preserved.

The Las Vegas sign camera's public metadata advertises no audio. Its attempted
capture is recorded as `source_has_no_advertised_audio`, not a detector miss. A
separate five-minute Statue of Liberty audio capture is in progress; its complete
outcome will be appended without changing detector settings. Herald Square is
owned by another coordinated capture worker.

Machine-readable captures, exact automatic requests/results, discovery summaries,
provenance and plots are in [the camera receipt directory](public-camera-20261103/).
Source audio and decoder logs remain local. Preserve every capture, processing
failure and inconclusive result; do not select only clips that return a coordinate.
Current-day historical flight archives may not yet exist, which is a separate
data-availability limitation.
