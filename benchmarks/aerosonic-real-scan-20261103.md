# Real AeroSonicDB scanner screen

This is a **scanner-only development sample**, not a geolocation test. It uses
actual recordings from [AeroSonicDB v1.1.2](https://zenodo.org/records/10215080),
created by Blake Downward and offered under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). The publisher
describes audible-aircraft labels and background labels. No flight matching,
location search, hand-selected frequency band, or generated audio was used.

The publisher deliberately provides nearby public-place coordinates rather
than exact microphone coordinates. Therefore these recordings **do not count
as precise known-location truth**, and they do not satisfy the separate goal
of 20 independently located clips. The dataset is from Adelaide, Australia;
the current national-search scope is the continental United States. Clock and
coordinate uncertainty were not established here.

Before scanning, a fixed seed selected 100 aircraft-labelled clips from site 0,
all 9 from site 1, all 16 from site 2, and 10 publisher-labelled background
clips from each site. The sample was shuffled, and the scanner received WAVs
renamed to opaque case IDs. The source filename and publisher labels remain in
the local `selection.json`, separate from the scanner inputs; no known flight
ID, coordinates, or event hints were supplied to discovery. The sample is
stratified and deliberately overrepresents the smaller sites, so its results
are not population prevalence estimates.

All 155 selected clips downloaded and scanned. Of 125 publisher-labelled
aircraft clips, 51 produced at least one scanner group and 74 produced none;
the groups are proposals, not verified aircraft identifications. None of the
30 background clips produced a proposal. **All 30 were 10 seconds long while
the default scanner requires a 12-second ridge**, so those outcomes cannot
measure false-positive behavior. The scanner produced 118 group IDs across the
sample; grouping and aircraft identity have not been independently verified.
Every individual outcome, including no-proposal clips, is in
[aerosonic-real-scan-20261103.csv](aerosonic-real-scan-20261103.csv).

The runner is `scripts/benchmark_aerosonic_scan.py` and needs the project
runtime plus the optional `remotezip` package. Run with a new output directory:

```sh
PYTHONPATH=src python scripts/benchmark_aerosonic_scan.py NEW_OUTPUT_DIRECTORY
```

The completed local run is
`/home/cinna/.local/state/dopplergeist-w4-aerosonic-20261103/`, including
source-to-case mapping, original WAVs, per-clip scanner records, and an
exploratory spectrogram contact sheet. Audio is not committed. The scanner
source was `f770380`; its intake, discovery, audio and contract files are
unchanged on main as of `a3fbf57`.
