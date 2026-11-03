# Worker 1 audio evidence: 2026-11-02

Intake: `9538c46` / PR #15. Frozen discovery: `4a49646` / PR #25.
The discovery code was fixed before DG-02 predictions began. No event windows,
bands, flight IDs, coordinates or truth paths enter discovery. All input audio
and caches remain local; this evidence contains no source media/video.
`SHA256SUMS.json` covers every evidence artifact other than itself and this README.

## Complete-file scans

| Fixed development version | Synthetic (1180 s) | Reference (3600.1845 s) |
| --- | --- | --- |
| v1 | 1 proposal; misses first planted pass | 22 proposals |
| v2 | 2 proposals; both planted passes covered | 24 proposals |
| v3 / 4a49646 | 2 proposals; both planted passes covered | 8 proposals |

v1 rejected a coherent weak synthetic ridge using a redundant median-contrast
cutoff. v2 removed that cutoff. v3 adds distributed-motion/jump checks to reject
paths switching between stationary tones and extends harmonic grouping to missing
fundamentals. Each version's original summary/code hash/git state, intake metadata,
discovery JSON and overview plot are preserved. v3 adds per-event spectrograms
and CSVs. None of these development versions used reference coordinates or flights.

v3 synthetic: 7.2366 s; peak RSS 238044 KiB. Reference: 31.0514 s; peak RSS
249528 KiB. Both prominent reference centers (about 2156 and 3076 s) are covered,
but the passes fragment into multiple proposals; the documented faint pass
(1250–1310 s) is missed. There is no complete reference event annotation, so the
other proposals cannot be certified true/false aircraft alarms. The reference
recording clock remains unresolved; it is not an eligible independent location test.

Source SHA256: synthetic `372912c008ed61a49de647cd9a5cd1651d1ce952e4690a2fe6c1da0cd641140a`;
reference `262d9c4eba1c80657813c604140ba2afbbaabed2b3aebc833cba7cafdc005e9f`.

Reproduction (fresh output directories required):

```bash
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python scripts/discover_audio.py /home/cinna/aircraft-audio-geolocation/data/synthetic/recording.wav --output results/new-synthetic-scan
PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python scripts/discover_audio.py /home/cinna/aircraft-audio-geolocation/data/source/reference-recording.wav --output results/new-reference-scan
```

## DG-02 fixed-code positive/negative controls

`dg02-controls-4a49646/report.json` is the unmodified separate evaluator output.
14 cases, 8 planted events, **8 hits / 0 misses / 0 false alarms / 0 execution
failures** at event IoU >= 0.3. Development and public deterministic held_out
splits each find 4/4 events. Noise, stationary, ascending electronic sweep and
short unsupported clips emit no event. Harmonics, overlapping events and actual
MP3 positives are retained. All statuses are intentionally `inconclusive` because
the adapter runs discovery only; no location is estimated. These are synthetic
controls, with zero eligible location cases and no real validation claim.

The public-input manifest, generator provenance, complete predictions and
per-case source/code/adapter hashes are included. The generator is Worker 4's
`scripts/make_benchmark_controls.py`, SHA256
`be52c4ac7a998302e0920522eea38c48cfa42f2b57ef21c3a24e69ce0ff7d80f`.
Predictions ran through its label-free subprocess runner before its separate
post-run evaluator opened truth. Total subprocess time was 61.176 s; maximum
per-case peak RSS was 227.984 MiB. The opaque-ID synthetic split is deterministic
and public; it is not an independently acquired held-out real corpus.

Exact runner invocation (W4 worktree supplies evaluation tooling; W1 supplies the
producer adapter; paths were absolute in the actual subprocess):

```bash
PYTHONPATH=/home/cinna/dopplergeist-w4-evaluation/src /home/cinna/aircraft-audio-geolocation/.venv/bin/python /home/cinna/dopplergeist-w4-evaluation/scripts/run_benchmark.py results/w1-dg02-controls-frozen-4a49646/inputs/manifest.json --output results/w1-dg02-predictions-4a49646 -- /usr/bin/env PYTHONPATH=/home/cinna/dopplergeist-w1-audio/src /home/cinna/aircraft-audio-geolocation/.venv/bin/python /home/cinna/dopplergeist-w1-audio/scripts/discover_benchmark_case.py '{request}' '{output}'
PYTHONPATH=/home/cinna/dopplergeist-w4-evaluation/src /home/cinna/aircraft-audio-geolocation/.venv/bin/python /home/cinna/dopplergeist-w4-evaluation/scripts/evaluate_benchmark.py results/w1-dg02-controls-frozen-4a49646/inputs/manifest.json results/w1-dg02-predictions-4a49646/predictions.json results/w1-dg02-controls-frozen-4a49646/truth/labels.json --output results/w1-dg02-report-4a49646.json
```

## Checks and remaining limits

`PYTHONPATH=src /home/cinna/aircraft-audio-geolocation/.venv/bin/python -m pytest -q --basetemp=results/pytest-audio-integration-4a49646`
passed **51 tests** after merging matching main `2512e9f`; runtime 49.35 s.
This includes 4 intake and 6 discovery regressions plus the shared contract,
matching and historical tests. It does not test every other worker's unmerged code.

Intake real MP3/WAV burst alignment is <=1 ms at three positions; duration agrees
within one decoded sample. Unknown MP3 encoders without gapless metadata may
retain unknown padding. Generic creation/edit/date tags remain untrusted and
missing recording UTC requires input. All spectral uncertainty is diagnostic,
not calibrated probability. Discovery can miss faint/truncated events, fragment
ridges, and propose non-aircraft moving tones. No 100 m / automatic nationwide
localization claim follows from this evidence. Product end-to-end acceptance is
owned by the integration and verification workers.

## Forty public full WAVs, without supplied bands

`public40-4a49646/` contains every prediction, input manifest/hash and per-case
resource/proposal counts. Fixed detector `4a49646` processed all 40 complete WAVs
(3605.323 s total audio): **0 processing errors, 28 recordings with at least one
proposal, 12 without, 102 proposals total**. Aggregate subprocess runtime321.562 s;
maximum per-case peak RSS266.902 MiB. The recording list came only from `audio.wav`
paths; the detector did not read frequency annotations, KML, reference speed/range,
coordinates or truth. Annotation-assisted historical feature results were not
used as discovery inputs.

These are proposal counts, **not 28 certified aircraft detections or a 70% true
event recall**. Multiple proposals may be fragments, other sources or false
alarms, and annotation/audio clock alignment and harmonic identity have not been
verified by this check. This corpus lacks independent recorder-coordinate/clock
proof, so no localization-accuracy claim is possible. The complete per-case
predictions preserve all additional proposals and misses for later evaluation.
