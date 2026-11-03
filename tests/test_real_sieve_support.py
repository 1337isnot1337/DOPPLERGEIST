"""Real-data regression for support accounting during acoustic screening.

The point is a previously declared diagnostic point, not a recording-location
label. The two passes come from the existing public ADS-B development index;
ridge records come from the original reference MP3's automatic discovery.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.search import score_candidate


def test_bad_first_event_does_not_hide_missing_later_support():
    result_path = os.environ.get("DOPPLERGEIST_REAL_AUDIO_RESULT")
    index_path = os.environ.get("DOPPLERGEIST_REAL_FLIGHT_INDEX")
    if not result_path or not index_path:
        pytest.skip("set DOPPLERGEIST_REAL_AUDIO_RESULT and DOPPLERGEIST_REAL_FLIGHT_INDEX")
    case_path = Path(__file__).parent / "data/real-sieve-support-case.json"
    case = json.loads(case_path.read_text())
    result = json.loads(Path(result_path).read_text())
    all_events, all_measurements = prepare_events(result["events"])
    events = [all_events[i] for i in case["event_indices"]]
    measurements = [all_measurements[i] for i in case["event_indices"]]
    ids = [p["flight_id"] for p in case["candidate"]["passes"]]
    tracks = {t.id: t for t in FlightIndex(index_path).lookup(ids, max_samples=2000000)}
    assert set(tracks) == set(ids)
    point = SimpleNamespace(**case["point"], x=0.0, y=0.0)
    scored = score_candidate(case["candidate"], point, tracks, events, measurements,
                             mode="robust_ridge", time_origin=case["clock"], time_sweep_s=0)
    assessment = scored["scoring_assessment"]
    assert assessment["complete"] is False
    assert assessment["unknown_trials"] > 0
    assert assessment["bounded_unknown_rejections"] == assessment["unknown_trials"]
    assert "incomplete_ridge_or_trajectory_support" in assessment["reasons"]
