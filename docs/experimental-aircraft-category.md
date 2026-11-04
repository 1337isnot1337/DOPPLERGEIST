# Experimental acoustic aircraft category recognition

The standard discover_events path can annotate detected events using an
externally supplied AeroSonicDB category-window-v1 model.

## Runtime requirements

The runtime must provide numpy, scipy, librosa, scikit-learn, joblib, and ffmpeg.
Use a compatible scikit-learn environment for the serialized model.
Load only a joblib artifact you created or otherwise trust.

Set both environment variables before running discovery:

- DOPPLERGEIST_CATEGORY_MODEL: path to category-window-v1/model.joblib
- DOPPLERGEIST_CATEGORY_AUDIO: path to the original input audio file

The original audio SHA-256 must match recording.metadata["source_sha256"].
With neither variable set, discovery behavior is unchanged.
The model artifact and source audio are not included in this repository.

## Recognition

Each event interval is decoded at 16000 Hz. Five-second windows with
2.5-second hops produce 20 MFCC means and 20 temporal standard deviations.
The trained scaler and classifier are applied to those vectors, and window
scores are averaged.

Model labels map as follows:

- turbofan -> jet_like
- propeller -> fixed_wing_propeller_like
- background -> unknown

Events shorter than five seconds are reported as unknown.

Annotations are experimental and report-only. They do not change ridge
measurements, flight filters, or identity matching. No calibrated probability
or helicopter recognition is provided.

## Limitations

This integrates inference; it does not establish reliable aircraft recognition.
Development evaluation showed substantial microphone/session-dependent errors.
Event-interval inference has not been independently validated.
The separate coherent-trace discovery path is not annotated by this change.
