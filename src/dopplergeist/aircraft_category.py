"""Explicit experimental category diagnostics; never called by localization."""
import hashlib
import math
from pathlib import Path
import re
import subprocess

import numpy as np

from .contracts import validate_event

METHOD = "mfcc20-16khz-window-score-mean-v1"
FEATURE_VERSION = "mfcc20-16khz-5s-hop2.5s-window-v1"
LABELS = {"background": "unknown", "propeller": "fixed_wing_propeller_like", "turbofan": "jet_like"}
CATEGORIES = {*LABELS.values(), "helicopter_like"}
SAMPLE_RATE = 16000
WINDOW_S = 5.0
HOP_S = 2.5


def validate_annotation(value):
    """Validate the report-only annotation, outside the shared event contract."""
    if not isinstance(value, dict) or value.keys() != {"label", "method", "experimental"}:
        raise ValueError("Annotation requires only label, method and experimental")
    if not isinstance(value["label"], str) or value["label"] not in CATEGORIES:
        raise ValueError("Unknown acoustic category")
    if (not isinstance(value["method"], str) or not value["method"].strip()
            or any(ord(char) < 32 for char in value["method"])):
        raise ValueError("Annotation method must be nonempty text")
    if value["experimental"] is not True:
        raise ValueError("Category annotations must remain experimental")
    return dict(value)


def window_count(start, end):
    if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end))
            or not 0 <= start < end):
        raise ValueError("Category interval must have finite, positive ordered endpoints")
    duration = end - start
    if duration < WINDOW_S:
        return 0
    steps = math.floor((duration - WINDOW_S) / HOP_S)
    final = start + steps * HOP_S
    return steps + 1 + int(not math.isclose(final, end - WINDOW_S, rel_tol=0, abs_tol=1e-8))


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def event_features(audio):
    """One fixed-size window, using the contributor's original feature recipe."""
    import librosa

    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 1 or len(audio) != int(WINDOW_S * SAMPLE_RATE) or not np.isfinite(audio).all():
        raise ValueError("Category features require exactly five seconds of finite mono audio at 16000 Hz")
    mfcc = librosa.feature.mfcc(y=audio, sr=SAMPLE_RATE, n_mfcc=20,
                                n_fft=1024, hop_length=320, n_mels=64)
    features = np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])[None, :]
    if not np.isfinite(features).all():
        raise ValueError("Non-finite aircraft-category features")
    return features


def decode_window(path, start):
    command = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path),
               "-t", str(WINDOW_S), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
               "-f", "f32le", "pipe:1"]
    result = subprocess.run(command, capture_output=True, check=True, timeout=30)
    audio = np.frombuffer(result.stdout, dtype="<f4")
    if len(audio) != int(WINDOW_S * SAMPLE_RATE) or not np.isfinite(audio).all():
        raise ValueError("Source audio does not contain the complete requested category window")
    return audio


class AircraftCategoryRecognizer:
    def __init__(self, model_path):
        import joblib

        # joblib executes serialized code. Only explicit, trusted local models.
        bundle = joblib.load(model_path)
        if not isinstance(bundle, dict) or bundle.get("feature_version") != FEATURE_VERSION:
            raise ValueError("Incompatible category model feature version")
        if bundle.get("aggregation") != "mean_window_predict_proba":
            raise ValueError("Unsupported category aggregation")
        self.scaler, self.classifier = bundle["scaler"], bundle["classifier"]
        self.classes = [str(value) for value in self.classifier.classes_]
        if len(self.classes) != len(LABELS) or set(self.classes) != set(LABELS):
            raise ValueError("Unexpected category model classes")
        if self.scaler.n_features_in_ != 40:
            raise ValueError("Category scaler must accept 40 features")
        if self.classifier.n_features_in_ != 40:
            raise ValueError("Category classifier must accept 40 features")

    def score_window(self, audio):
        scores = np.asarray(self.classifier.predict_proba(
            self.scaler.transform(event_features(audio))), dtype=float)
        if (scores.shape != (1, len(self.classes)) or not np.isfinite(scores).all()
                or np.any(scores < 0) or np.any(scores > 1)
                or not np.isclose(scores.sum(), 1.0)):
            raise ValueError("Invalid category model output")
        return scores[0]

    def classify_interval(self, audio_path, start, end, *, max_windows=1024):
        """The common bounded inference path for diagnostics and evaluation."""
        if type(max_windows) is not int or max_windows < 0:
            raise ValueError("Interval window allowance must be a nonnegative integer")
        annotation = {**validate_annotation({"label": "unknown", "method": METHOD, "experimental": True}),
                      "windows_scored": 0, "reason": "insufficient_audio"}
        needed = window_count(start, end)
        if not needed:
            return annotation
        if needed > max_windows:
            return dict(annotation, reason="work_limit")
        steps = math.floor((end - start - WINDOW_S) / HOP_S)
        total = np.zeros(len(self.classes))
        for index in range(needed):
            offset = end - WINDOW_S if index > steps else start + index * HOP_S
            total += self.score_window(decode_window(audio_path, offset))
        scores = total / needed
        predicted = self.classes[int(np.argmax(scores))]
        annotation.update(label=LABELS[predicted], windows_scored=needed, reason="model_output",
                          mean_model_scores=dict(zip(self.classes, scores.tolist())))
        return annotation


def diagnose(discovery, audio_path, model_path, *, max_windows=1024):
    """Return a separate report; never mutate discovery, events or saved jobs."""
    if type(max_windows) is not int or max_windows <= 0:
        raise ValueError("max_windows must be a positive integer")
    expected = discovery.get("source_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError("Saved discovery must identify its source SHA-256")
    if file_digest(audio_path) != expected.lower():
        raise ValueError("Category audio does not match the saved discovery source SHA-256")
    events = discovery.get("events")
    if not isinstance(events, list):
        raise ValueError("Saved discovery must contain an events list")
    events = [validate_event(event) for event in events]
    if len({event["event_id"] for event in events}) != len(events):
        raise ValueError("Saved event IDs must be unique")
    recognizer = AircraftCategoryRecognizer(model_path)
    rows, cached = [], {}
    examined, limited = 0, False
    for event in events:
        start, end = event["start_s"], event["end_s"]
        key = (start, end)
        if key not in cached:
            annotation = recognizer.classify_interval(audio_path, start, end,
                                max_windows=0 if limited else max_windows - examined)
            examined += annotation["windows_scored"]
            limited = limited or annotation["reason"] == "work_limit"
            cached[key] = annotation
        rows.append({"event_id": event["event_id"], "start_s": start, "end_s": end, **cached[key]})
    return {"schema_version": 1, "source_sha256": expected.lower(),
            "model_sha256": file_digest(model_path), "feature_version": FEATURE_VERSION,
            "events": rows, "windows_scored": examined, "max_windows": max_windows,
            "complete": not limited,
            "limitations": ["Experimental acoustic categories are not aircraft identities or calibrated probabilities.",
                            "Background maps to unknown; helicopter recognition is not implemented.",
                            "No localization, flight filtering, scoring or event-independence decision uses this report."]}
