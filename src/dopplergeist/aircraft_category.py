"""Experimental event-audio category recognition; never filters flights."""
import hashlib
import os
from pathlib import Path

import numpy as np

from .audio import decode
from .contracts import validate_acoustic_aircraft_category

METHOD = "aerosonic-window-logistic-mfcc40-v1"
LABELS = {
    "background": "unknown",
    "propeller": "fixed_wing_propeller_like",
    "turbofan": "jet_like",
}
FEATURE_VERSION = "mfcc20-16khz-5s-hop2.5s-window-v1"


def event_features(audio, sr=16000):
    import librosa

    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError("Category audio must be finite mono samples")
    if sr != 16000:
        raise ValueError("Category features require 16000 Hz audio")

    size, hop = 5 * sr, int(2.5 * sr)
    if len(audio) < size:
        return np.empty((0, 40))

    starts = list(range(0, len(audio) - size + 1, hop))
    if starts[-1] != len(audio) - size:
        starts.append(len(audio) - size)

    vectors = []
    for start in starts:
        mfcc = librosa.feature.mfcc(
            y=audio[start:start + size],
            sr=sr,
            n_mfcc=20,
            n_fft=1024,
            hop_length=320,
            n_mels=64,
        )
        vectors.append(np.concatenate([
            mfcc.mean(axis=1),
            mfcc.std(axis=1),
        ]))
    features = np.asarray(vectors)
    if not np.isfinite(features).all():
        raise ValueError("Non-finite aircraft-category features")
    return features


class AircraftCategoryRecognizer:
    def __init__(self, model_path):
        import joblib

        # Load only a model artifact you created and trust.
        bundle = joblib.load(model_path)
        if not isinstance(bundle, dict):
            raise ValueError("Expected the window-baseline model bundle")
        if bundle.get("feature_version") != FEATURE_VERSION:
            raise ValueError(
                "Incompatible category model: expected the original "
                "40-feature category-window-v1 model"
            )
        if bundle.get("aggregation") != "mean_window_predict_proba":
            raise ValueError("Unsupported category aggregation")
        self.scaler = bundle["scaler"]
        self.classifier = bundle["classifier"]
        if set(self.classifier.classes_) != set(LABELS):
            raise ValueError("Unexpected category model classes")
        if self.scaler.n_features_in_ != 40:
            raise ValueError("Category scaler must accept 40 features")

    def classify(self, audio):
        features = event_features(audio)
        if not len(features):
            return validate_acoustic_aircraft_category({
                "label": "unknown",
                "method": METHOD + "-insufficient-audio",
                "experimental": True,
            })

        scores = self.classifier.predict_proba(
            self.scaler.transform(features)
        ).mean(axis=0)

        if not np.isfinite(scores).all():
            raise ValueError("Non-finite category model output")

        predicted = str(self.classifier.classes_[int(np.argmax(scores))])
        return validate_acoustic_aircraft_category({
            "label": LABELS[predicted],
            "method": METHOD,
            "experimental": True,
        })


def annotate_discovered_events(events, recording):
    """Opt-in recognition using explicitly supplied original source audio."""
    model_path = os.environ.get("DOPPLERGEIST_CATEGORY_MODEL")
    audio_path = os.environ.get("DOPPLERGEIST_CATEGORY_AUDIO")
    if not model_path and not audio_path:
        return
    if not model_path or not audio_path:
        raise ValueError(
            "Set both DOPPLERGEIST_CATEGORY_MODEL and "
            "DOPPLERGEIST_CATEGORY_AUDIO"
        )

    model_path, audio_path = Path(model_path), Path(audio_path)
    if not model_path.is_file() or not audio_path.is_file():
        raise FileNotFoundError("Category model or source audio does not exist")

    # Prevent accidentally classifying a different recording.
    expected = recording.metadata.get("source_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Source SHA-256 is required for category recognition")
    digest = hashlib.sha256()
    with audio_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest().lower() != expected.lower():
        raise ValueError(
            "Category audio does not match recording source_sha256; "
            "supply the original input file"
        )

    recognizer = AircraftCategoryRecognizer(model_path)
    annotations = {}
    pending = []
    for event in events:
        start, end = float(event["start_s"]), float(event["end_s"])
        key = (start, end)
        if key not in annotations:
            audio, _ = decode(
                audio_path,
                start=start,
                duration=end - start,
                sample_rate=16000,
            )
            annotations[key] = recognizer.classify(audio)
        pending.append(dict(annotations[key]))

    # Attach only after every event was successfully processed.
    for event, annotation in zip(events, pending):
        event["acoustic_aircraft_category"] = annotation
