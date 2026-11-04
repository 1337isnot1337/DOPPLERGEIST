"""Keep a nonfinite whole-track distance from excluding a recorded flight."""
import os
from pathlib import Path

import numpy as np
import pytest

from dopplergeist.geometry import AcousticSupportError, Track


@pytest.fixture(scope="module")
def real_unsupported_track_and_observers():
    source = os.environ.get("DOPPLERGEIST_REAL_UNSUPPORTED_CPA_FIXTURE")
    if not source or not Path(source).is_file():
        pytest.skip("set DOPPLERGEIST_REAL_UNSUPPORTED_CPA_FIXTURE to a recorded ADS-B/receiver fixture")
    with np.load(source, allow_pickle=False) as data:
        case = 5
        index = int(data[f"case_{case}_track"])
        track = Track(f"recorded-{index}", *(data[f"track_{index}_{name}"].copy()
            for name in ("time", "lat", "lon", "altitude")),
            velocity=data[f"track_{index}_velocity"].copy())
        return track, data[f"case_{case}_observers"].copy()


def test_real_unsupported_track_does_not_pass_nonfinite_whole_track_distance(
    real_unsupported_track_and_observers, monkeypatch
):
    track, observers = real_unsupported_track_and_observers
    with pytest.raises(AcousticSupportError, match="non_subsonic_motion") as caught:
        track.validate_motion_support(333.3)
    support_error = caught.value
    with pytest.raises(AcousticSupportError, match="non_subsonic_motion"):
        track.outside_observer_radius(observers, 20_000.0, 333.3)

    # Reuse the real validator outcome and real track; inject only numeric
    # overflow in the proof distance calculation.
    def recorded_support_error(_sound_speed_mps):
        raise support_error

    monkeypatch.setattr(track, "validate_motion_support", recorded_support_error)
    original_norm = np.linalg.norm

    def overflow_distance(values, *args, **kwargs):
        array = np.asarray(values)
        if array.ndim == 2 and array.shape[1] == 3 and kwargs.get("axis") == 1:
            return np.full(array.shape[0], np.inf)
        return original_norm(values, *args, **kwargs)

    monkeypatch.setattr(np.linalg, "norm", overflow_distance)
    with pytest.raises(AcousticSupportError, match="non_subsonic_motion"):
        track.outside_observer_radius(observers, 20_000.0, 333.3)
