# Evaluation corpus and separation

Current reports use the updated 1,000 m acceptance target and show the 100, 500
and 1,000 m tiers separately. Historical runs retain their original 100 m target.
Uncalibrated sensitivity and diagnostic candidates are distinct from measured
error of an accepted location.

`inventory.json` pins input hashes from the published checkpoint manifest, source,
license status, clock evidence and coordinate precision. The 40-passage record is
CC BY 4.0 (Praveen Pathak). The public reference recording has no independently
established redistribution licence in the collected evidence; this change adds
neither that audio nor the source video. Synthetic fixtures use the repository's
independent emission-domain renderer. Historical outputs remain untouched.

`frozen-manifest.json` contains case identity, split and scope only.
`truth/frozen-labels.json` contains post-run evaluation references. None of these
historical cases is held out: all have already been inspected during development.
The exact coordinates, known aircraft, manual event windows/bands and regional
search boxes in historical artifacts must never become normal search inputs.

## Reproduce the frozen audit

```bash
PYTHONPATH=src .venv/bin/python scripts/evaluate_frozen.py --output results/frozen-audit-new
```

This evaluates every one of the 48 readable frozen cases. Two independent-renderer
synthetic searches return 21.8855 m and 40.8744 m errors. These searches used manual
event settings. The real regional two-event estimate is 43.8585 m from a rounded
mapped reference; the faint all-types result is 357.4687 m away and misses the
100 m target. Neither is eligible for independent real localization accuracy.
Three exploratory directories have no completed report and are counted as
execution failures. The 40 feature cases include all seven misses (33 detections),
using supplied harmonic-band annotations. Their case-level detection recall is
not automatic event-window recall. Peak memory was not recorded and remains null.
Feature-only results are represented as `inconclusive` for localization. Use the
`by_scope` aggregates to distinguish these from localization abstention.

## Run new audio controls with truth unavailable

```bash
PYTHONPATH=src .venv/bin/python scripts/make_benchmark_controls.py --output results/controls-new
# Place results/controls-new/truth outside the search worker's filesystem/mount.
# The runner reads only inputs/manifest.json, requests, and checksummed audio.
PYTHONPATH=src .venv/bin/python scripts/run_benchmark.py results/controls-new/inputs/manifest.json \
  --output results/controls-run-new -- python run_one.py '{request}' '{output}'
# After the worker exits, join the separately held labels:
PYTHONPATH=src .venv/bin/python scripts/evaluate_benchmark.py \
  results/controls-new/inputs/manifest.json results/controls-run-new/predictions.json \
  results/controls-new/truth/labels.json --output results/controls-evaluation-new.json
```

`run_one.py` is an adapter to the actual producer entry point and must write a
shared `JobResult` to `OUTPUT/result.json`. The runner uses an argument vector,
validates the normal request contract (no manual hints), verifies audio hashes,
records every process exit and per-process Linux `wait4` runtime/peak memory, and
refuses existing output directories. It does not pass manifest labels to the
executable. It is not an adversarial filesystem sandbox: the operator must remove
or unmount truth for an isolation claim. A protocol test executes with no truth
directory at all; that test does not claim audio/localization accuracy.

The generator makes seven development and seven public deterministic held-out
controls with distinct seeds: noise, stationary tone, ascending non-aircraft
electronic sweep, moving-source harmonic event, overlapping nonharmonic events,
truncated short clip and MP3. Audio filenames are opaque. Truth contains event
intervals and negative labels; requests contain only audio, an explicit synthetic
clock and CONUS coverage. These discovery controls have no historical track corpus,
so precise locations from them are unsupported. The renderer transports emission
phase into reception time without calling the inverse search physics. MP3 bytes
are hashed per generation because encoder versions can change bytes. Freeze
detector settings on development controls before examining held-out predictions.
These small public synthetic splits are regression controls, not independent real
validation or an estimate of performance over arbitrary sound distributions.

