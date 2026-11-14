#!/usr/bin/env python3
"""Fit and evaluate the frozen public AeroSonicDB window baseline (#355).

Uses real audio only. Run prepare, fit, test, then environment in that order.
Test labels never enter fitting. Category outputs never enter localization.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
from importlib.metadata import version
import inspect
import json
from pathlib import Path
import shutil
import time
import warnings
import zipfile

import numpy as np

from dopplergeist.aircraft_category import (
    AircraftCategoryRecognizer, FEATURE_VERSION, HOP_S, LABELS, WINDOW_S,
    decode_window, event_features, file_digest, window_count,
)


SUBCLASSES = {"0": "background", "1": "propeller", "2": "propeller", "3": "turbofan"}


def metadata(root):
    with (root / "sample_meta.csv").open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    rows = list(rows)
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["empty"])
        writer.writeheader()
        writer.writerows(rows)


def prepare(root):
    """Extract named WAV members, preserving all files and rejecting collisions."""
    for archive_name, directory in (("audio.zip", "audio"), ("env_audio.zip", "environment")):
        output = root / directory
        output.mkdir(exist_ok=True)
        names = set()
        with zipfile.ZipFile(root / archive_name) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                name = Path(entry.filename).name
                if not name.lower().endswith(".wav") or name in names:
                    raise ValueError(f"Unexpected or duplicate source member: {entry.filename}")
                names.add(name)
                path = output / name
                if path.exists():
                    if path.stat().st_size != entry.file_size:
                        raise ValueError(f"Existing extracted source has a different size: {path}")
                    continue
                temporary = path.with_suffix(".extracting")
                with archive.open(entry) as source, temporary.open("xb") as target:
                    shutil.copyfileobj(source, target)
                temporary.rename(path)  # ZipFile checked the original member CRC.
        print(f"Prepared {len(names)} original WAVs in {output}", flush=True)


def feature_rows(root, row):
    """Cache the exact bounded runtime features; cache inputs are explicit."""
    path = root / "audio" / row["filename"]
    state = path.stat()
    recipe = "\n".join((FEATURE_VERSION, version("librosa"), inspect.getsource(event_features),
                         inspect.getsource(decode_window)))
    cache = root / "feature-cache" / hashlib.sha256(recipe.encode()).hexdigest()[:16]
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / (path.stem + ".npz")
    if destination.exists():
        with np.load(destination, allow_pickle=False) as saved:
            if int(saved["mtime"]) == state.st_mtime_ns and int(saved["bytes"]) == state.st_size:
                return saved["features"]
    duration = float(row["file_length"])
    count = window_count(0.0, duration)
    if not count:
        raise ValueError(f"Training/test source has no complete five-second window: {path.name}")
    steps = int((duration - WINDOW_S) // HOP_S)
    features = []
    for index in range(count):
        start = duration - WINDOW_S if index > steps else index * HOP_S
        features.append(event_features(decode_window(path, start))[0])
    matrix = np.asarray(features)
    np.savez(destination, features=matrix, mtime=state.st_mtime_ns, bytes=state.st_size)
    return matrix


def fit(root, output, workers):
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    output.mkdir(parents=True, exist_ok=False)
    rows = [row for row in metadata(root) if row["train-test"] == "train" and row["subclass"] in SUBCLASSES]
    assert len(rows) == 1475, "The frozen source population changed"
    first = feature_rows(root, rows[0])  # Initialize optional feature libraries on real training audio.
    matrices = [first]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, matrix in enumerate(pool.map(lambda row: feature_rows(root, row), rows[1:]), 2):
            matrices.append(matrix)
            if index % 50 == 0:
                print(f"Training features {index}/{len(rows)}", flush=True)
    x = np.concatenate(matrices)
    y = np.concatenate([np.repeat(SUBCLASSES[row["subclass"]], len(matrix))
                        for row, matrix in zip(rows, matrices)])
    scaler = StandardScaler().fit(x)
    classifier = LogisticRegression(C=1, class_weight="balanced", solver="lbfgs", max_iter=2000,
                                    random_state=20261114)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        classifier.fit(scaler.transform(x), y)
    versions = {name: version(name) for name in ("numpy", "scipy", "librosa", "scikit-learn", "joblib")}
    bundle = {"feature_version": FEATURE_VERSION, "aggregation": "mean_window_predict_proba",
              "training_unit": "window", "scaler": scaler, "classifier": classifier,
              "source": "AeroSonicDB YPAD-0523 v1.1.2, Zenodo 10215080", "versions": versions}
    joblib.dump(bundle, output / "model.joblib")
    summary = {"records": len(rows), "windows": len(y), "held_out_records_used": 0,
               "excluded_training_rotorcraft": 4, "classes": classifier.classes_.tolist(),
               "versions": versions, "parameters": classifier.get_params(),
               "fit_warnings": [str(item.message) for item in caught],
               "iterations": classifier.n_iter_.tolist(), "seconds": time.monotonic() - started,
               "model_sha256": file_digest(output / "model.joblib")}
    (output / "training.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


def score_file(root, row, recognizer):
    expected_class = SUBCLASSES.get(row["subclass"], "unsupported_rotorcraft")
    expected_label = LABELS.get(expected_class, "unknown")
    answer = {"filename": row["filename"], "session": row["session"], "subclass": row["subclass"],
              "expected_class": expected_class, "expected_label": expected_label,
              "predicted_label": "diagnostic_failed", "reason": "diagnostic_failed", "windows_scored": 0,
              "background_score": "", "propeller_score": "", "turbofan_score": "", "error": ""}
    try:
        result = recognizer.classify_interval(root / "audio" / row["filename"],
                                              0.0, float(row["file_length"]), max_windows=1024)
        answer.update(predicted_label=result["label"], reason=result["reason"],
                      windows_scored=result["windows_scored"])
        for label, score in result.get("mean_model_scores", {}).items():
            answer[label + "_score"] = score
    except Exception as error:
        answer["error"] = type(error).__name__ + ": " + str(error)
    return answer


def metrics(rows):
    from sklearn.metrics import classification_report, confusion_matrix
    labels = ["unknown", "fixed_wing_propeller_like", "jet_like", "diagnostic_failed"]
    expected, predicted = [row["expected_label"] for row in rows], [row["predicted_label"] for row in rows]
    return {"records": len(rows), "labels": labels,
            "confusion": confusion_matrix(expected, predicted, labels=labels).tolist(),
            "classification_report": classification_report(expected, predicted, labels=labels,
                                                            zero_division=0, output_dict=True),
            "failed": sum(row["reason"] == "diagnostic_failed" for row in rows),
            "unsupported_rotorcraft": [row for row in rows if row.get("expected_class") == "unsupported_rotorcraft"]}


def test(root, model, output, workers):
    output.mkdir(parents=True, exist_ok=False)
    rows = [row for row in metadata(root) if row["train-test"] == "test"]
    assert len(rows) == 416, "The frozen official test population changed"
    recognizer = AircraftCategoryRecognizer(model)
    started = time.monotonic()
    answers = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in enumerate(pool.map(lambda row: score_file(root, row, recognizer), rows), 1):
            answers.append(result)
            if index % 25 == 0:
                print(f"Official test {index}/{len(rows)}", flush=True)
    write_csv(output / "predictions.csv", answers)
    summary = dict(metrics(answers), model_sha256=file_digest(model), seconds=time.monotonic() - started,
                   scope="All official held-out files; identical bounded interval inference to the diagnostic")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


def environment(root, model, output, workers):
    output.mkdir(parents=True, exist_ok=False)
    with (root / "environment_class_mappings.csv").open(newline="") as stream:
        labels = list(csv.DictReader(stream))
    assert len(labels) == 720, "Expected all 720 five-second intervals per original hour"
    recognizer = AircraftCategoryRecognizer(model)
    tasks = [(str(site + 1), index, row[str(site)]) for site in range(6) for index, row in enumerate(labels)]

    def one(task):
        site, index, expected = task
        row = {"recording": site + "_AUDIO.wav", "start_s": index * 5,
               "publisher_label": expected, "predicted_label": "diagnostic_failed",
               "reason": "diagnostic_failed", "error": ""}
        try:
            result = recognizer.classify_interval(root / "environment" / row["recording"],
                                                   index * 5.0, (index + 1) * 5.0, max_windows=1)
            row.update(predicted_label=result["label"], reason=result["reason"])
        except Exception as error:
            row["error"] = type(error).__name__ + ": " + str(error)
        return row

    answers = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, row in enumerate(pool.map(one, tasks), 1):
            answers.append(row)
            if index % 200 == 0:
                print(f"Continuous recording windows {index}/{len(tasks)}", flush=True)
    write_csv(output / "predictions.csv", answers)
    table = {truth: {prediction: sum(row["publisher_label"] == truth and row["predicted_label"] == prediction
                                  for row in answers)
                     for prediction in ("unknown", "fixed_wing_propeller_like", "jet_like", "diagnostic_failed")}
             for truth in ("0", "1", "ignore")}
    summary = {"windows": len(answers), "publisher_labels_by_prediction": table,
               "model_sha256": file_digest(model), "seconds": time.monotonic() - started,
               "scope": "All six original hours. Publisher labels are binary aircraft/background; category accuracy is not measured here."}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "fit", "test", "environment"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 4:
        parser.error("Use one to four bounded workers")
    if args.command != "prepare" and args.output is None:
        parser.error("--output is required")
    if args.command in ("test", "environment") and args.model is None:
        parser.error("--model is required")
    if args.command == "prepare":
        prepare(args.data)
    elif args.command == "fit":
        fit(args.data, args.output, args.workers)
    elif args.command == "test":
        test(args.data, args.model, args.output, args.workers)
    else:
        environment(args.data, args.model, args.output, args.workers)


if __name__ == "__main__":
    main()
