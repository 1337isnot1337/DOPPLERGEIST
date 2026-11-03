"""Bound certificates must describe how actual observations were screened."""
import copy
import importlib.util
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


def test_real_bound_methods_and_independent_verifier():
    source = os.environ.get("DOPPLERGEIST_REAL_CPA_FIXTURE")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_CPA_FIXTURE to the real reference diagnostic")
    fixture = json.loads(Path(source).read_text())
    events, measurements = prepare_events(fixture["events"])
    candidates, _ = association_candidates(pd.DataFrame(fixture["cpa_rows"]), events, max_candidates=20000)
    point = SimpleNamespace(**fixture["point"], x=0.0, y=0.0)
    spec = importlib.util.spec_from_file_location("upload_verifier", Path(__file__).resolve().parents[1] / "scripts/verify_upload_http.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    singleton = next(c for c in candidates if len(c["event_indices"]) == 1)
    ceiling = score_candidate(singleton, point, {}, events, measurements, mode="robust_ridge", score_floor=2.0)
    detail = dict(ceiling, finite_best=False)
    assert bounded_assessment(ceiling)
    assert verifier.bounded_finite_clock_assessment(detail, len(events))

    candidate = candidates[287]
    tracks = {track.id: track for track in FlightIndex(fixture["real_index"]).lookup(
        [entry["flight_id"] for entry in candidate["passes"]])}
    row = score_candidate(candidate, point, tracks, events, measurements, mode="robust_ridge", score_floor=0.0)
    assessment = row["scoring_assessment"]
    assert assessment["acoustic_bound_rejected_trials"] > 0
    assert assessment["unknown_score_bound_method"] == "nonnegative_loss_validated_fits_and_acoustic_dual"
    assert bounded_assessment(row)
    assert verifier.bounded_finite_clock_assessment(dict(row, finite_best=False), len(events))

    for field, value in (("acoustic_bound_rejected_trials", True),
                         ("acoustic_bound_rejected_trials", 0),
                         ("acoustic_bound_rejected_trials", assessment["bounded_unknown_rejections"] + 1),
                         ("unknown_score_bound_method", "nonnegative_loss_and_validated_event_fits")):
        invalid = copy.deepcopy(row)
        invalid["scoring_assessment"][field] = value
        assert not bounded_assessment(invalid)
        assert not verifier.bounded_finite_clock_assessment(dict(invalid, finite_best=False), len(events))