The [isolated live receipt](reports/discovery-isolation-20261102/receipt.json) and
[all-case report](reports/discovery-isolation-20261102/report.json) exercise the
actual W1 intake/discovery source frozen at `62066ac` (discovery `4a49646`). Each
subprocess had both truth directories masked with bubblewrap, a read-only root,
private `/tmp`, disabled network and only its own output directory writable.
A separate probe verified label files were absent inside that namespace. All
14 cases completed: 8/8 labelled events, zero misses and zero false alarms, with
4/4 events in each split. All cases remain discovery-only inconclusive without
coordinates. Total per-case elapsed time was 120.1 s; maximum per-case peak RSS
was 240,021,504 bytes, including plotting/import/codec overhead. The receipt pins
source/input/prediction hashes and preserves the two failed isolation-harness
attempts; their failures are not detector outcomes. These results do not measure
historical flight association or real-world localization accuracy.

Detection evaluation merges harmonic groups and uses maximum-cardinality temporal
IoU matching at 0.3 (predeclared). It reports TP, misses and false alarms. Localization
uses WGS84 geodesic error with a 100 m threshold, marks wrong flight associations as
false localizations, and reports all statuses separately. The false-localization
denominator is explicit: eligible location cases plus known negative cases. Candidate
coordinates retained under `inconclusive` are diagnostic alternatives, not fixes.

## Unresolved independent real-data acceptance

The requested three independently timed recordings across two known public or
consented locations have **not** been established. No existing real case qualifies
for that gate. The 40 Livermore passages have UTC frequency annotations but no
established audio-sample-zero clock or precise recorder coordinate in the collected
evidence. Their labels cannot be promoted from flight proximity or fitted clocks.

Source investigation on 2026-11-02 found
[AeroSonicDB v1.1](https://zenodo.org/records/8368882), which supplies recordings
from three Adelaide locations and filenames with dates/times. Its published
coordinates deliberately identify a nearby road/public space for privacy, rather
than the recorder. Precision adequate for a 100 m recorder-error claim and a UTC
sample-zero clock are unestablished. It is also outside the current CONUS contract.
The [3K version](https://zenodo.org/records/12775560) has restricted files and
trimmed events. These are potential detection corpora, not eligible location
truth. No access request or author message was sent. Additional real recordings
must establish coordinate uncertainty, consent/public site, source licence,
sample-zero UTC/time window and a flight archive independent of the known target.
Until those exist, do not close the real-corpus or nationwide-accuracy gate.

## Automatic discovery on the 40 real Livermore recordings

On 2026-11-03, all 40 published smartphone recordings were encoded to 192 kbps
MP3 and passed through the normal automatic CLI at source `e8cbb08`. Inputs had
opaque names, no event windows/bands, no flight hints and no supplied UTC. Workers
had no network or access to the annotations, KML files or original case mapping.
Every case and outcome is in [the compact table](real-discovery-20261103.csv).

**36 clips produced proposals; four produced none; 136 groups were proposed.**
All 40 jobs returned `needs_input / recording_time_required`; none returned a
location. Processing took 241.88 s, excluding MP3 staging. These are real positive
recordings, but a proposal in a positive clip is not a confirmed target detection.
There is no event-level false-alarm rate or location-accuracy result here.

The missed clips were N958JX_R50, N1387U_R44, N451EE_R51 and N9658K_R24. Their
annotated bands, inspected only after outputs were terminal, all lie inside the
frozen 40–1600 Hz discovery range. The historical manually banded analysis detected
N9658K_R24; the other three were historical misses too. N563FX_R21 produced 25
groups and N60RS_R11 produced 19, requiring inspection for fragments, harmonics
and unrelated proposals. Extra groups remain unconfirmed rather than being
automatically counted as false alarms. These cases are handed to W1 in issue #5.

To repeat with the restored public source and a new output directory:

```sh
PYTHONPATH=src .venv/bin/python scripts/benchmark_real_discovery.py \
  data/research/zenodo-23424278 --output results/NEW-UNUSED-DIRECTORY
```

The script requires the automatic CLI, ffmpeg and bwrap. Its runner is made
portable from the local script used for this experiment; only `--help` was run
on the committed helper, without repeating the unchanged 40-clip experiment.
The missing microphone/UTC evidence described above still prevents these cases
from qualifying as real geolocation acceptance. Further validation must use real
recordings and geolocations under the user's real-data-only directive.
