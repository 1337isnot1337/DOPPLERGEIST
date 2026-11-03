# Real-data recording clock and benchmark units

The [Zenodo 23424278 record](https://zenodo.org/records/23424278) supplies 40 WAV
recordings, annotated frequency/UTC pairs and flight tracks. Those UTC annotations
are useful evidence, but they do not by themselves identify WAV sample zero. This
audit retains the dataset's feature-benchmark scope; it does not promote it to an
independent 100 m location benchmark.

The audit downloaded the all-case summary CSV, both analysis PDFs, the author's
extraction HTML and the smallest four-case ZIP directly from the record. Every
asset matches the upstream MD5, and local SHA256 values are recorded in the
[machine-readable receipt](20261103-real-data-metadata.json). No third-party audio
or PDF is added to Git by this audit.

| Case | Annotated span | WAV duration | Difference |
| --- | ---: | ---: | ---: |
| N456CS_R38 | 109.226 s | 119.226667 s | 10.000667 s |
| N60RS_R11 | 82.090 s | 92.090667 s | 10.000667 s |
| N748SP_R36 | 58.368 s | 68.368021 s | 10.000021 s |
| N814SR_R07 | 54.242 s | 64.241833 s | 9.999833 s |

For all four cases, the summary's `received_start_utc` equals the first annotated
frequency timestamp. The WAVs extend approximately ten seconds beyond the
annotation span. That does not establish how the extra duration is split before
and after the annotations. A five-second leading margin is a possible hypothesis,
not verified timing metadata.

`ffprobe -show_format -show_streams` finds no format or stream tags in the sampled
N814SR_R07 WAV. Its audio is mono 48 kHz PCM16. The tool supports manually entered
recording timing and timing parsed from original filenames; the distributed WAV
is named `audio.wav`. The ZIP's four KMLs contain flight tracks and no recorder
Point, LookAt or Camera. The combined atlas presents the phone at the origin of a
relative ground-track diagram. Text extraction of both PDFs and visual inspection
of the atlas's N814SR_R07 page did not establish an absolute recorder coordinate
or WAV start-time mapping. The remaining three raw ZIPs were not inspected here.

Independent location acceptance still needs a documented mapping from audio
samples to UTC, an independently established recorder coordinate with uncertainty,
and sufficient flight-data coverage. Annotation-based timing alignment or a
reference reconstructed from flight geometry must retain its own evidence label.

## Datetime-unit regression

At checkpoint `472a668`, `benchmark_real_features.py` parsed UTC strings, converted
their integer representation to numbers, and divided by 1e9. Pandas 3.1.0 parses
these strings as microseconds. The 0.170 s interval between the first two
N748SP_R36 annotations consequently became 0.00017000013 s, corrupting the
annotation-fit diagnostics. This did not change the sound waveform or constitute
a localization result.

Current main already fixes that conversion in `b0d9cd1` by using the existing
`unix_time` helper. This follow-up preserves the fix and adds six checks: identical
SI-second intervals at second/millisecond/microsecond/nanosecond datetime
resolution, the actual millisecond annotation example, and equivalent absolute
times expressed with different timezone offsets. The checks allow floating-point
Unix-second rounding below 0.5 microseconds; they do not claim nanosecond precision.
