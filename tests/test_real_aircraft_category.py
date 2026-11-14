"""Diagnostic isolation checks on licensed real non-jet audio, not accuracy tests.

Fixture: Blake Downward, AeroSonicDB YPAD-0523 v1.1.2, CC BY-NC 4.0,
https://zenodo.org/records/10215080 ; 7C293D_2023-04-22_10-14-18_0_1.wav.
Publisher class 1 (piston). Source SHA-256 is in the committed candidate manifest.
The fixture is seconds 22..27, converted to mono 16 kHz FLAC. These checks
neither load a classifier nor invent model scores or geolocation results.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from dopplergeist import aircraft_category as category
from dopplergeist.contracts import event_measure_settings, validate_event
from dopplergeist.discovery import discover_events
from dopplergeist.intake import intake_recording


ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "tests/fixtures/aerosonic-propeller-7c293d-22s.flac"


def test_category_environment_cannot_break_ordinary_discovery(tmp_path, monkeypatch):
    recording = intake_recording(AUDIO, tmp_path / "intake")
    baseline = discover_events(recording, plot_summary=False)
    monkeypatch.setenv("DOPPLERGEIST_CATEGORY_MODEL", str(tmp_path / "absent.joblib"))
    monkeypatch.setenv("DOPPLERGEIST_CATEGORY_AUDIO", str(tmp_path / "wrong-recording.wav"))
    assert discover_events(recording, plot_summary=False) == baseline
    assert baseline == []  # The actual excerpt is shorter than the acceptance window.


def test_source_mismatch_is_rejected_before_loading_any_model(tmp_path, monkeypatch):
    discovery = {"source_sha256": "0" * 64, "events": []}
    before = deepcopy(discovery)
    def forbidden(*args, **kwargs):
        raise AssertionError("A mismatched source must never reach model loading")
    monkeypatch.setattr(category, "AircraftCategoryRecognizer", forbidden)
    with pytest.raises(ValueError, match="does not match"):
        category.diagnose(discovery, AUDIO, tmp_path / "absent.joblib")
    assert discovery == before


def test_missing_model_does_not_modify_saved_discovery(tmp_path):
    discovery = {"source_sha256": category.file_digest(AUDIO), "events": []}
    before = deepcopy(discovery)
    with pytest.raises((OSError, ImportError)):
        category.diagnose(discovery, AUDIO, tmp_path / "absent.joblib")
    assert discovery == before


def test_window_decode_is_bounded_and_rejects_truncation():
    audio = category.decode_window(AUDIO, 0)
    assert audio.shape == (80000,) and audio.nbytes == 320000
    assert np.isfinite(audio).all() and np.any(audio)
    with pytest.raises(ValueError, match="complete requested"):
        category.decode_window(AUDIO, 4)


def test_actual_window_features_are_finite_and_reject_oversized_audio():
    pytest.importorskip("librosa")
    audio = category.decode_window(AUDIO, 0)
    features = category.event_features(audio)
    assert features.shape == (1, 40) and np.isfinite(features).all()
    # Two consecutive real recorded windows exceed this single-window interface.
    with pytest.raises(ValueError, match="exactly five seconds"):
        category.event_features(np.concatenate([audio, audio]))


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_window_budgets_are_rejected_before_inference(budget):
    with pytest.raises(ValueError, match="positive integer"):
        category.diagnose({}, AUDIO, "unused.joblib", max_windows=budget)


def test_command_refuses_existing_output_and_preserves_input(tmp_path):
    source = tmp_path / "discovery.json"
    source.write_text(json.dumps({"source_sha256": category.file_digest(AUDIO), "events": []}))
    before = source.read_bytes()
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/diagnose_aircraft_category.py"),
                                "--discovery", str(source), "--audio", str(AUDIO),
                                "--model", str(tmp_path / "absent.joblib"), "--output", str(source)],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 2 and "Output already exists" in completed.stderr
    assert source.read_bytes() == before


def test_annotation_validation_stays_outside_the_real_event_contract():
    recorded = json.loads((ROOT / "tests/data/shared-ridges-real.json").read_text())
    event = recorded["shared"]["events"][0]
    before = deepcopy(event)
    settings = event_measure_settings(event)
    for label in category.CATEGORIES:
        annotation = {"label": label, "method": category.METHOD, "experimental": True}
        assert category.validate_annotation(annotation) == annotation
        assert validate_event(event) == before
        assert event_measure_settings(event) == settings
        with pytest.raises(ValueError):
            validate_event(dict(event, acoustic_aircraft_category=annotation))
    assert event == before


@pytest.mark.parametrize("change", [
    {"label": "Boeing 737"}, {"label": []}, {"experimental": False},
    {"experimental": 1}, {"method": " "}, {"method": "method\n"}, {"probability": 0.9},
])
def test_invalid_report_annotations_are_rejected(change):
    with pytest.raises(ValueError):
        category.validate_annotation({"label": "unknown", "method": category.METHOD,
                                      "experimental": True, **change})


def test_insufficient_audio_and_budget_do_not_invent_model_output(monkeypatch):
    recognizer = object.__new__(category.AircraftCategoryRecognizer)
    def forbidden(*args, **kwargs):
        raise AssertionError("No decoder or classifier may run without a complete allowed window")
    monkeypatch.setattr(category, "decode_window", forbidden)
    monkeypatch.setattr(recognizer, "score_window", forbidden)
    short = recognizer.classify_interval(AUDIO, 0.0, 4.0)
    limited = recognizer.classify_interval(AUDIO, 0.0, 5.0, max_windows=0)
    assert short["reason"] == "insufficient_audio" and limited["reason"] == "work_limit"
    for row in (short, limited):
        assert row["label"] == "unknown" and row["windows_scored"] == 0
        assert "mean_model_scores" not in row


def test_public_trained_model_uses_the_same_real_window_path():
    pytest.importorskip("librosa")
    pytest.importorskip("sklearn")
    recognizer = category.AircraftCategoryRecognizer(
        ROOT / "benchmarks/aircraft-category-20261114/model.joblib")
    scores = recognizer.score_window(category.decode_window(AUDIO, 0.0))
    annotation = recognizer.classify_interval(AUDIO, 0.0, 5.0, max_windows=1)
    assert annotation["reason"] == "model_output" and annotation["windows_scored"] == 1
    assert annotation["experimental"] is True
    np.testing.assert_allclose([annotation["mean_model_scores"][name] for name in recognizer.classes], scores)
    assert annotation["label"] == category.LABELS[recognizer.classes[int(np.argmax(scores))]]
    # This checks real inference wiring, not whether this short excerpt's label
    # is correct. Category errors belong in the retained held-out evaluation.
