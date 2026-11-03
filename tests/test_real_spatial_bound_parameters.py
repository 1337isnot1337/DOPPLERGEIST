"""Distance-sieve parameter and support checks on archived ADS-B segments.

Receiver controls are recorded aircraft positions or an existing research
candidate. No trajectory, recording, or location truth is generated here.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import _frame_track
from dopplergeist.geometry import AcousticSupportError, ecef


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def recorded_tracks():
    tracks = []
    for source in sorted((ROOT / "research/trajectory-motion/frozen").glob("fresh-*.json")):
        frame = pd.DataFrame(json.loads(source.read_text())).sort_values("time_s")
        for number, (_, segment) in enumerate(frame.groupby((frame.time_s.diff() > 30.).cumsum())):
            if len(segment) >= 3:
                tracks.append(_frame_track(f"{source.stem}:{number}", segment))
    assert tracks, "Archived aircraft observations are required"
    return tracks


@pytest.mark.parametrize("c", (0., -1., -np.inf))
def test_nonpositive_sound_speed_preserves_unsupported_error(recorded_tracks, c):
    for track in recorded_tracks:
        observer = track.xyz[len(track.time) // 2:len(track.time) // 2 + 1]
        with pytest.raises(AcousticSupportError) as expected:
            track.validate_motion_support(c)
        with pytest.raises(AcousticSupportError) as actual:
            track.outside_observer_radius(observer, 20000., c)
        assert vars(actual.value) == vars(expected.value)


@pytest.mark.parametrize("c", (np.nan, np.inf))
def test_nonfinite_sound_speed_does_not_prove_distance(recorded_tracks, c):
    candidate = json.loads((ROOT / "tests/data/real-search-workloads.json").read_text())["cases"]["previous-fit"]["point"]
    observer = ecef(candidate["lat"], candidate["lon"], candidate["elev_m"]).reshape(1, 3)
    for track in recorded_tracks:
        assert not track.outside_observer_radius(observer, 20000., c)


@pytest.mark.parametrize("c", (338., 343., 348.))
def test_recorded_positions_remain_inside_supported_bound(recorded_tracks, c):
    supported = unsupported = 0
    for track in recorded_tracks:
        observers = track.xyz[[0, len(track.time) // 2, -1]]
        try:
            track.validate_motion_support(c)
        except AcousticSupportError as expected:
            unsupported += 1
            with pytest.raises(AcousticSupportError) as actual:
                track.outside_observer_radius(observers, 0., c)
            assert vars(actual.value) == vars(expected)
        else:
            supported += 1
            assert not track.outside_observer_radius(observers, 0., c)
    assert supported and unsupported


def test_distant_unsupported_recorded_tracks_keep_hull_exclusion(recorded_tracks):
    candidate = json.loads((ROOT / "tests/data/real-search-workloads.json").read_text())["cases"]["previous-fit"]["point"]
    observer = ecef(candidate["lat"], candidate["lon"], candidate["elev_m"]).reshape(1, 3)
    excluded = 0
    for track in recorded_tracks:
        try:
            track.validate_motion_support()
        except AcousticSupportError:
            try:
                excluded += track.outside_observer_radius(observer, 20000.)
            except AcousticSupportError:
                pass
    assert excluded > 0
