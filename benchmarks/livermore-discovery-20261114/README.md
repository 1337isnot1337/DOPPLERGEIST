# Forty public smartphone passages: automatic-discovery development control

Protocol registered before waveform inspection or detector output in
[issue341](https://github.com/1337isnot1337/DOPPLERGEIST/issues/341#issuecomment-6874158023).
Source: Praveen Pathak, [Aeroplane data full analysis and raw files,v2](https://zenodo.org/records/24075029),
CC BY4.0, November9,2026. All40 WAVs in the archive match all40 publisher result
rows. The publisher archive MD5 is verified by the prepare command. No recordings
or publisher tools are copied into Git.

This source was found through AeroDoppler's public README; its previously
reported29-case development summary was already seen. This is not an untouched
holdout. The source supplies presegmented individual passages, so this control
cannot measure full-recording recall or exhaustively label false proposals.

## Fixed experiment

- Production source463834f5bc9b839a74593b429dd88e92c7ad5779; all automatic defaults.
  The runner refuses changed production source rather than silently using this
  historical label. No aircraft IDs, harmonic traces, time windows, bands or
  coordinates enter discovery. It receives only each complete opaque WAV.
- All40 original WAVs, sorted by archive path and copied byte-for-byte as
  P01..P40. No case is selected or removed based on outcomes.
- Serial subprocesses,120-second deadline per case, single OpenBLAS/OMP thread,
  CPU median backend, no synthetic data. Every failed/timeout/partial outcome is
  retained. The complete prediction population freezes before evaluation.
- Evaluation then joins the publisher's manually traced single harmonic using
  its public first-sample UTC. At each reference point, an output ridge matches
  within max(2Hz,1% of reference frequency). Interpolation bridges at most1second;
  an exact observed point remains supported. No harmonic frequency scaling,
  event selection, time shifting, threshold tuning or refit is permitted.
- Retain every reference point, pointwise union coverage, best-single-ridge
  coverage and all out-of-audio reference points. The registered coverage
  criterion is union>=80% and best single ridge>=60%. This is a trace-recovery
  control, not validated source identity or general aircraft-detection accuracy.
  Unmatched output ridges lack exhaustive false-positive labels.

The publisher explicitly supplies phone WGS84 position, EGM96 elevation and UTC
sample-zero filenames. No hidden position is inferred. Its README does not
establish measured recorder position/clock uncertainty or start/end drift.
Those gaps prevent #53 field-corpus acceptance. No location search or acoustic
association to its supplied flight track is performed here.

## Replay

Download `raw_flight_data.zip` and `final_results_40_cases.csv` from the exact
public record above. In the recorded Python3.14.6/NumPy2.5.4/SciPy1.18.1/Numba0.68.1
environment, from the committed runner checkout with the pinned production
source and native extensions built:

```bash
PYTHONPATH=src python scripts/benchmark_livermore_discovery.py prepare --data /path/to/public-data --output /path/to/new-inputs
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLBACKEND=Agg PYTHONPATH=src python scripts/benchmark_livermore_discovery.py discover --inputs /path/to/new-inputs --output /path/to/new-predictions
PYTHONPATH=src python scripts/benchmark_livermore_discovery.py evaluate --data /path/to/public-data --predictions /path/to/new-predictions --output /path/to/new-evaluation
```

Outcomes will be appended after all40 cases finish; incomplete work is not a
successful discovery result, and a close supplied-track fit would not be an
accepted location.
