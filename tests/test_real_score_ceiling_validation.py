"""Validate bound records produced from actual audio and flight candidates."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.finite_search import bounded_assessment
from dopplergeist.matching import association_candidates, prepare_events
from dopplergeist.search import score_candidate


def test_real_score_ceiling_rejects_malformed_support_claims():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real reference diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    candidates, _ = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
    singleton = next(candidate for candidate in candidates if len(candidate["event_indices"]) == 1)
    point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
    row = score_candidate(singleton, point, {}, events, measurements, mode="robust_ridge", score_floor=2.0)
    assert bounded_assessment(row)

    # A no-fit ceiling cannot certify that unknown trials are rejections.
    malformed = copy.deepcopy(row)
    assessment = malformed["scoring_assessment"]
    assessment["bounded_unknown_rejections"] = assessment["bounded_unknown_trials"]
    assessment["unknown_score_upper_bound"] = None
    assert not bounded_assessment(malformed)

    # bool compares equal to one in Python but is not a numeric score ceiling.
    malformed = copy.deepcopy(row)
    malformed["scoring_assessment"]["unknown_score_upper_bound"] = True
    assert not bounded_assessment(malformed)


def test_real_singleton_retains_source_drift_parameter_errors():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real reference diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    candidates, _ = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
    singleton = next(candidate for candidate in candidates if len(candidate["event_indices"]) == 1)
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        [singleton["passes"][0]["flight_id"]])}
    point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
    index = singleton["event_indices"][0]
    for fraction in (-0.1, 0.2, float("nan")):
        configured = list(events)
        configured[index] = dict(events[index], quality=dict(events[index]["quality"],
                                                            source_drift_fraction=fraction))
        for floor in (None, 2.0):
            with pytest.raises(ValueError, match="drift fraction"):
                score_candidate(singleton, point, tracks, configured, measurements,
                                mode="robust_ridge", score_floor=floor)

