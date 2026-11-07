"""Automatic orchestration checks for explicit review exclusions.

These use a fake recording and discoverer so they exercise orchestration, not
detection accuracy or synthetic field data.
"""
import json

from dopplergeist import automatic


def event(event_id, group_id, start_s, end_s):
    return {
        "event_id": event_id, "harmonic_group_id": group_id,
        "start_s": start_s, "end_s": end_s, "band_hz": [100.0, 200.0],
        "ridge": [
            {"time_s": start_s, "frequency_hz": 100.0, "weight": 3.0},
            {"time_s": (start_s + end_s) / 2, "frequency_hz": 150.0, "weight": 3.5},
            {"time_s": end_s, "frequency_hz": 200.0, "weight": 3.0},
        ],
        "quality": {"median_contrast": 3.0},
    }


class FakeRecording:
    time_status = "needs_input"
    source_path = None
    metadata = {
        "source_sha256": "0" * 64, "duration_s": 40.0, "sample_rate_hz": 4000,
        "channels": 1, "source_format": "wav",
    }


def request(tmp_path, **fields):
    source = tmp_path / "source.wav"
    source.write_bytes(b"not decoded in this orchestration check")
    return {"schema_version": 1, "audio_path": str(source), **fields}


def run(tmp_path, monkeypatch, request_value, *, time_status="needs_input"):
    recording = FakeRecording()
    recording.time_status = time_status
    monkeypatch.setattr("dopplergeist.intake.intake_recording", lambda *args, **kwargs: recording)
    monkeypatch.setattr("dopplergeist.discovery.discover_events",
                        lambda *args, **kwargs: [event("event-0001", "group-a", 0.0, 10.0),
                                                 event("event-0002", "group-b", 20.0, 30.0)])
    monkeypatch.setattr(automatic, "_save_audio_checkpoint", lambda *args, **kwargs: None)
    output = tmp_path / "job"
    value = automatic.analyze(request_value, output)
    return value, output


def test_exclusions_filter_the_searched_events_and_record_user_assistance(tmp_path, monkeypatch):
    value, output = run(tmp_path, monkeypatch, request(
        tmp_path, excluded_event_ids=["event-0002"], review_source_job_id="a" * 32))
    assert value["status"] == "needs_input"
    assert [item["event_id"] for item in value["events"]] == ["event-0001"]
    assert value["review"] == {
        "user_assisted": True, "excluded_event_ids": ["event-0002"], "source_job_id": "a" * 32,
    }
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["event_selection"] == "automatic_whole_recording_with_user_review_exclusions"
    assert provenance["excluded_event_ids"] == ["event-0002"]
    assert provenance["discovered_ridges"] == 2
    assert provenance["searched_ridges"] == 1


def test_excluding_every_event_returns_inconclusive_without_searching(tmp_path, monkeypatch):
    value, _ = run(tmp_path, monkeypatch, request(
        tmp_path, excluded_event_ids=["event-0001", "event-0002"]), time_status="ok")
    assert value["status"] == "inconclusive"
    assert value["reason_code"] == "no_supported_events"
    assert "excluded by review" in value["message"]
    assert value["events"] == []
    assert value["review"]["excluded_event_ids"] == ["event-0001", "event-0002"]


def test_unknown_exclusion_is_an_explicit_failure(tmp_path, monkeypatch):
    value, _ = run(tmp_path, monkeypatch, request(tmp_path, excluded_event_ids=["event-9999"]))
    assert value["status"] == "failed"
    assert value["reason_code"] == "invalid_configuration"
    assert "event-9999" in value["message"]
    assert value["review"]["excluded_event_ids"] == ["event-9999"]


def test_no_review_fields_leave_the_automatic_result_unchanged(tmp_path, monkeypatch):
    value, _ = run(tmp_path, monkeypatch, request(tmp_path))
    assert value["status"] == "needs_input"
    assert [item["event_id"] for item in value["events"]] == ["event-0001", "event-0002"]
    assert "review" not in value
