# AeroSonicDB scanner-only sample

This report summarizes an existing run of the DOPPLERGEIST event scanner on
real, publicly released AeroSonicDB audio. No flight matching, aircraft
association, or geolocation was run. The scanner received audio only; publisher
class, location, flight, and time labels stayed in a separate local selection
record and were joined only for this summary.

Source: Downward and Nordby, [AeroSonicDB (YPAD-0523), version 1.1.2](https://doi.org/10.5281/zenodo.10215080), released under CC BY-NC 4.0. This repository does not redistribute audio.

## Sample and results

The fixed sample used seed `20261103` and stratified by publisher class and
location: 100 aircraft-labeled clips from location 0, nine from location 1, 16
from location 2, and ten publisher-labeled ambient/background clips at each
location. The per-case table uses opaque case IDs and contains scanner outcomes
only: [CSV](aerosonic-scanner-survey-20261103.csv). Original audio and the
truth-bearing selection remain under
`/home/cinna/.local/state/dopplergeist-w4-aerosonic-20261103/`.

| Publisher class, joined after scanning | Cases | At least one scanner proposal | No proposal |
| --- | ---: | ---: | ---: |
| Aircraft labeled | 125 | 51 (40.8%) | 74 (59.2%) |
| Ambient/background labeled without aircraft | 30 | 0 (0%) | 30 (100%) |

By publisher location, proposals appeared in 43/100 aircraft clips at location
0, 3/9 at location 1, and 5/16 at location 2. The smaller latter strata make
those percentages unstable. The sample is stratified and unbalanced by design;
these counts are not a population sensitivity or false-alarm estimate.

“Proposal” means the automatic scanner emitted one or more harmonic-group IDs.
It does not confirm that a ridge is an aircraft Doppler curve. The background
sample's 0/30 proposal count also does not prove zero false alarms outside this
small, source-defined sample. The first 16 proposal plots are saved locally as
`first-16-proposal-review.png`; they are a limited visual inspection, not an
independent aircraft-identity review.

## Location and clock limits

The dataset supplies aircraft labels, dates, times, microphone IDs, and location
IDs. To protect privacy, its published coordinates are for nearby roads or public
places rather than the exact recorder positions. Do not use them as 100 m
localization ground truth. This scanner-only sample does not satisfy the
requested set of 20 recordings with independently verified microphone locations
and five usable unknown-location recordings.

The current reproduction entry point is
[`benchmark_aerosonic_scan.py`](../scripts/benchmark_aerosonic_scan.py). It uses
the same seed and stratum counts, keeps labels out of the scanner call, and writes
outputs to a new directory. This report summarizes the completed local run; it
does not claim a rerun on the current source revision.
