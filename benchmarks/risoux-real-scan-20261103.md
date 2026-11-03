# Risoux real-aircraft-labeled scanner sample

This scanner-only development sample uses the publisher's
[Risoux forest soundscape dataset](https://zenodo.org/records/10701274). The
publisher reports 1,314 one-minute field recordings, manually labeled for
sound categories including aircraft, from recorders deployed in the French
Jura. The source describes four recorders roughly 1 km apart; the individual
recorder coordinates and recording clock accuracy have not been established
here. Five filename prefixes occur in the archive and are sampling strata,
not a claim of five independent sites. These clips cannot validate precision
location accuracy and are outside the current CONUS search domain.

With seed `20261103`, select five recordings per filename prefix labeled
`plane=1` with no wind, rain or biophony label, and one per prefix labeled
`plane=0, silence=1`: 25 aircraft-labeled clips and five quiet controls. These
labels select and describe the sample; the scanner receives only opaque audio
filenames. All 30 clips were scanned successfully and each was about 60 seconds:

| Publisher label | Scanner proposals | No scanner proposal |
| --- | ---: | ---: |
| Aircraft, without the other specified labels | 4 | 21 |
| Silence, no aircraft label | 0 | 5 |

A quick visual review found two proposal traces that look Doppler-like and two
whose sources remain ambiguous. Two of the 21 no-proposal aircraft-labeled
clips were spot-checked and showed no obvious long descending tone in the
0–1.6 kHz view. A publisher aircraft label does not establish that a usable
tonal Doppler ridge is present, and a scanner proposal does not establish that
its trace came from an aircraft. The 21 no-proposal results are misses against
the broad publisher aircraft labels, not demonstrated missed Doppler ridges.
The sample is intentionally label-selected and small; the five controls do not
establish a general false-positive rate.

[Individual outcomes and checksums](risoux-real-scan-20261103.csv) retain all
30 cases. The publisher annotation CSV matched its published MD5; each extracted
ZIP member passed its CRC check. The full 10.5 GB archive was not downloaded
or verified. No flight data, flight matching, location search, manually chosen
event windows or frequency bands were used.

To reproduce with the project runtime and optional `remotezip` package:

```sh
PYTHONPATH=src python scripts/benchmark_risoux_scan.py NEW_OUTPUT_DIRECTORY
```

The script requires a new output directory and keeps audio local. The completed
run, source mapping, individual scanner results, and review images are at
`/home/cinna/.local/state/dopplergeist-w4-risoux-20261103/`. Audio is not
committed. The scanner used source `2864068`; intake and discovery match main
at `b4f6e1c`.
