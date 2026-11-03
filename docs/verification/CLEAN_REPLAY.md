# Independent clean-environment replay

This lane checks the existing methodology from a new clone and isolated virtual
environment. It supports DG-12 / issue #13. The automatic upload acceptance runner
is a separate coordinated lane. Successful replays do not complete automatic
discovery or independent national real-audio validation.

The current project target is up to 1,000 m acceptable and 500 m or better
preferred. New runner outputs report 100/500/1,000 m point-error thresholds,
independently of exact-baseline agreement. The frozen receipts and measurements
below retain their original 100 m labels. Meeting a point-error threshold alone
does not establish automatic, independent or national acceptance.

The runner requires Python 3.11+, ffmpeg, the installed project, and restored
inputs. Follow `docs/ARTIFACTS.md` for release acquisition and checksum verification.
Generate the independent synthetic cases before running them:

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest
.venv/bin/python -m pytest -q
.venv/bin/python scripts/make_synthetic_cases.py
.venv/bin/python scripts/verify_pipeline_replay.py \
  --case synthetic-two-events --case synthetic-known-minute \
  --output results/clean-synthetic-replay
.venv/bin/python scripts/verify_pipeline_replay.py \
  --case reference-local --case reference-faint \
  --output results/clean-real-regional-replay
```

Use new output paths. Existing directories are refused. With no `--case`, the
runner attempts all four cases; failed/missing cases are recorded and later cases
still run. Missing fixtures are failures, not skips. A timeout terminates the
whole subprocess group and preserves the partial log/output.

Each case runs the real research CLI as a separate subprocess. The runner records
all declared input hashes, including terrain, geoid, type database and supplied
ridge files; implementation hashes; Git revision and working-tree status;
dependency/Python/ffmpeg versions; exact command; subprocess log; elapsed time; and
peak RSS/CPU use when GNU `time` is available. Evaluation references are read only
after the search exits and are separately hashed. This is process separation,
not a filesystem isolation claim.

`baseline_replays_passed` means that the winning flight IDs, position (within 2 m),
score (within 0.0001) and shared recording clock (within 0.05 s) reproduce the frozen
case. `within_100_m` is reported separately. In particular, reproducing the faint
case's approximately 357 m error passes its regression comparison while retaining
its localization failure. `automatic_upload_goal_verified` remains false for all
these manually configured replays.

The two synthetic cases use the independent emission-domain renderer and separate
truth JSON. The real cases retain the source-informed regional search bounds,
event windows and frequency bands. Their comparison coordinate is a public
platform listing with unquantified physical uncertainty, and the faint case's
recording clock comes from the two-event match.

## Measured clean replay, 2026-11-03 UTC

All four real CLI subprocesses completed successfully at source revision
`472a668`. The original real two-event and faint-event winners reproduce exactly,
including position, flight IDs, ranking score and shared clock. The known-time
synthetic case reproduces its winner, with a score difference of 3.43e-11.

| Case | Position error | Baseline comparison | Runtime | Peak RSS |
| --- | ---: | --- | ---: | ---: |
| Synthetic two events | 15.40 m | Changed; correct flight pair | 148.63 s | 611.58 MiB |
| Synthetic known-time minute | 40.87 m | Reproduced | 15.76 s | 287.00 MiB |
| Real regional two events | 43.86 m from public reference | Reproduced exactly | 99.11 s | 810.77 MiB |
| Real regional faint event | 357.47 m from public reference | Reproduced exactly; misses 100 m target | 208.73 s | 503.97 MiB |

The clean environment used CPython 3.12.3, pandas 3.1.0, numpy 2.5.4, scipy
1.18.1 and ffmpeg 6.1.1 on Linux. All 39 tests passed in 6.14 s, including the four
new runner failure/provenance checks. These machine-specific runtimes include
overlap between the synthetic and real replay processes; they are observations,
not controlled speed comparisons with the original host.

The synthetic wrapper intentionally exited 1: its two-event winner moved
24.77555 m from the archived point, its score changed by +0.00958725, and its
recording start changed by +0.40638876 s. It still found the correct pair with
0.06380653 s absolute clock error. The archived and current first-event ridge
CSVs differ at 67 of 733 frames; the second event differs at 34 frames. The old
synthetic report does not pin an implementation hash. The exact cause of that
ridge/baseline change is unresolved; no algorithm improvement is inferred.

The independently regenerated WAV has exactly the same 4,720,000 decoded float32
samples as the release WAV. Only its PEAK-chunk timestamp bytes 60 and 61 differ.
Both container hashes and the common decoded-sample SHA256 are retained. Configs,
tracks, type data and synthetic truth regenerate byte-for-byte.

The real-regional wrapper exited 0. All three required data archives and the
additional synthetic comparison archive match their published release hashes;
all 21 selected restored input files also match the manifest. The national
prop/unknown Parquet and raw daily archive were not restored for these regional
replays. No source video was downloaded or uploaded.

Exact commands are in the machine-readable
[synthetic receipt](20261103-clean-replay/synthetic-verification.json) and
[real regional receipt](20261103-clean-replay/real-regional-verification.json).
[Restored-file hashes](20261103-clean-replay/restored-files.json),
[release-archive hashes](20261103-clean-replay/release-archives.json),
[synthetic sample comparison](20261103-clean-replay/synthetic-regeneration.json)
and subprocess logs are in the same directory. Large audio/flight arrays and
spectral outputs stay in ignored `data/`, `results/` and release assets.

Automatic upload/discovery and independent national real-audio acceptance remain
outside these manually configured replays. This verification does not close
issue #13.
