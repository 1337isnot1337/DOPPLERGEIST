# Physical motion and emission-solver evidence — W3, 2026-11-03 UTC

Code commits: `186fbed` continuous total-speed/CPA/time-local support;
`a1ae353` convergence; current-main ancestry and source `294ac49`.
The W1 classifier is retained by ancestry and is not replaced.

Before: at `21ad2f0`, a side-view trajectory reaches 750 m/s between zero-speed
native knots while arrivals stay monotone. Its exact ridge receives normalized
score 1.0. `baseline.log` records the two expected failures plus two clean
controls. The tested file is frozen at `186fbed` and its digest is verified in
`baseline.json`. At `186fbed`, the additional analytic near-sonic convergence
control still fails (`convergence-baseline.log`); its test is frozen at
`a1ae353`. Baselines used `git archive <source> src` in a temporary directory
and a PYTHONPATH override, with pytest selection/exit codes in the JSON records.

After: full gates passed 235 + 6 subtests at `186fbed`, 236 + 6 at `a1ae353`,
and 243 + 6 at main-combined `294ac49`, all zero failures/skips. The complete
command, sources, durations and native logs are in `receipt.json`.

From the repository root, the source-only check is reproducible with:

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 .venv/bin/python \
  scripts/check_motion_support.py --output results/new-motion-support-check
```

The output directory must be new. It compares the production guard against all
16 preserved canonical/fresh source segments: all 207 excluded native intervals
agree exactly. `source-audit-speed-guard.json` preserves the first check and
`source-audit-current-main.json` records the final source, every excluded interval
and all native input/code hashes. It reads no audio or receiver truth.

The native fixture controls also retain a 300 m/s clean path, a disjoint clean
event in a flawed source, both actual CPA paths, changing sound speed, conservative
arrival bounds and independent dense continuous-speed samples. The unfinished
near-sonic solve remains unknown; neither a finite iterate nor a perfect ridge
fit establishes model support. Details: [MOTION_SUPPORT.md](../../docs/MOTION_SUPPORT.md).

These are physical-model/source-boundary regressions. Whole-track CPA exclusions
must remain visible as lost model coverage through W2/W5; an unsupported source
is not an acoustic rejection. This evidence performs no interpolation repair,
new nationwide localization, real accuracy validation or source-data collection.
Issue #64 and independent field/end-to-end acceptance gates remain open.
