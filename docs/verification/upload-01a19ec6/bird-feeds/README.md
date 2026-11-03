# Cornell public bird-feed verification

The user requested tests from birdwatching feeds. These are two complete,
predeclared one-hour recordings from Cornell Lab FeederWatch. They are public
institutional outdoor audio, not independently labelled aircraft positives.
The official [source page](https://www.allaboutbirds.org/cams/cornell-lab-feederwatch/)
identifies the Treman Bird Feeding Garden, Axis P1488-LE camera and ETS ML1-WPW
microphone. The public embed points to YouTube video `x10vL6_47Dw`.

| Case | Decoded duration | RMS | Peak | Automatic outcome |
| --- | ---: | ---: | ---: | --- |
| Nighttime HLS hour | 3599.9985 s at 4 kHz audit | -59.45 dBFS | -25.28 dBFS | 11 unconfirmed proposals; real acquisition failed, Nov3 archive unavailable |
| Prior-day daylight DVR hour | 3599.9985625 s at 16 kHz audit | -42.08 dBFS | -1.12 dBFS | 4 unconfirmed proposals; actual full upload in acquisition at this checkpoint |

Both contain finite, nonzero decoded audio and no near-full-scale samples.
The native night source is stereo with channel correlation 0.9999165; mono
conversion does not explain its low level. RMS/peak summaries use the stated
sample rates and are not source SNR measurements or aircraft labels.

## Independent source-clock checks

For night, the visible clock reads Nov2 20:04:04 America/New_York while its HLS
segment declares Nov3 01:04:05.092 UTC. Measured first audio/video PTS alignment
places audio zero inside the conservative request window 00:59:38–41 UTC.
The actual whole-hour HTTP job `4f96b679d5bd4220b8305005c51d2d1b` ran frozen
integration `5291dab`, with no synthetic index mounted. It failed explicitly at
real acquisition, and downloaded-original hashes matched. All 11 proposals,
coverage, request and terminal failure remain in `night/`.

For daylight, the hour was selected **six hours before an observed live head**
before listening or event extraction. All 720 five-second public audio fragments
returned their exact requested sequences 4072021–4072740. Three same-sequence
video frames show 15:47:49,15:49:49 and16:47:44 local at nominal offsets 0, 120
and 3595 s. Video/audio first PTS differ 0.016508 s. Broadcaster HLS sequence/PDT
mapping corroborates the camera clock with an approximately 1.1 s offset. The
normal request therefore uses Nov2 **20:47:48–51 UTC**, rounded outward.

Every source AAC packet was audited before accepted encoding. Maximum adjacent
fragment boundary discrepancy is 1.003 microseconds at decimal timestamp
precision; all internal packet timing is continuous to that precision. The
158,759,936 source samples at 44.1 kHz predict 3599.99854875 s; the final decoded
16 kHz MP3 differs by less than one output sample. Explicit per-fragment packet
durations repair misleading live-fragment container duration metadata. The
accepted encoder emits no warnings. Complete hashed fragment and packet
receipts are gzip-compressed in `daylight/`, with source clock frames.

These are engineering source-clock envelopes. Absolute camera calibration is
not independently measured; download/upload/file times are never substituted
for recording time. Source identity, location, bands, event times and flight IDs
do not enter normal analysis. The runtime hides the host home and evaluation
files. Public source/site evidence remains outside it.

## Actual daylight pipeline and scope

The frozen source `23632c32e6e904874ddabc8c58da00f774edc806` combines observed main
`fcbe513` and published product `f5c59a4` in an owned integration branch. It passes
**245 tests plus 6 subtests** with zero skips, in 102.63 s. The immutable source
archive hash is adjacent; the published branch is
`worker/bird-daytime-01a19ec6`. No producer settings are tuned to this source.
The normal operator uses real online ADSB.lol/Copernicus inputs, 2000 m coarse
spacing, 100 m fine spacing, 5 refinement finalists and top 30 retained candidates;
there is no default event-count cap or synthetic flight-index override.

Job `1b4e1e1ee1164ab4b019e9637371cabe` consumes the whole MP3, CONUS and the
independent clock window. Four automatically proposed groups occur at 398.5–412.5,
1002.5–1019, 2720–2735.5 and2983.5–3000 s. They remain unconfirmed. Both published
Nov2 archive parts (2,979,275,776 bytes) have downloaded with matching SHA256
receipts. The default global daily index is being built; terminal localization,
artifact roundtrip and any error evaluation are **pending** at this checkpoint.
A watcher cancels only this job if free space falls below 15 GiB and preserves
that explicit resource outcome. No successful location is claimed here.

The official public institution and garden are documented, but surveyed
microphone coordinates and a defensible numeric spatial uncertainty are not.
No address/map marker will silently become exact microphone truth. Any later
location-error comparison must state that limitation and report 100/500/1000 m
thresholds separately from an accepted product decision.

`retained-failures.json` lists every bounded acquisition/encoding/runtime failure,
including the rejected live-sequence probe and warning-producing first encode.
Original source media, signed URL paths/queries, playlists and private logs stay
ignored local. No original YouTube MP4 or media fragments are committed.
