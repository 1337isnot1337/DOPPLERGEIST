"""Regression for a real flyover near a track's final sample."""
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


def test_real_tiled_cpa_preserves_final_interval_passage():
    source = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_REFERENCE_ROOT to the real reference data checkout")
    root = Path(source)
    base = json.loads((root / "results/reference-local/ranked.json").read_text())[0]
    point = json.loads((root / "results/reference-faint-alltypes-local/ranked.json").read_text())[5153]
    assert point["point_id"] == 4904
    clock = base["recording_start_time_s"]
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    track = next(track for track in tracks if track.id == "a52fe1:1")
    observer = ecef(point["lat"], point["lon"], point["elev_m"])
    samples = np.unique(np.r_[np.arange(track.time[0], track.time[-1], 2), track.time[-1]])
    lo, hi = samples[-2:]
    minimum = minimize_scalar(lambda dt: np.sum((track.position(lo + dt) - observer) ** 2),
                              bounds=(0, hi - lo), method="bounded", options={"xatol": 0.0001})
    assert 0 < minimum.x < hi - lo and minimum.fun < 20000 ** 2
    points = pd.DataFrame([{key: point[key] for key in ("point_id", "lat", "lon", "elev_m", "x", "y")}])
    rows = cpa_table([track], points, 20000)
    matching = rows[(rows.emission_time >= lo) & (rows.emission_time <= hi)]
    assert len(matching) == 1
    assert matching.iloc[0].emission_time == pytest.approx(lo + minimum.x, abs=0.01)
    assert matching.iloc[0].distance_m == pytest.approx(minimum.fun ** 0.5, abs=0.1)
