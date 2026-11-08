"""Encoded audio through the real job process, intake and automatic discovery."""
import hashlib
import json
import threading
import urllib.request
import subprocess

import numpy as np
import pytest
import soundfile as sf

from dopplergeist.jobs import JobManager
from dopplergeist.service import JobServer


def encoded_mp3(tmp_path, *, moving=False):
    pytest.importorskip("dopplergeist.intake")
    pytest.importorskip("dopplergeist.discovery")
    sr = 8000
    t = np.arange(sr * 40) / sr
    frequency = 220 - t if moving else np.full_like(t, 200)
    # Deterministic acoustic control, not aircraft/location truth.
    wave = .3*np.sin(2*np.pi*np.cumsum(frequency)/sr) + np.random.default_rng(44).normal(0, .002, len(t))
    source = tmp_path / "control.wav"
    sf.write(source, wave, sr)
    target = tmp_path / "control.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-codec:a", "libmp3lame", str(target)], check=True)
    return target.read_bytes()


def submit_and_wait(tmp_path, payload, *, time_window=None, config=None):
    manager = JobManager(tmp_path / "jobs", config)
    server = JobServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = {"schema_version": 1}
        if time_window:
            request["time_window"] = time_window
        upload = urllib.request.Request(base + "/api/jobs", payload,
                    headers={"Content-Type": "application/octet-stream", "X-Dopplergeist-Request": json.dumps(request)})
        with urllib.request.urlopen(upload, timeout=10) as response:
            assert response.status == 202
            queued = json.load(response)
        final = manager.wait(queued["job_id"])
        directory = manager.directory(queued["job_id"])
        with urllib.request.urlopen(base + f"/api/jobs/{queued['job_id']}") as response:
            shown = json.load(response)
        display_only = {"progress_stale", "progress_age_seconds", "elapsed_seconds"}
        assert {key: value for key, value in shown.items() if key not in display_only} == final
        with urllib.request.urlopen(base + f"/api/jobs/{queued['job_id']}/artifacts/input.mp3") as response:
            assert response.read() == payload
        return final, directory
    finally:
        server.shutdown()
        server.server_close()
        manager.close()
        thread.join()


WINDOW = {"start_utc": "2026-09-08T20:00:00Z", "end_utc": "2026-09-08T20:01:00Z", "source": "user"}


