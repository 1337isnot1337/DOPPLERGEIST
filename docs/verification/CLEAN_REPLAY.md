# Independent clean-environment replay

This lane checks the existing methodology from a new clone and isolated virtual
environment. It supports DG-12 / issue #13. The automatic upload acceptance runner
is a separate coordinated lane. Successful replays do not complete automatic
discovery or independent national real-audio validation.

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

Machine-readable run receipts and measured results will be added here after the
clean replays complete. Large audio/flight arrays and spectral outputs stay in
ignored `data/`, `results/` and checksummed release assets.
