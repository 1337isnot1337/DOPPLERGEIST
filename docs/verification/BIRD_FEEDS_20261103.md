# Public bird-feed tests, 2026-11-03 UTC

The user requested tests from birdwatching feeds. Two predetermined public live
sites were captured for 600 s each and passed through unchanged, whole-file
intake/discovery. No event windows, frequency bands, true flight IDs, coordinates
or time hints were supplied. Input copies had opaque SHA-derived names.

| Site | Decoded duration | Proposals | Runtime | Peak RSS | RMS / peak dBFS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cornell FeederWatch | 600.000 s | 0 | 1.813 s | 152.94 MiB | -47.43 / -17.77 |
| Hellgate Ospreys | 600.000 s | 5 | 2.699 s | 183.74 MiB | -30.03 / -6.62 |

Every decoded sample was finite; neither clip had samples at or above full scale.
These measurements establish usable decoded audio, not aircraft SNR or source
identity. Cornell's zero is retained. Hellgate's five are acoustic proposals,
not five confirmed aircraft. Unlabelled recordings do not establish recall or a
false-positive rate.

All discovery used producer `0461e9e43903706e26eb93436c418171f56584f9`, approved
default `min_contrast=2.5`, and identical source digest
`c6a8034375c2448c292372a982434dd9155b6deac9466d1170ba71ef651c3e14`.
No settings were tuned on these clips. Both sites were on nighttime camera view.

## Sources and actual signals

[Cornell's official FeederWatch page](https://www.allaboutbirds.org/cams/cornell-lab-feederwatch/)
identifies the Treman Bird Feeding Garden at the Lab of Ornithology and documents
an ETS ML1-WPW microphone. Its public YouTube feed was `x10vL6_47Dw`.
[Cornell's Hellgate page](https://www.allaboutbirds.org/cams/hellgate-ospreys/)
identifies the Missoula nest near roads and a railway; its feed was `J7HO0dkkomE`.
That setting provides plausible non-aircraft alternatives, not a verified label
for any proposal in this batch. Rights in source media remain with their owners.

Hellgate proposed intervals, in recording-relative seconds, were 8–25,
88.5–123.5, 405–420, 482.5–497.5 and 503.5–522. Their frequency bands were
239–268, 124–136, 246–272, 42–49 and 92–106 Hz. The saved spectrograms show the
measured falling ridges; matching to historical aircraft remains necessary.

The official pages were readable through the web fetcher; direct Python page
requests returned 403. Their official YouTube links remained publicly accessible.
yt-dlp 2026.10.26 resolved public live HLS audio/video without supplied credentials.
The normal public audio rendition and a video rendition shared a small local HLS
master for synchronized capture. Video was copied to null; only three small
camera-clock PNG frames were retained per site. No video file was saved.

The shared camera capture command preserves input timestamps and maps video to
null while encoding mono 16 kHz / 64 kbps MP3. Adding a sparse clock-frame filter
needed `trim=duration=...` before `select` so a short smoke test could terminate
before the next selected frame. The exact executed prototype, its dependencies'
hashes and all initial setup failures are retained. The successful 10 s smoke
decoded to exactly 10 s; it is a timing check, not a discovery benchmark case.

## Clock evidence and limits

The first requested audio and video segments shared the same sequence at each
site. Provider program dates were `2026-11-03T02:05:25.092Z` for Cornell and
`2026-11-03T02:05:23.929Z` for Hellgate. Visible camera clocks were separately
read from the original PNGs. Under the expected site-local timezone assumptions
(`America/New_York` / `America/Denver`), their displayed times differ from program
date plus frame PTS by about -1.094 s / -0.941 s consistently at 0/120/240 s.

Those are corroborating observations, not calibrated hard clock bounds. Timezone
interpretation, displayed-second rounding, hardware clock accuracy and exact
microphone coordinates remain explicit uncertainties. Raw MP3 intake correctly
reported `needs_input`; the outside-camera evidence was not passed to discovery.
Capture/download time is recorded separately from source program/camera time.

The usual ADSB.lol staging release
`v2026.11.03-planes-readsb-staging-0` was queried and not found. Other providers
were not ruled out. This batch has no aircraft association, searched geographic
coverage or location estimate; errors at 100/500/1000 m are **not evaluated**.

## Inspectable artifacts

All-case batch summary, input/code hashes, complete discovery JSON, individual
ridge CSV/PNGs, audio-level checks and clock audits are under
`evidence/bird-feeds-20261103/`. One original clock frame per site is included for
inspection. The remaining frame hashes are in the clock audits.

Full local MP3s are under `/home/cinna/DOPPLERGEIST/results/bird-feeds-20261103/`.
Whole-file diagnostic arrays are under
`/home/cinna/DOPPLERGEIST-bird-feeds/results/bird-feed-discovery-20261103/`.
Transient stream URLs and unredacted transport logs are kept only in private
local artifacts. No such URLs, source video, audio cache or environment is added
to Git. These are exploratory real-audio feature tests; independent real/national
localization acceptance remains open.
