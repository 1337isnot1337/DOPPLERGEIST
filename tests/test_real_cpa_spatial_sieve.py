"""Optional end-to-end CPA sieve comparison using recorded audio and real tracks."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.matching import prepare_events
from dopplergeist.search import cpa_table
from dopplergeist.tiled_search import SearchBudget, _score
from dopplergeist.tracks import load_tracks


def test_real_search_sieve_preserves_candidates_and_support(monkeypatch):
    root = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    discovery = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_DISCOVERY")
    if not root or not discovery:
        pytest.skip("set the real reference checkout and discovery JSON paths")
    root = Path(root)
    seed = json.loads((root / "results/reference-local/ranked.json").read_text())[0]
    events = json.loads(Path(discovery).read_text())["events"]
    events, measurements = prepare_events(events)
    clock = seed["recording_start_time_s"]
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    points = pd.DataFrame([{key: seed[key] for key in ("point_id", "lat", "lon", "elev_m", "x", "y")}])
    options = dict(budget=SearchBudget(top_k=5),
                   parameters={"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0},
                   filters={})

    # This is an existing regional development point, not an evaluation search
    # or a claim about the microphone's location. The baseline calls the same
    # CPA table and scoring code but disables this one spatial prefilter.
    original = Track.outside_observer_radius
    monkeypatch.setattr(Track, "outside_observer_radius", lambda *args, **kwargs: False)
    before = _score(points, tracks, events, measurements, **options)
    excluded = []

    def counting(track, *args, **kwargs):
        result = original(track, *args, **kwargs)
        if result:
            excluded.append(track.id)
        return result

    monkeypatch.setattr(Track, "outside_observer_radius", counting)
    after = _score(points, tracks, events, measurements, **options)
    assert excluded
    assert after[1]["cpa_rows"] > 0
    assert json.dumps(after, sort_keys=True, allow_nan=True) == json.dumps(before, sort_keys=True, allow_nan=True)


def test_real_multi_point_sieve_does_not_discard_cpas():
    source = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_REFERENCE_ROOT to the real reference checkout")
    root = Path(source)
    clock = json.loads((root / "results/reference-local/ranked.json").read_text())[0]["recording_start_time_s"]
    candidates = json.loads((root / "results/reference-faint-alltypes-local/ranked.json").read_text())[:64]
    points = pd.DataFrame(candidates).drop_duplicates("point_id")
    observers = ecef(points.lat.to_numpy(), points.lon.to_numpy(), points.elev_m.to_numpy())
    tracks, _ = load_tracks(root / "data/adsb/2026-09-08/reference-region.parquet",
                            time_range=(clock - 120, clock + 3720))
    excluded, retained_rows, unsupported = 0, 0, 0
    for track in tracks:
        try:
            outside = track.outside_observer_radius(observers, 20000)
        except AcousticSupportError:
            unsupported += 1
            with pytest.raises(AcousticSupportError):
                cpa_table([track], points, 20000)
            continue
        table = cpa_table([track], points, 20000)
        if outside:
            excluded += 1
            assert table.empty
        else:
            retained_rows += len(table)
    assert excluded > 0 and retained_rows > 0 and unsupported > 0
