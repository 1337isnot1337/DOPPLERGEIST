"""Compare shared-clock batching with unbatched physics on real observations."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import _cache_ridge_fits, association_candidates, prepare_events
from dopplergeist.search import score_candidate
import dopplergeist.matching as matching


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def test_real_batched_clock_scores_and_bounded_fallback(monkeypatch):
    fixture_path = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not fixture_path:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the saved real-audio/flight CPA diagnostic")
    fixture = json.loads(Path(fixture_path).read_text())
    events, measurements = prepare_events(fixture["events"])
    candidates, _ = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
    assert len(candidates) == 10549
    tracks = {t.id: t for t in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
    selected = [candidates[i] for i in (895, 1874, 2188, 3101, 5120, 10545)]

    @_cache_ridge_fits
    def evaluate():
        rows = [score_candidate(c, point, tracks, events, measurements, mode="robust_ridge") for c in selected]
        return json.dumps(rows, sort_keys=True, default=_json_default)

    batch = matching.batch_acoustic_trials
    actual = evaluate()
    with monkeypatch.context() as patch:
        patch.setattr(matching, "batch_acoustic_trials", lambda tracks, measurements, *args, **kwargs:
                      [None] * len(measurements))
        baseline = evaluate()
    assert actual == baseline
    with monkeypatch.context() as patch:
        patch.setattr(matching, "batch_acoustic_trials", lambda *args, **kwargs:
                      batch(*args, **kwargs, max_samples=1))
        fallback = evaluate()
    assert fallback == baseline

    # Exercise the exception fallback with an actual unsupported trajectory
    # interval and a measured ridge sample, not a manufactured track.
    bad = next(track for track in tracks.values() if len(track._unsupported_motion_intervals(343.0)))
    interval = int(bad._unsupported_motion_intervals(343.0)[0])
    observer = ecef(point.lat, point.lon, point.elev_m)
    arrival = bad.time[interval] + np.linalg.norm(bad.xyz[interval] - observer) / 343.0
    spec, ridge, weight, _ = measurements[0]
    measured = np.isfinite(spec.time) & np.isfinite(ridge) & (weight > 0)
    sample_times = spec.time[measured]
    start = arrival - sample_times[0]
    with pytest.raises(AcousticSupportError):
        bad.acoustic(start + sample_times, observer)
    assert batch([bad], [measurements[0]], observer, np.array([start, start + 1.0])) == [None]


def test_real_harmonic_group_uses_same_clock_and_fits(monkeypatch):
    fixture_path = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    discovery_path = os.environ.get("DOPPLERGEIST_REAL_HARMONIC_DISCOVERY")
    if not fixture_path or not discovery_path:
        pytest.skip("set the real CPA fixture and harmonic discovery paths")
    fixture = json.loads(Path(fixture_path).read_text())
    events, measurements = prepare_events(json.loads(Path(discovery_path).read_text())["events"])
    harmonic_index = next(i for i, event in enumerate(events) if len(event["event_ids"]) >= 3)
    candidates, _ = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
    candidate = next(c for c in candidates if harmonic_index in c["event_indices"])
    tracks = {t.id: t for t in FlightIndex(fixture["real_index"]).query(
        fixture["query_bounds"], fixture["query_time_s"])}
    point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
    batched = score_candidate(candidate, point, tracks, events, measurements, mode="robust_ridge")
    with monkeypatch.context() as patch:
        patch.setattr(matching, "batch_acoustic_trials", lambda tracks, measurements, *args, **kwargs:
                      [None] * len(measurements))
        baseline = score_candidate(candidate, point, tracks, events, measurements, mode="robust_ridge")
    assert json.dumps(batched, sort_keys=True, default=_json_default) == json.dumps(
        baseline, sort_keys=True, default=_json_default)
