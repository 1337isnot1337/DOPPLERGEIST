import importlib.util
import json
from pathlib import Path
import sys

import pytest

from aircraft_geoloc.evaluation import detection_counts, evaluate


def test_maximum_matching_and_harmonic_deduplication():
    truth = [{"start_s": 0, "end_s": 10}, {"start_s": 10, "end_s": 20}]
    predicted = [{"start_s": 0, "end_s": 20, "harmonic_group_id": "a"},
                 {"start_s": 0, "end_s": 10, "harmonic_group_id": "b"},
                 {"start_s": 0, "end_s": 10, "harmonic_group_id": "b"},
                 {"start_s": 30, "end_s": 35}]
    assert detection_counts(truth, predicted) == {"true_positives": 2, "misses": 0, "false_alarms": 1}


def test_all_outcomes_and_eligibility():
    cases = [{"case_id": str(i), "split": "held_out", "scope": "control"} for i in range(5)]
    truth = {"0": {"location": [40, -100], "location_accuracy_eligible": True},
             "1": {"location": [40, -100], "location_accuracy_eligible": True},
             "2": {"events": [], "expect_inconclusive": True},
             "3": {"location": [40, -100], "location_accuracy_eligible": False}}
    predictions = {"0": {"status": "succeeded", "candidates": [{"lat": 40, "lon": -100}]},
                   "1": {"status": "inconclusive", "candidates": [{"lat": 41, "lon": -100}]},
                   "2": {"status": "succeeded", "candidates": [{"lat": 41, "lon": -100}]},
                   "3": {"status": "succeeded", "candidates": [{"lat": 42, "lon": -100}]}}
    report = evaluate({"cases": cases}, predictions, truth)
    assert len(report["cases"]) == 5
    assert report["summary"]["eligible_location_cases"] == 2
    assert report["summary"]["successful_locations_within_threshold"] == 1
    assert report["summary"]["false_localizations"] == 1
    assert report["summary"]["execution_failures"] == 1
    assert not report["cases"][1]["location_returned"]
    assert report["cases"][3]["location_error_m"] > 100


def test_case_ids_and_terminal_results_are_required():
    cases = {"cases": [{"case_id": "a", "split": "held_out", "scope": "test"}]}
    with pytest.raises(ValueError, match="absent"):
        evaluate(cases, {"unlisted": {}}, {})
    with pytest.raises(ValueError, match="Nonterminal"):
        evaluate(cases, {"a": {"status": "running"}}, {})
    with pytest.raises(ValueError, match="no candidate"):
        evaluate(cases, {"a": {"status": "succeeded"}}, {})


def test_runner_does_not_require_truth_and_measures_each_process(tmp_path):
    import hashlib
    module_path = Path(__file__).resolve().parents[1] / "scripts/run_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_benchmark", module_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "audio.mp3").write_bytes(b"protocol fixture; decoder not invoked")
    (inputs / "request.json").write_text(json.dumps({"schema_version": 1, "audio_path": "audio.mp3"}))
    manifest = {"cases": [{"case_id": "one", "split": "held_out", "scope": "transport_fixture",
                          "request": "request.json", "audio_sha256": hashlib.sha256((inputs / "audio.mp3").read_bytes()).hexdigest()}]}
    (inputs / "manifest.json").write_text(json.dumps(manifest))
    # No truth directory exists. This checks process protocol, not localization.
    script = "import json,sys;from pathlib import Path;p=Path(sys.argv[1]);r={'schema_version':1,'job_id':'one','status':'inconclusive','reason_code':'no_events','message':'Protocol fixture'};(p/'result.json').write_text(json.dumps(r))"
    result = runner.run(inputs / "manifest.json", tmp_path / "run", [sys.executable, "-c", script, "{output}"])
    assert result["one"]["status"] == "inconclusive"
    assert result["one"]["runtime_s"] > 0
    assert result["one"]["peak_memory_bytes"] > 0
    with pytest.raises(FileExistsError):
        runner.run(inputs / "manifest.json", tmp_path / "run", [sys.executable])


def test_frozen_replay_preserves_all_cases():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("evaluate_frozen", root / "scripts/evaluate_frozen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((root / "benchmarks/frozen-manifest.json").read_text())
    truth = json.loads((root / "benchmarks/truth/frozen-labels.json").read_text())
    report = evaluate(manifest, module.frozen_predictions(root), truth)
    assert len(report["cases"]) == 48
    assert report["summary"]["detection_misses"] == 7
    assert report["summary"]["execution_failures"] == 3
    faint = next(c for c in report["cases"] if c["case_id"] == "reference-faint-alltypes-local")
    assert 350 < faint["location_error_m"] < 365
    assert faint["within_threshold"] is False
    assert faint["location_accuracy_eligible"] is False
