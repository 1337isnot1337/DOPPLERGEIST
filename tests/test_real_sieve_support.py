"""Preserve unknown physical support when screening real multi-event fits.

Set DOPPLERGEIST_REAL_CPA_FIXTURE to the documented real reference-CPA JSON;
its real_index field must point to the corresponding archived flight index.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.matching import association_candidates, prepare_events
from dopplergeist.search import score_candidate


def test_real_multi_event_support_gaps_remain_explicit():
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
    # These two observed candidate combinations contain both incompatible
    # acoustic fits and real out-of-support trials, in different events.
    for candidate_index in (1874, 5120):
        result = score_candidate(candidates[candidate_index], point, tracks, events,
                                 measurements, mode="robust_ridge")
        assessment = result["scoring_assessment"]
        assert assessment["unknown_trials"] > 0
        assert assessment["complete"] is False
