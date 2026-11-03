from copy import deepcopy
import json
from pathlib import Path

import pytest

from dopplergeist.contracts import (
    event_measure_settings, validate_candidate, validate_event, validate_recording,
    validate_request, validate_result,
)


EXAMPLES = Path(__file__).resolve().parents[1] / "docs/examples"


def example(name):
    return json.loads((EXAMPLES / f"{name}.json").read_text())


def test_examples_roundtrip_without_mutating_inputs():
    for name, validator in (("analysis-request", validate_request), ("detected-event", validate_event),
                            ("job-result", validate_result), ("job-needs-input", validate_result)):
        original = example(name)
        before = deepcopy(original)
        clean = validator(original)
        assert validator(json.loads(json.dumps(clean, allow_nan=False))) == clean
        assert original == before
    request = {"schema_version": 1, "audio_path": "clip.mp3"}
    assert validate_request(request)["search"] == {"coverage": "conus"}
    assert "time_window" not in validate_request(request)


def test_time_window_is_recording_start_with_explicit_timezone():
    request = example("analysis-request")
    request["time_window"].update(start_utc="2026-09-08T12:00:00+02:00", end_utc="2026-09-08T10:00:00Z")
    assert validate_request(request)["time_window"]["start_utc"] == "2026-09-08T10:00:00Z"
    for invalid in ("2026-09-08", "2026-09-08T12:00:00", 1788861600):
        request["time_window"]["start_utc"] = invalid
        with pytest.raises(ValueError):
            validate_request(request)


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2}, {"audio_path": ""},
    {"true_lat": 40.0}, {"events": []}, {"search": {"coverage": "global"}},
    {"search": {"coverage": "conus", "bounds_wsen": [-100, 40, -110, 45]}},
    {"search": {"coverage": "conus", "bounds_wsen": [-110, 40, float("nan"), 45]}},
])
def test_invalid_request_and_truth_fields_rejected(change):
    request = example("analysis-request")
    request.update(change)
    with pytest.raises(ValueError):
        validate_request(request)


def test_untrusted_time_source_and_reversed_window_rejected():
    request = example("analysis-request")
    request["time_window"]["source"] = "file_mtime"
    with pytest.raises(ValueError, match="Time source"):
        validate_request(request)
    request["time_window"]["source"] = "user"
    request["time_window"]["start_utc"] = "2026-09-10T00:00:00Z"
    with pytest.raises(ValueError, match="reversed"):
        validate_request(request)


def test_ridge_time_and_frequency_are_recording_relative():
    event = example("detected-event")
    event["start_s"] = 100
    event["end_s"] = 160
    with pytest.raises(ValueError):
        validate_event(event)  # Chunk-local points were not shifted by +90 s.
    for point in event["ridge"]:
        point["time_s"] += 90
    validate_event(event)
    settings = event_measure_settings(event)
    assert settings["start_s"] == 100
    assert settings["band_hz"] == [80.0, 180.0]
    assert "ridge" not in settings and "quality" not in settings
    assert "f0_range_hz" not in settings  # No invented rest-frequency bounds.


@pytest.mark.parametrize("field,value", [("time_s", 40.0), ("frequency_hz", float("inf")), ("weight", -1)])
def test_invalid_ridge_samples_rejected(field, value):
    event = example("detected-event")
    event["ridge"][0][field] = value
    with pytest.raises(ValueError):
        validate_event(event)


def test_recording_metadata_labels_decoded_samples_and_source_hash():
    metadata = {"source_sha256": "a" * 64, "duration_s": 60, "sample_rate_hz": 4000,
                "channels": 1, "source_format": "mp3"}
    assert validate_recording(metadata) == metadata
    for change in ({"source_sha256": "missing"}, {"duration_s": 0}, {"channels": True}):
        with pytest.raises(ValueError):
            validate_recording(dict(metadata, **change))


def test_uncalibrated_radius_is_not_a_probability():
    candidate = example("job-result")["candidates"][0]
    candidate["uncertainty"]["coverage_probability"] = 0.95
    with pytest.raises(ValueError, match="Uncalibrated"):
        validate_candidate(candidate)
    candidate["uncertainty"]["kind"] = "calibrated"
    with pytest.raises(ValueError, match="calibration_reference"):
        validate_candidate(candidate)
    candidate["uncertainty"]["calibration_reference"] = "evaluation/heldout-report.json"
    validate_candidate(candidate)


def test_job_decisions_require_support_or_explanations():
    result = {"schema_version": 1, "job_id": "job", "status": "succeeded"}
    with pytest.raises(ValueError, match="requires a candidate"):
        validate_result(result)
    for status in ("inconclusive", "failed", "needs_input"):
        result["status"] = status
        with pytest.raises(ValueError):
            validate_result(result)
    result = example("job-needs-input")
    del result["required_fields"]
    with pytest.raises(ValueError, match="required_fields"):
        validate_result(result)


def test_ranked_candidates_must_be_comparable_and_reference_real_events():
    result = example("job-result")
    result["candidates"][0]["event_ids"] = ["absent-event"]
    with pytest.raises(ValueError, match="absent event"):
        validate_result(result)
    result = example("job-result")
    result["candidates"].append(deepcopy(result["candidates"][0]))
    result["candidates"][1]["score_kind"] = "unrelated_score"
    with pytest.raises(ValueError, match="comparable"):
        validate_result(result)
    result["candidates"][1]["score_kind"] = result["candidates"][0]["score_kind"]
    result["candidates"][1]["score"] = 100
    with pytest.raises(ValueError, match="descending"):
        validate_result(result)


def test_coverage_distinguishes_finished_search_from_available_data():
    result = example("job-result")
    result["coverage"] = {"search_complete": False, "data_status": "available",
                          "limitations": ["Only one tile searched; ADS-B capture can miss aircraft."]}
    assert validate_result(result)["coverage"]["search_complete"] is False
    result["coverage"]["search_complete"] = "yes"
    with pytest.raises(ValueError, match="Coverage"):
        validate_result(result)


@pytest.mark.parametrize("path", ["../other-job/file.json", "/etc/passwd", "C:\\private\\file", "nested/../../file"])
def test_artifact_paths_cannot_leave_job_directory(path):
    result = example("job-result")
    result["artifacts"]["report"] = path
    with pytest.raises(ValueError, match="relative"):
        validate_result(result)
