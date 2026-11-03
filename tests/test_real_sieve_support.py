"""Real-data regression for rejection witnesses during acoustic screening.

The point is a previously declared diagnostic point, not a recording-location
label. The two passes come from the existing public ADS-B development index;
ridge records come from the original reference MP3's automatic discovery.
"""
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import _frequency_scale, fit_ridge, prepare_events
from dopplergeist.search import score_candidate


def test_incomplete_support_requires_a_valid_rejection_witness():
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
    observer = ecef(point.lat, point.lon, point.elev_m)
    first = fit_ridge(tracks[ids[0]], observer, measurements[0], case["clock"],
                      events[0]["f0_range_hz"], sigma_hz=_frequency_scale(events[0]))
    assert first["support_fraction"] == 1.0 and math.isfinite(first["score"])
    assert -first["score"] > 3 * _frequency_scale(events[0])
    try:
        second = fit_ridge(tracks[ids[1]], observer, measurements[1], case["clock"],
                           events[1]["f0_range_hz"], sigma_hz=_frequency_scale(events[1]))
    except AcousticSupportError:
        pass
    else:
        assert second["support_fraction"] != 1.0 or not math.isfinite(second["score"])
    if assessment["complete"]:
        assert assessment["rejected_trials"] == assessment["scheduled_trials"]
        assert assessment["unknown_trials"] == 0
    else:
        assert assessment["unknown_trials"] > 0
        assert assessment["bounded_unknown_rejections"] == assessment["unknown_trials"]
