# VIREO real-audio scanner sample

This is a scanner-only development survey, not a location-accuracy benchmark.
The [VIREO Initiative dataset](https://zenodo.org/records/21246876) contains
real 2026 recordings at 18 named sites in three Chicago-area preserves. The
publisher lists site coordinates, but the accuracy of those coordinates and
the mapping from archive directories to numbered sites have not been independently
verified. One inspected AudioMoth header and a recorder configuration label the
clock UTC, but GPS time setting is disabled in that configuration and clock
accuracy or drift is not established. The publisher says detected human speech
was anonymized by formant modification; this processing may affect the audio.

From the archive's filename-matching WAV members, select six per site using
seed `20261103` and inspect them in site-balanced rounds. The 108 real clips
were each 30 seconds long. All 108 were acquired and scanned: **107 returned
no proposal and one returned one proposal**. The one proposal is a faint
descending low-frequency trace whose source is unverified; it could be a ground
vehicle. No clip is counted here as a confirmed aircraft Doppler benchmark.
A quick 0–1 kHz spectrogram spot-check of three no-proposal clips, one per
preserve, revealed no obvious long descending harmonic structure, but does not
prove that aircraft were absent. The 30-second recordings are short samples,
not continuous monitoring, and their site-balanced selection is not a
representative sample of all environments or aircraft flyovers.

[Individual outcomes and checksums](vireo-real-scan-20261103.csv) include every
case. Each extracted ZIP member passed its CRC check; the full 27.8 GB archive
was not downloaded or verified. Archive filenames and their site/date mapping
are held separately from scanner input: the scanner only receives an opaque
hash-named WAV. No flight data, flight matching, location search, manually
selected event windows or frequency bands were used.

To reproduce with the project runtime and optional `remotezip` package:

```sh
PYTHONPATH=src python scripts/benchmark_vireo_scan.py NEW_OUTPUT_DIRECTORY
```

The script requires a new output directory and keeps audio local. The completed
local run, per-clip scanner outputs, selection and review images are at
`/home/cinna/.local/state/dopplergeist-w4-vireo-20261103/`. Audio is not
committed. The scan used source `2864068`; its intake and discovery code match
main at `72cdebb`. Counts are scanner proposals, not confirmed detections or
estimates of the scanner's sensitivity or false-positive rate.