def test_real_mp3_without_time_requests_clock_and_preserves_hash(tmp_path):
    payload = encoded_mp3(tmp_path)
    final, directory = submit_and_wait(tmp_path, payload)
    assert final["status"] == "needs_input", final
    assert final["reason_code"] == "recording_time_required"
    assert final["required_fields"] == ["time_window"]
    assert final["recording"]["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (directory / "input.mp3").read_bytes() == payload
    assert (directory / final["artifacts"]["provenance"]).is_file()


def test_stationary_mp3_returns_no_events_without_search(tmp_path):
    payload = encoded_mp3(tmp_path)
    final, directory = submit_and_wait(tmp_path, payload, time_window=WINDOW)
    assert final["status"] == "inconclusive" and final["reason_code"] == "no_supported_events", final
    assert not final["events"]
    assert not (directory / "search").exists()


@pytest.mark.parametrize("discovery", [None, {"chunk_s": 24., "overlap_s": 16.}])
def test_moving_tone_mp3_discovers_events_then_reports_missing_data(tmp_path, discovery):
    pytest.importorskip("dopplergeist.data_access")
    pytest.importorskip("dopplergeist.matching")
    pytest.importorskip("dopplergeist.tiled_search")
    payload = encoded_mp3(tmp_path, moving=True)
    config = {"discovery": discovery} if discovery is not None else {}
    final, directory = submit_and_wait(tmp_path, payload, time_window=WINDOW, config=config)
    assert final["status"] == "inconclusive" and final["reason_code"] == "data_unavailable", final
    assert len(final["events"]) >= 1
    assert list((directory / "discovery").glob("event-*.png"))
    media = json.loads((directory / "discovery/event-media.json").read_text())
    assert media["version"] == 6
    assert media["events"]
    assert any("audio" in entry and (directory / "discovery" / entry["audio"]["raw"]).is_file()
               for entry in media["events"].values())
    assert final["coverage"]["data_status"] == "unavailable"
    from dataclasses import asdict
    from dopplergeist.discovery import DiscoverySettings
    receipt = json.loads((directory/"discovery/discovery.json").read_text())
    assert receipt["settings"] == asdict(DiscoverySettings(**(discovery or {})))
    assert len(receipt["chunks"]) > 1 if discovery else len(receipt["chunks"]) == 1
    assert json.loads((directory/"operator.json").read_text()) == config


def test_corrupt_upload_returns_predictable_decode_failure(tmp_path):
    pytest.importorskip("dopplergeist.intake")
    pytest.importorskip("dopplergeist.discovery")
    final, directory = submit_and_wait(tmp_path, b"not encoded audio", time_window=WINDOW)
    assert final["status"] == "failed" and final["reason_code"] == "invalid_media", final
    assert (directory / "input.mp3").read_bytes() == b"not encoded audio"


def test_subset_association_preserves_original_event_identity(tmp_path):
    """A middle subset must never be relabelled as the first input events."""
    pytest.importorskip("dopplergeist.confidence")
    from dopplergeist.automatic import _decide
    from dopplergeist.jobs import read_json
    events = [{"event_id": f"event-{i}", "start_s": i*10., "end_s": i*10.+5, "band_hz": [100., 120.],
               "ridge": [{"time_s": i*10.+t, "frequency_hz": 115.-t} for t in (1., 2., 3.)]} for i in range(3)]
    search = {"status": "complete", "scoring_time_is_locked": True, "ranked": [
        {"event_indices": [1, 2], "unmatched_event_ids": ["event-0"], "flight_ids": ["second-flight", "third-flight"], "lat": 40., "lon": -100.,
         "score": -1., "recording_start_time_s": 1788897600., "event_diagnostics": [{"rmse_hz": .1}, {"rmse_hz": .2}]}]}
    state = {"recording": {"time_window": {"start_utc": "2026-09-21T14:13:20Z", "end_utc": "2026-09-21T14:14:20Z", "source": "user"}}, "coverage": {"search_complete": True, "data_status": "available", "limitations": []}}
    def finish(status, reason_code=None, message=None, **fields):
        return dict(status=status, reason_code=reason_code, message=message, **fields)
    final = _decide(search, events, events, [None]*3, [], None, state, tmp_path,
                    {"refine_finalists": 0}, finish, lambda: None)
    assert final["status"] == "inconclusive"
    assert final["candidates"][0]["event_ids"] == ["event-1", "event-2"]
    diagnostics = read_json(tmp_path / "refined-candidates.json")["matching_diagnostics"]
    assert "event-0" not in diagnostics
    assert diagnostics["unmatched_event_ids"] == ["event-0"]
    assert diagnostics["recording_start_window_s"][1] - diagnostics["recording_start_window_s"][0] == 60
    assert diagnostics["event-1"]["rmse_hz"] == .1
    assert diagnostics["event-2"]["rmse_hz"] == .2


def test_complete_tile_work_is_separate_from_partial_flight_coverage():
    from dopplergeist.automatic import _coverage
    coverage = _coverage({"search": {"coverage": "conus"}},
        {"status": "partial", "tiles_total": 819, "tiles_completed": 819,
         "tile_failures": [], "refinement_failure": None, "data_scope_complete": False}, {})
    assert coverage["search_complete"] is True
    assert coverage["data_status"] == "partial"
    assert "historical_flight_scope_or_audible_border_region" in coverage["missing_data"]


def test_acquisition_budget_counts_utc_archive_days_across_midnight(tmp_path):
    from types import SimpleNamespace
    from dopplergeist.automatic import MissingData, _search
    window = {"start_utc": "2026-09-08T23:59:00Z", "end_utc": "2026-09-08T23:59:00Z", "source": "user"}
    event = {"event_id": "event-1", "start_s": 0., "end_s": 10., "band_hz": [100., 120.],
             "ridge": [{"time_s": float(t), "frequency_hz": 115.-t} for t in range(10)]}
    recording = SimpleNamespace(metadata={"time_window": window, "duration_s": 61.})
    request = {"schema_version": 1, "audio_path": "unused", "time_window": window, "search": {"coverage": "conus"}}
    with pytest.raises(MissingData, match="acquisition budget"):
        _search(request, recording, [event], tmp_path, {"cache_root": str(tmp_path), "max_acquisition_days": 1}, lambda: None)
    assert not (tmp_path/"flights").exists()


def test_refinement_adapter_preserves_raw_residual_and_avoids_double_normalization():
    from dopplergeist.automatic import _comparable_refinement
    from dopplergeist.matching import association_score
    events = [{"quality": {"frequency_sigma_hz": 1.}}]
    raw = {"score": -.6, "event_scores": [-.6], "score_kind": "negative_robust_ridge_loss_hz"}
    normalized = association_score(raw, events)
    original = dict(normalized, event_indices=[0])
    assert _comparable_refinement(raw, original, events) == normalized
    assert _comparable_refinement(normalized, original, events)["residual_score"] == -.6
    assert _comparable_refinement(normalized, original, events)["score"] == normalized["score"]


@pytest.mark.parametrize("second", [{"lat": 41.}, {"recording_start_time_s": 1790000010.},
                                     {"elev_m": 180.}, {"mode_id": "separate-seed"}])
def test_refinement_preserves_same_association_model_modes(tmp_path, monkeypatch, second):
    from types import SimpleNamespace
    from dopplergeist import automatic, matching
    events = [{"event_id": f"event-{i}", "start_s": i*100., "end_s": i*100.+20., "band_hz": [90., 200.],
               "ridge": [{"time_s": i*100.+t, "frequency_hz": 140.-t} for t in (0., 10., 20.)]} for i in range(2)]
    fit = {"rmse_hz": .1, "support_fraction": 1., "outlier_fraction": 0., "drift_at_bound": False}
    seed = {"lat": 40., "lon": -100., "score": -1., "score_kind": "negative_robust_ridge_loss_hz",
            "recording_start_time_s": 1790000000., "flight_ids": ["a", "b"],
            "pass_emission_times_s": [1790000010., 1790000110.], "event_diagnostics": [dict(fit), dict(fit)]}
    raw = [seed, dict(seed, score=-2., **second)]
    seen = []
    def refine(candidate, *args, **kwargs):
        seen.append((candidate["lat"], candidate["lon"], candidate["recording_start_time_s"],
                     candidate.get("elev_m"), candidate.get("mode_id")))
        return dict(candidate, score=candidate["score"]+.1)
    monkeypatch.setattr(matching, "refine_candidate", refine)
    monkeypatch.setattr(matching, "profile_candidate", lambda candidate, *args, **kwargs: dict(candidate, sensitivity={"complete": False}))
    tracks = [SimpleNamespace(id=name, time=[0., 1.], altitude_basis=["ellipsoidal"]) for name in ("a", "b")]
    index = SimpleNamespace(query=lambda *args: tracks)
    search = {"ranked": raw, "status": "complete", "scoring_time_is_locked": True, "alternative_modes_exhaustively_assessed": True}
    state = {"recording": {"time_window": {"start_utc": "2026-09-21T14:13:20Z", "end_utc": "2026-09-21T14:14:20Z", "source": "user"}},
             "coverage": {"search_complete": True, "data_status": "available", "limitations": []}}
    def finish(status, reason_code=None, message=None, **fields):
        return dict(status=status, **fields)
    final = automatic._decide(search, events, events, [None]*2, [index], None, state, tmp_path,
                              {"refine_finalists": 5}, finish, lambda: None)
    assert set(seen) == {(row["lat"], row["lon"], row["recording_start_time_s"],
                          row.get("elev_m"), row.get("mode_id")) for row in raw}
    assert final["status"] == "inconclusive"
    diagnostics = json.loads((tmp_path/"refined-candidates.json").read_text())["matching_diagnostics"]
    assert diagnostics["retained_hypotheses"] == 2
    assert diagnostics["refined_hypotheses"] == 2


def test_an_explicit_event_cap_is_incomplete_work_not_missing_flight_data():
    from dopplergeist.automatic import _coverage
    coverage = _coverage({"search": {"coverage": "conus"}},
        {"status": "partial", "tiles_total": 2, "tiles_completed": 2, "tile_failures": [],
         "refinement_failure": None, "data_scope_complete": True, "all_event_groups_considered": False,
         "event_limit_reason": "Configured limit 3 omits proposed groups from this four-group recording."}, {})
    assert coverage["search_complete"] is False
    assert coverage["data_status"] == "available"
    assert any("limit 3" in message for message in coverage["limitations"])


@pytest.mark.parametrize("options", [None, {"min_frequency_hz": 400.}, {"chunk_s": "bad"},
                                      {"chunk_s": 24., "overlap_s": 24.}])
def test_invalid_operator_discovery_configuration_is_explicit(tmp_path, options):
    from dopplergeist.automatic import analyze
    source = tmp_path/"unused.mp3"
    source.write_bytes(b"configuration must fail before decode")
    final = analyze({"schema_version": 1, "audio_path": str(source)}, tmp_path/"output",
                    {"discovery": options})
    assert final["status"] == "failed"
    assert final["reason_code"] == "invalid_configuration"
    assert not (tmp_path/"output/intake").exists()


@pytest.mark.parametrize("flag,changes,complete,counts_known", [
    (True, {}, True, True),
    (False, {"unsupported_cpa_track_evaluations": 1}, False, True),
    (False, {"unclassified_score_candidates": 2, "unknown_trials": 3}, False, True),
    (True, {"unknown_trials": 1}, False, True),
    (True, {"unknown_trials": False}, False, False),
    (True, {"unknown_trials": None}, False, False),
    (None, {}, False, True),
    (True, {"unreported_trial_envelopes": 1}, False, True),
    (True, {"unreported_trial_envelopes": None}, False, False),
])
def test_model_support_work_is_explicit_in_product_coverage(flag, changes, complete, counts_known):
    from dopplergeist.automatic import _coverage
    support = {"unsupported_cpa_track_evaluations": 0, "unclassified_score_candidates": 0,
               "evaluated_trials": 4, "rejected_trials": 1, "unknown_trials": 0,
               "unreported_trial_envelopes": 0, "diagnostics_directory": "support", **changes}
    coverage = _coverage({"search": {"coverage": "conus"}},
        {"status": "complete", "tiles_total": 2, "tiles_completed": 2, "data_scope_complete": True,
         "model_support_complete": flag, "model_support": support}, {})
    assert coverage["search_complete"] is complete
    assert coverage["data_status"] == "available"
    assert any("Trajectory model" in item for item in coverage["limitations"]) is (not complete)
    if counts_known and not complete:
        assert f'unknown clock trials: {support["unknown_trials"]}' in ' '.join(coverage["limitations"])
        assert f'unreported trial envelopes: {support["unreported_trial_envelopes"]}' in ' '.join(coverage["limitations"])
    elif not complete:
        assert "unavailable or malformed" in ' '.join(coverage["limitations"])


@pytest.mark.parametrize("missing", ["counters", "flag"])
def test_missing_model_support_evidence_cannot_become_completed_work(missing):
    from dopplergeist.automatic import _coverage
    report = {"tiles_total": 1, "tiles_completed": 1, "data_scope_complete": True,
              "model_support_complete": True,
              "model_support": {"unsupported_cpa_track_evaluations": 0, "unclassified_score_candidates": 0,
                                "evaluated_trials": 4, "rejected_trials": 1, "unknown_trials": 0,
                                "unreported_trial_envelopes": 0}}
    report.pop("model_support" if missing == "counters" else "model_support_complete")
    coverage = _coverage({"search": {"coverage": "conus"}}, report, {})
    assert coverage["search_complete"] is False
    assert coverage["data_status"] == "available"
    assert "Trajectory model assessment is incomplete" in ' '.join(coverage["limitations"])
    if missing == "counters":
        assert "unavailable or malformed" in ' '.join(coverage["limitations"])
