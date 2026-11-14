# Experimental category baseline: public held-out results

This is a negative result for reliable propeller recognition. The diagnostic
is explicit and report-only; these categories must not filter flights, establish
aircraft identity or justify a location. The [registered protocol](PROTOCOL.md)
and executable recipe retain the contributor's feature definition while fixing
the former training/inference mismatch.

Source: Blake Downward and Jon Nordby, [AeroSonicDB YPAD-0523 v1.1.2](https://zenodo.org/records/10215080),
CC BY-NC 4.0. The original licensed audio stays outside Git. The small real-audio
test fixture has its own attribution. The model was fitted from public audio
features, without using aircraft IDs, locations, test labels or published event
offsets as input features.

## Official test split

The single fixed fit used 1,475 training recordings and 14,651 five-second windows.
It converged in 49 iterations with no fitting warnings. All 416 official test
recordings completed the delivered bounded interval method; none failed decoding
or inference. The model identity is recorded in `training.json` and the result
summary. No thresholds were tuned or model refitted after test predictions.

| True category | Predicted unknown | Predicted propeller-like | Predicted jet-like |
| --- | ---: | ---: | ---: |
| Background (317 recordings) | 282 | 34 | 1 |
| Piston/turboprop (25) | 1 | 15 | 9 |
| Turbofan (73) | 0 | 7 | 66 |
| Unsupported rotorcraft (1) | 0 | 0 | 1 |

Propeller-like precision is **15/56 = 26.8%**, and recall is **15/25 = 60.0%**.
Jet-like precision is **66/77 = 85.7%**, and recall is **66/73 = 90.4%**.
Thirty-five of 317 background recordings received an aircraft-like category.
The unsupported rotorcraft was incorrectly labeled jet-like; this baseline does
not provide reliable out-of-distribution rejection or helicopter recognition.
Overall accuracy is dominated by background and does not establish useful
propeller classification. There are only 25 held-out propeller recordings.

The official split has no repeated file names or sessions, but it does reuse
aircraft identities: 74 of the 99 aircraft test recordings have an identity
present in training. A **post-hoc**, explicitly non-registered identity analysis
of the unchanged predictions is retained in `identity-strata.json`. The unseen
identity stratum has only six propeller, eighteen turbofan and one rotorcraft
recordings. When combined with the held-out background recordings, propeller-like
precision is 4/38 (10.5%). No new fitting or inference was used for this analysis;
it does not establish broad unseen-aircraft performance.

All source file names, sessions, predictions, scores, failures and unknown outcomes
are in `official-test-predictions.csv`; `official-test-summary.json` contains the
full four-column confusion matrix, including the zero-count diagnostic-failure
column. Its generic classification report includes that empty failure category
in the macro average; the per-category results above are the relevant metrics.

## Model and replay

`model.joblib` is the exact locally trained experimental bundle. Loading joblib
executes serialized code; use this only if you trust the repository and the
listed dependency versions. It is not a model from a user upload. The training
and evaluation versions are in `training.json` and the protocol. Cross-version
feature/model equivalence is not claimed.

```bash
PYTHONPATH=src python scripts/diagnose_aircraft_category.py \
  --discovery /path/to/saved/discovery.json --audio /path/to/matching/source.wav \
  --model benchmarks/aircraft-category-20261114/model.joblib \
  --output /path/to/new-category-report.json
```

## Six complete hours: window controls

All 4,320 non-overlapping five-second windows completed, including every
publisher-marked transition. No window failed decoding or inference.

| Publisher label | Predicted unknown | Predicted propeller-like | Predicted jet-like |
| --- | ---: | ---: | ---: |
| Background (3,039 windows) | 2,366 | 630 | 43 |
| Aircraft present (762) | 34 | 323 | 405 |
| Ignore/transition (519) | 213 | 258 | 48 |

The classifier gives aircraft-like labels to **673/3,039 = 22.1%** of background
windows. It gives an aircraft-like label to 728/762 positive windows, but the
publisher's binary labels cannot verify which aircraft category is correct.
Transition predictions are retained and excluded from that comparison. Adjacent
windows are correlated; these counts are not independent-trial confidence bounds.
Complete predictions and aggregate counts are in `continuous-window-*`.
The supplied mapping does not bind the six files to the official split's session
IDs, so independence from its training recordings is not established.

## Six complete hours: automatic proposals

Ordinary discovery completed all six original hours within the fixed 600-second
per-recording limit. It produced 1,593 ridge events in 123 acoustic groups, with
no event windows, aircraft identities, coordinates or publisher labels supplied
to discovery. Groups do not establish independent aircraft. Per-recording results
and elapsed times (412–565 seconds) are in `whole-recording-outcomes.csv`.

The separate diagnostic completed all six saved discoveries and 10,323 actual
five-second inference windows with a 20,000-window budget per recording. It
retained all 1,593 events, including 120 short events that remained unknown;
there were no failed recordings or work-limit outcomes. Each saved discovery
was checked byte-for-byte before and after its diagnostic.

| Publisher state over the entire event interval | Predicted unknown | Predicted propeller-like | Predicted jet-like |
| --- | ---: | ---: | ---: |
| Background only (325 events) | 205 | 98 | 22 |
| Aircraft present throughout (949) | 71 | 427 | 451 |
| Mixed or ignored, unscored (319) | 14 | 207 | 98 |

The classifier assigns aircraft-like labels to **120/325 = 36.9%** of events
contained entirely in publisher-background bins. Binary aircraft-presence labels
cannot validate category accuracy, source identity or discovery recall. Overlapping
ridges and windows are correlated. Mixed and ignored intervals stay unscored.
`automatic-proposal-predictions.csv` retains every event, annotation-bin state,
prediction, reason, window count and available mean model scores;
`automatic-proposal-summary.json` retains every recording's completion status.
No fit, threshold or selection rule was changed after viewing these outcomes.

A separate CLI control on the first actual 240-event saved discovery allowed
only one window. Its first eligible interval required more, so the global budget
stopped inference: all 220 eligible events remained unknown without partial
scores, and the 20 short events stayed unknown. No windows were decoded and the
report was explicitly incomplete (`actual-work-limit-control.json`).

This completes the registered category experiment, with negative results for
reliable propeller recognition. It supplies no geolocation, calibration or
field-corpus acceptance evidence.
