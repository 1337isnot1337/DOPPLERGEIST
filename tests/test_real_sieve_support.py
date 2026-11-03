"""Check screening witnesses and unknown support on real multi-event fits.

Set DOPPLERGEIST_REAL_CPA_FIXTURE to the documented real reference-CPA JSON;
its real_index field must point to the corresponding archived flight index.
"""
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import AcousticSupportError, ecef
from dopplergeist.matching import _frequency_scale, association_candidates, fit_ridge, prepare_events
from dopplergeist.search import score_candidate


def test_real_screening_has_supported_rejection_witnesses():
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
    observer = ecef(point.lat, point.lon, point.elev_m)
    # These observed combinations contain both incompatible acoustic fits and
    # incomplete support in different events. A complete rejection is safe
    # only if each clock has another fully supported incompatible event.
    for candidate_index in (1874, 5120):
        candidate = candidates[candidate_index]
        result = score_candidate(candidate, point, tracks, events, measurements, mode="robust_ridge")
        assessment = result["scoring_assessment"]
        assert not math.isfinite(result["score"])
        assert assessment["evaluated_trials"] == 0
        selected_events = [events[i] for i in candidate["event_indices"]]
        selected_measurements = [measurements[i] for i in candidate["event_indices"]]
        selected_tracks = [tracks[p["flight_id"]] for p in candidate["passes"]]
        anchor = candidate["passes"][0]["receive_time"] - selected_events[0]["cpa_receive_s"]
        low, high = candidate["recording_start_bounds_s"]
        low, high = low - 5.0, high + 5.0
        shifts = np.linspace(low-anchor, high-anchor, max(1, int(np.ceil((high-low)/0.5)))+1)
        assert len(shifts) == assessment["scheduled_trials"]
        for shift in shifts:
            witnesses = []
            for track, event, measurement in zip(selected_tracks, selected_events, selected_measurements):
                scale = _frequency_scale(event)
                try:
                    fit = fit_ridge(track, observer, measurement, anchor + shift, event["f0_range_hz"],
                                    343.0, scale, event.get("quality", {}).get("source_drift_fraction", 0.02))
                except AcousticSupportError:
                    continue
                witnesses.append(fit.get("support_fraction") == 1.0 and math.isfinite(fit["score"])
                                 and -fit["score"] > 3 * scale)
            assert any(witnesses), f"No supported rejection witness for candidate {candidate_index} at {shift}"

    # A retained finite hypothesis with genuinely unknown trials must not lose
    # its missing-support accounting just because other trials can be screened.
    result = score_candidate(candidates[3101], point, tracks, events, measurements, mode="robust_ridge")
    assert result["score"] == pytest.approx(1.1929979825148687)
    assert result["scoring_assessment"]["unknown_trials"] > 0
    assert result["scoring_assessment"]["complete"] is False
