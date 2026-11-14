# Experimental aircraft-category diagnostic

This is an explicit diagnostic over an existing `discovery.json` and its original
recording. Categories stay outside `DetectedEvent` and saved job results.
Automatic discovery, uploads, localization, flight filtering and scoring do not
import or call the recognizer. The previous `DOPPLERGEIST_CATEGORY_MODEL` and
`DOPPLERGEIST_CATEGORY_AUDIO` environment hooks are removed.

## Run separately

The diagnostic needs the normal runtime, FFmpeg, librosa, scikit-learn and joblib.
These classifier dependencies are optional and are not added to the product's
dependency list. A compatible trusted model is also required; no model bundle
is shipped or silently downloaded.

```bash
python -m pip install librosa scikit-learn joblib
PYTHONPATH=src python scripts/diagnose_aircraft_category.py \
  --discovery /path/to/job/discovery/discovery.json \
  --audio /path/to/job/input.mp3 \
  --model /path/to/trusted/model.joblib \
  --output /path/to/new-category-report.json --max-windows 1024
```

Loading joblib can execute serialized code. Use only a local artifact you created
or explicitly trust, with compatible dependency versions. A model from an
untrusted upload is not safe to load. The source SHA-256 must match the saved
discovery before any model is loaded. An existing output file is refused.
Missing dependencies, invalid input/model or decoding failures stop this separate
command and leave the saved discovery and completed localization job untouched.

## Features, limits and output

Each five-second window is decoded at 16 kHz with a 30-second decoder timeout.
Its 20 MFCC means and 20 temporal standard deviations use the contributor's
original feature settings. Windows start every 2.5 seconds; a final window ends
at the event boundary when necessary. Window classifier scores are averaged.
Audio buffers and feature matrices are bounded by one window, including long
events. Duplicate intervals reuse their diagnostic result.

The global window budget counts decoded/scored windows. If an event cannot fit
entirely in the remaining budget, that event and subsequent uncached eligible
events receive `unknown / work_limit`; no partial-window result is promoted to
a category. The report states `complete: false`, and the command exits 2.
Events shorter than five seconds receive `unknown / insufficient_audio`.

The compatible bundle is a dictionary with `feature_version` equal to
`mfcc20-16khz-5s-hop2.5s-window-v1`, `aggregation` equal to
`mean_window_predict_proba`, a fitted 40-feature `scaler`, and a `classifier`
with `background`, `propeller` and `turbofan` classes and `predict_proba`.
The report identifies the model bytes and preserves mean classifier scores.
Those scores are uncalibrated model outputs, not probabilities of aircraft
identity. `background` maps to `unknown`, `propeller` to
`fixed_wing_propeller_like`, and `turbofan` to `jet_like`. Helicopter recognition
is not implemented. These labels never override the confirmed non-jet policy.

## Empirical gate

The [development experiment](https://github.com/1337isnot1337/DOPPLERGEIST/issues/355#issuecomment-6623693150)
reported propeller precision 0.223 and recall 0.480 on recording-level aggregated
features. It did not evaluate this event-window score-averaging path. Its official
test split was not evaluated, and its training recipe/model bundle are not part
of this repository. Those results are retained as a warning about the measured
baseline, not as accuracy evidence for this command.

The [public held-out experiment](../benchmarks/aircraft-category-20261114/README.md)
now supplies an exact model bundle, window-level training recipe and all 416
official test outcomes through the delivered inference path. Propeller-like
precision is only 26.8%, and the unsupported rotorcraft is mislabeled jet-like.
The annotation remains an unreliable experimental diagnostic, never an aircraft
identity or a reason to change the confirmed non-jet search policy. Six-hour
continuous and automatic-proposal controls are retained in the same experiment.
