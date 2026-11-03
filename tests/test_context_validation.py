"""Independent spectral stimuli and rejection controls for frozen context."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from aircraft_geoloc.context_validation import ContextSettings, validate_context


class FrequencyOracle:
    """A frequency-provider test double; full propagation has separate tests.

    Its two models agree throughout the fitted core but disagree in the wings.
    Audio below is rendered directly by integrating an independently specified
    receiver-time chirp, without calling this predictor or the context scorer.
    """
    def __init__(self, center, wrong=False, support=None, fail_context=False):
        self.center, self.wrong, self.support, self.fail_context = center, wrong, support, fail_context

    def acoustic(self, t, observer, c):
        t = np.asarray(t, dtype=float)
        dt = t - self.center
        if self.fail_context and np.ptp(t) > 10:
            raise ValueError("context trajectory unsupported")
        frequency = 100 + 0.5 * dt
        if self.wrong:
            frequency += 0.8 * np.maximum(abs(dt) - 3, 0)
        factor, emission = frequency / 100, t - 3
        if self.support:
            valid = (t >= self.support[0]) & (t <= self.support[1])
            factor, emission = np.where(valid, factor, np.nan), np.where(valid, emission, np.nan)
        return factor, emission, np.full_like(t, 1029)


def stimulus(tmp_path, count=1):
    sr, duration = 4000, count * 40
    t = np.arange(sr * duration) / sr
    audio = np.random.default_rng(41307).normal(0, 0.035, len(t))
    events, measurements, tracks = [], [], {}
    for i in range(count):
        center = 20 + i * 40
        dt = t - center
        # Independent chirp phase derivative is 100 + 0.5*dt Hz.
        envelope = np.maximum(0, 1 - (dt / 19)**8)
        audio += 0.4 * envelope * np.sin(2 * np.pi * (100 * dt + 0.25 * dt**2))
        event = {"event_id": f"event-{i}", "start_s": center - 3, "end_s": center + 3,
                 "band_hz": [98.5, 101.5], "harmonic_group_id": f"group-{i}"}
        core_t = np.arange(center - 3, center + 3.01, 0.5)
        measurements.append((SimpleNamespace(time=core_t), 100 + 0.5 * (core_t - center),
                             np.ones_like(core_t), {}))
        events.append(event)
        tracks[f"good-{i}"] = FrequencyOracle(center)
        tracks[f"bad-{i}"] = FrequencyOracle(center, wrong=True)
    path = tmp_path / "recording.f32"
    audio.astype("<f4").tofile(path)
    recording = SimpleNamespace(samples_path=path, metadata={"sample_rate_hz": sr,
                                "duration_s": duration, "source_sha256": "a" * 64})
    return recording, events, measurements, tracks


def candidate(ids, **extra):
    return dict({"lat": 40.0, "lon": -100.0, "elev_m": 120.0,
                 "recording_start_time_s": 0.0, "flight_ids": ids,
                 "event_indices": list(range(len(ids))), "score": -0.1,
                 "score_kind": "negative_robust_ridge_loss_hz",
                 "event_diagnostics": [{"f0_hz": 100.0, "source_drift_hz_s": 0.0} for _ in ids]}, **extra)


def settings(**extra):
    return ContextSettings(expansion_s=12, bootstrap_samples=80, **extra)


def test_audio_wings_discriminate_without_refitting_or_mutating(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    rows = [candidate(["bad-0"]), candidate(["good-0"])]
    before = copy.deepcopy(rows)
    report = validate_context(recording, rows, tracks, events, measurements,
                              output_dir=tmp_path / "context", settings=settings())
    assert rows == before
    assert report["status"] == "compared"
    assert report["ranking"][0]["input_index"] == 1
    assert report["ranking"][0]["context_contrast_excess"] > report["ranking"][1]["context_contrast_excess"] + 0.5
    assert report["location_decision"] == "not_evaluated"
    arrays = np.load(tmp_path / "context/event-0001.npz")
    core = (arrays["time_s"] >= events[0]["start_s"] - 2) & (arrays["time_s"] <= events[0]["end_s"] + 2)
    assert not arrays["common_validation_mask"][core].any()
    assert arrays["common_validation_mask"].sum() == report["events"][0]["common_samples"]
    assert "confidence" not in report and "coverage_probability" not in report


def test_fourth_supported_event_is_used_and_partial_mode_stays_explicit(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path, count=4)
    rows = [candidate(["good-0", "good-1", "good-2", "bad-3"]),
            candidate(["good-0", "good-1", "good-2", "good-3"]),
            candidate(["good-0", "good-1"])]
    report = validate_context(recording, rows, tracks, events, measurements, settings=settings())
    assert len(report["events"]) == 4
    assert report["ranking"][0]["input_index"] == 1
    assert report["modes"][2]["status"] == "unsupported"
    assert "every supplied supported event" in report["modes"][2]["limitations"][0]
    assert not report["all_modes_compared"] and report["status"] == "inconclusive"
    for e in report["events"][:3]:
        assert e["scores"][0]["contrast_excess_mean"] == e["scores"][1]["contrast_excess_mean"]


def test_same_association_spatial_and_clock_modes_are_not_deduplicated(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    rows = [candidate(["good-0"]), candidate(["good-0"], lat=40.01),
            candidate(["good-0"], recording_start_time_s=2.0)]
    report = validate_context(recording, rows, tracks, events, measurements, settings=settings())
    assert report["candidate_mode_count"] == len(report["ranking"]) == 3
    assert len({r["input_candidate_sha256"] for r in report["modes"]}) == 3
    assert report["ranking"][0]["context_contrast_excess"] == report["ranking"][1]["context_contrast_excess"]
    assert report["ranking"][2]["input_index"] == 2


def test_missing_competitor_is_retained_and_cannot_become_a_complete_comparison(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    report = validate_context(recording, [candidate(["good-0"]), candidate(["missing"])],
                              tracks, events, measurements, settings=settings())
    assert len(report["modes"]) == 2
    assert report["modes"][1]["status"] == "unsupported"
    assert report["status"] == "inconclusive" and not report["all_modes_compared"]


def test_context_gaps_use_one_common_mask_and_reject_tiny_overlap(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    tracks["short"] = FrequencyOracle(20, support=(16.5, 23.5))
    report = validate_context(recording, [candidate(["good-0"]), candidate(["short"])],
                              tracks, events, measurements, settings=settings())
    assert report["status"] == "inconclusive" and not report["ranking"]
    assert report["events"][0]["reason"] == "insufficient_common_context"
    assert report["events"][0]["common_samples"] == 0


def test_partial_wings_are_compared_on_identical_bins(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    tracks["partial"] = FrequencyOracle(20, support=(8, 32))
    report = validate_context(recording, [candidate(["good-0"]), candidate(["partial"])],
                              tracks, events, measurements, settings=settings())
    evidence = report["events"][0]
    assert 0 < evidence["common_fraction"] < 1
    assert evidence["own_supported_samples"]["mode-0001"] > evidence["own_supported_samples"]["mode-0002"]
    assert evidence["common_samples"] == evidence["own_supported_samples"]["mode-0002"]
    assert evidence["scores"][0]["contrast_excess_mean"] == evidence["scores"][1]["contrast_excess_mean"]


def test_all_original_proposal_cores_are_excluded_including_unconfirmed(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    raw = events + [{"event_id": "unconfirmed", "start_s": 7, "end_s": 9}]
    validate_context(recording, [candidate(["good-0"])], tracks, events, measurements,
                     detected_events=raw, settings=settings(), output_dir=tmp_path / "context")
    arrays = np.load(tmp_path / "context/event-0001.npz")
    trained = (arrays["time_s"] >= 5) & (arrays["time_s"] <= 11)
    assert trained.any() and not arrays["common_validation_mask"][trained].any()


def test_frozen_drift_and_explicit_emission_anchor_predict_the_same_curve(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)

    class ConstantRange:
        def acoustic(self, t, observer, c):
            t = np.asarray(t)
            return np.ones_like(t), t - 3, np.full_like(t, 1029)

    tracks["constant-range"] = ConstantRange()
    rows = [candidate(["constant-range"]) for _ in range(3)]
    rows[0]["event_diagnostics"] = [{"f0_hz": 100.0, "source_drift_hz_s": 0.5}]
    # Change source-reference epoch and intercept together, leaving predictions
    # identical. Ignoring the explicit anchor would incorrectly alter this curve.
    rows[1]["event_diagnostics"] = [{"f0_hz": 99.5, "source_drift_hz_s": 0.5,
                                     "source_reference_emission_time_s": 16.0}]
    report = validate_context(recording, rows, tracks, events, measurements, settings=settings())
    assert abs(report["ranking"][0]["context_contrast_excess"] - report["ranking"][1]["context_contrast_excess"]) < 1e-8
    assert report["ranking"][2]["input_index"] == 2
    assert report["modes"][0]["frozen_parameters"][0]["reference_emission_time_s"] == 17.0
    assert report["modes"][1]["frozen_parameters"][0]["anchor_source"] == "candidate_diagnostic"


def test_trajectory_error_in_context_is_preserved_not_dropped(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    tracks["failure"] = FrequencyOracle(20, fail_context=True)
    report = validate_context(recording, [candidate(["good-0"]), candidate(["failure"])],
                              tracks, events, measurements, settings=settings())
    assert report["status"] == "inconclusive" and not report["ranking"]
    assert report["events"][0]["prediction_failures"]["mode-0002"] == "context trajectory unsupported"


def test_budget_does_not_silently_keep_only_one_mode(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path)
    report = validate_context(recording, [candidate(["good-0"]), candidate(["bad-0"])],
                              tracks, events, measurements, settings=settings(max_modes=1))
    assert len(report["modes"]) == 2 and not report["ranking"]
    assert all(m["limitations"] == ["mode_budget_exceeded"] for m in report["modes"])


def test_harmonics_must_be_prepared_as_one_group_and_outputs_preserved(tmp_path):
    recording, events, measurements, tracks = stimulus(tmp_path, count=2)
    events[1]["harmonic_group_id"] = events[0]["harmonic_group_id"]
    with pytest.raises(ValueError, match="harmonics/fragments count once"):
        validate_context(recording, [candidate(["good-0", "good-1"])], tracks, events,
                         measurements, settings=settings())
