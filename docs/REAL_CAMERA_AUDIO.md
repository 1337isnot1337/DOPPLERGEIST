# Actual public-camera recordings

The public capture helper supports EarthCam and HDOnTap without account
credentials. For a new recording, use a new directory:

```bash
python scripts/capture_camera_audio.py --provider hdontap \
  --page https://hdontap.com/stream/204942/hanover-eagles-nest-live-cam/embed/ \
  --camera hanover-eagles --duration-s 300 --output results/new-hanover-capture
```

The existing real bird-feed experiments used whole recordings and frozen
discovery defaults, including contrast 2.5. No event windows, bands, flight IDs
or recorder coordinates entered discovery. All four completed recordings are
listed below; none produced a supported location.

| Public site | Real audio duration | Acoustic proposals | Actual scope/outcome |
| --- | ---: | ---: | --- |
| Hanover Eagles, Pennsylvania | 300 s | 1 | Normal automatic CLI: recording time required; no coordinate |
| Dulles Greenway Eagles, Virginia | 300 s | 7 | Normal automatic CLI: recording time required; no coordinate |
| Cornell FeederWatch, New York | 600 s | 0 | Whole-file intake/discovery; recorder UTC unestablished |
| Hellgate Ospreys, Montana | 600 s | 5 | Whole-file intake/discovery; recorder UTC unestablished |

These are unconfirmed acoustic proposals, not confirmed aircraft counts or a
measured false-positive rate. The overlapping Dulles groups do not establish
seven independent flyovers. Cornell's zero-proposal recording is retained.
The attempted hummingbird source failed during access/setup and produced no
eligible recording. Earlier Times Square limitations remain in
[the public-camera notes](verification/PUBLIC_CAMERA_BENCHMARK.md).

Capture/HTTP wall time is not the recorder clock. Broadcaster segment dates
require a defensible binding to the first captured audio sample. Provider map
markers and public site names have unquantified microphone-location uncertainty;
they are not measured GPS truth and must not enter a localization request.

The four-recording measurements and original attempts remain preserved in
[PR #76](https://github.com/1337isnot1337/DOPPLERGEIST/pull/76) and
[PR #82](https://github.com/1337isnot1337/DOPPLERGEIST/pull/82), including local
raw recordings. Their source-media rights remain with the respective owners.
No raw recording, signed stream URL or new audit package is added here.
