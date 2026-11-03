"""Optional regression using a real archived flight and regional search result."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize_scalar

from dopplergeist.geometry import ecef
from dopplergeist.search import cpa_table
from dopplergeist.tracks import load_tracks


def test_real_flight_cpa_inside_final_sample_interval():
    source = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_REFERENCE_ROOT to the real reference data checkout")
    root = Path(source)
    base = json.loads((root / "results/reference-local/ranked.json").read_text())[0]
    candidates = json.loads((root / "results/reference-faint-alltypes-local/ranked.json").read_text())
    point = candidates[5153]
    assert point["point_id"] == 4904
    clock = base["recording_start_time_s"]
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    track = next(track for track in tracks if track.id == "a52fe1:1")
    observer = ecef(point["lat"], point["lon"], point["elev_m"])

    samples = np.unique(np.r_[np.arange(track.time[0], track.time[-1], 2), track.time[-1]])
    lo, hi = samples[-2:]
    def distance2(dt):
        return float(np.sum((track.position(lo + dt) - observer) ** 2))
    minimum = minimize_scalar(distance2, bounds=(0, hi - lo), method="bounded",
                              options={"xatol": 0.0001})
    # The final sample is smaller than its neighbour, but the actual minimum
    # is strictly inside that last interval and inside the 20 km search radius.
    assert distance2(hi - lo) < distance2(0)
    assert 0 < minimum.x < hi - lo
    assert minimum.fun < min(distance2(0), distance2(hi - lo))
    assert minimum.fun < 20000 ** 2
    matches = [event for event in track.closest_approaches(observer, max_distance=20000)
               if abs(event["emission_time"] - (lo + minimum.x)) < 0.01]
    assert len(matches) == 1
    assert matches[0]["distance_m"] == pytest.approx(minimum.fun ** 0.5, abs=0.01)


def test_real_national_cpa_table_keeps_the_final_interval_pass():
    source = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_REFERENCE_ROOT to the real reference data checkout")
    root = Path(source)
    seed = json.loads((root / "results/reference-local/ranked.json").read_text())[0]
    point = json.loads((root / "results/reference-faint-alltypes-local/ranked.json").read_text())[5153]
    assert point["point_id"] == 4904
    clock = seed["recording_start_time_s"]
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    track = next(track for track in tracks if track.id == "a52fe1:1")
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    reference = [event for event in track.closest_approaches(observer, max_distance=20000)
                 if 0 < track.time[-1] - event["emission_time"] < 1]
    assert len(reference) == 1
    points = pd.DataFrame([{key: point[key] for key in ("point_id", "lat", "lon", "elev_m")}])
    table = cpa_table([track], points, 20000)
    near_end = table[(track.time[-1] - table.emission_time > 0)
                     & (track.time[-1] - table.emission_time < 1)]
    assert len(near_end) == 1
    assert near_end.iloc[0].emission_time == pytest.approx(reference[0]["emission_time"], abs=0.001)
    assert near_end.iloc[0].distance_m == pytest.approx(reference[0]["distance_m"], abs=0.01)
