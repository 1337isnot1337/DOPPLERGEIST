# Risoux real-audio expanded scanner sample

This is a second, scanner-only development sample from the publisher's
[Risoux forest recordings](https://zenodo.org/records/10701274). Using seed
`20261104`, it selects 20 additional aircraft-only-labeled recordings and two
additional silence/no-aircraft-labeled recordings per filename prefix. All
110 choices exclude the earlier [30-case pilot](risoux-real-scan-20261103.md).
Five filename prefixes are sampling strata, not an assertion of five sites.
Publisher labels select and describe the sample; the scanner receives only
opaque audio filenames, with no labels, flight data, location information or
manually chosen bands/windows.

All 110 one-minute clips were eventually scanned:

| Publisher label | Scanner proposals | No scanner proposal |
| --- | ---: | ---: |
| Aircraft, without wind, rain or biophony label | 11 | 89 |
| Silence, no aircraft label | 0 | 10 |

A quick 0–1.6 kHz visual review found two proposal traces that look
Doppler-like and nine with ambiguous sources. The publisher's broad aircraft
label does not establish a usable tonal ridge; the 89 no-proposal cases are
misses against that broad label, not demonstrated missed Doppler ridges. The
sample is deliberately label-selected, the controls are few, and these counts
do not estimate general sensitivity or false-positive rates. Exact recorder
positions and clock accuracy remain unresolved; no clip here is a verified
precision-location benchmark.

[Every case and checksum](risoux-expanded-scan-20261103.csv) is retained. The
first run scanned 34 clips, then 76 individual requests failed with HTTP 503.
Those original acquisition failures are preserved locally. A later single probe
succeeded and the 76 failed members were retried in a new directory; all then
scanned. Each extracted ZIP member passed its CRC; the full 10.5 GB archive
was not downloaded or verified. The current runner stops on a source throttle
or transient server error instead of repeating requests.

Reproduce with the project runtime and optional `remotezip` package:

```sh
PYTHONPATH=src python scripts/benchmark_risoux_scan.py NEW_OUTPUT_DIRECTORY --expanded
```

The runner requires a new output directory. The preserved original and retry
runs, audio, source mapping, scanner output, and review contact sheet are in
`/home/cinna/.local/state/dopplergeist-w4-risoux-expanded-20261103/` and
`/home/cinna/.local/state/dopplergeist-w4-risoux-expanded-retry1-20261103/`.
Audio is not committed. No flight matching or geolocation was run. The scanner
used source `2864068`; intake and discovery match main at `7998a90`.
