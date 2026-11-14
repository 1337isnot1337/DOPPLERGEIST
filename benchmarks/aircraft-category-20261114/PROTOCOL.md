# Public aircraft-category experiment

Registered before audio inspection in [issue #355](https://github.com/1337isnot1337/DOPPLERGEIST/issues/355#issuecomment-6872849599).
This evaluates the contributor's proposed optional diagnostic, not localization.

- Source: Blake Downward and Jon Nordby, AeroSonicDB YPAD-0523 v1.1.2,
  [Zenodo 10215080](https://zenodo.org/records/10215080), CC BY-NC 4.0.
  Download `audio.zip`, `env_audio.zip`, `sample_meta.csv`, and
  `environment_class_mappings.csv`; verify downloads against the record's checksums.
- Fit on all 1,475 official training records labeled background, piston,
  turboprop or turbofan. Retain the official split/session separation. Four
  training rotorcraft are excluded because this model does not recognize them.
- Use the contributor's 16 kHz mono, five-second MFCC20 means and standard
  deviations (40 features), 1,024-point FFT, 320-sample spectral hop, 64 mel bands.
  Classifier windows advance 2.5 seconds, with a final full window ending at the
  interval boundary. Training uses every complete window from the full source
  files. File names, aircraft metadata and publisher offsets are not features.
- StandardScaler then LogisticRegression: C=1, balanced class weights, lbfgs,
  max_iter=2000, random_state=20261114. No held-out threshold tuning. The predicted
  class has the largest mean window score; background maps to unknown. Scores
  are uncalibrated. Helicopter recognition is not claimed.
- Evaluate all 416 official test files, including the unsupported rotorcraft
  control, through the same bounded interval method used by the diagnostic.
  Retain every failure. Report full confusion, per-category precision/recall,
  false labels, background and unknown outcomes.
- Evaluate every five-second interval of all six untouched one-hour continuous
  environment recordings. Their published labels are binary aircraft/background,
  with transitional `ignore` intervals. Preserve all predictions and ignore counts;
  these binary labels cannot establish jet/propeller category accuracy.
- Run ordinary automatic discovery on the complete six recordings, then apply the
  saved-discovery diagnostic. Join publisher labels only afterward. Mixed and
  ignored event intervals remain explicitly unscored. Do not supply event bands,
  time windows, aircraft identities or coordinates to discovery.
- One bounded audio window is decoded at a time. An interval that exceeds the
  remaining work budget stays unknown; partial results cannot become a category.
  No classifier result may affect the flight filter, scores, independent-event
  counts or accepted location.

Runtime at first execution: Python 3.14.6, librosa 1.0.1, scikit-learn 1.9.1,
NumPy 2.5.4, SciPy 1.18.1, joblib 1.6.0. The training output records these versions,
parameters, warnings and the model identity. No synthetic data, private sources
or outreach is allowed. No audio is committed here.
Python 3.11 isolation/feature checks use librosa 0.11.0 because librosa 1.0.1
requires Python 3.12 or later; these checks do not establish cross-version model
equivalence. The registered training/evaluation environment stays unchanged.

Commands, from a checkout with optional classifier dependencies installed:

```bash
PYTHONPATH=src python scripts/evaluate_aircraft_category.py prepare --data /path/to/public-data
PYTHONPATH=src python scripts/evaluate_aircraft_category.py fit --data /path/to/public-data --output /path/to/new-training --workers 2
PYTHONPATH=src python scripts/evaluate_aircraft_category.py test --data /path/to/public-data --model /path/to/new-training/model.joblib --output /path/to/new-test --workers 2
PYTHONPATH=src python scripts/evaluate_aircraft_category.py environment --data /path/to/public-data --model /path/to/new-training/model.joblib --output /path/to/new-environment --workers 2
PYTHONPATH=src python scripts/evaluate_aircraft_category.py discover --data /path/to/public-data --output /path/to/new-discoveries
PYTHONPATH=src python scripts/evaluate_aircraft_category.py proposals --data /path/to/public-data --discoveries /path/to/new-discoveries --model /path/to/new-training/model.joblib --output /path/to/new-proposal-evaluation
```

After viewing the official-test predictions, an additional identity-stratified
analysis was added to distinguish held-out sessions from unseen aircraft. It
does not change the registered fit, predictions, model, thresholds or population.
It is explicitly post-hoc and cannot replace the full registered result:

```bash
PYTHONPATH=src python scripts/evaluate_aircraft_category.py identities --data /path/to/public-data --predictions /path/to/new-test/predictions.csv --output /path/to/new-identity-analysis
```
