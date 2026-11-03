"""Optional fixed-clock regression using actual audio discovery and ADS-B."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from dopplergeist.geometry import ecef
from dopplergeist.matching import association_score, prepare_events, score_ridges
from dopplergeist.tiled_search import SearchBudget, _score
from dopplergeist.tracks import load_tracks


def test_real_fixed_clock_is_scored_once_without_changing_fit():
    root = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    discovery = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_DISCOVERY")
    if not root or not discovery:
        pytest.skip("set the real reference checkout and discovery JSON paths")
    root = Path(root)
    seed = json.loads((root / "results/reference-local/ranked.json").read_text())[0]
    events, measurements = prepare_events(json.loads(Path(discovery).read_text())["events"])
    clock = seed["recording_start_time_s"]
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    points = pd.DataFrame([{key: seed[key] for key in ("point_id", "lat", "lon", "elev_m", "x", "y")}])
    ranked, counts = _score(points, tracks, events, measurements, SearchBudget(top_k=100),
                            {"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0}, {})
    assert ranked and counts["candidates"] > 1
    assert counts["evaluated_trials"] + counts["rejected_trials"] + counts["unknown_trials"] == counts["candidates"]
    best = ranked[0]
    assert best["scoring_assessment"]["scheduled_trials"] == 1
    lookup = {track.id: track for track in tracks}
    indices = best["event_indices"]
    selected = [events[i] for i in indices]
    direct = score_ridges([lookup[name] for name in best["flight_ids"]], selected,
                          [measurements[i] for i in indices],
                          ecef(seed["lat"], seed["lon"], seed["elev_m"]), clock)
    direct = association_score(direct, selected)
    assert best["recording_start_time_s"] == clock
    assert best["score"] == direct["score"]
    assert best["event_scores"] == direct["event_scores"]
