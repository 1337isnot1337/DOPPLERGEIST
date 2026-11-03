"""Annotation duration must use seconds across pandas datetime resolutions."""
import numpy as np
import pandas as pd
import pytest

from aircraft_geoloc.tracks import unix_time


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_annotation_intervals_have_the_same_seconds_at_each_resolution(unit):
    # Whole seconds remain representable at every tested resolution.
    times = pd.DatetimeIndex(["2026-05-17T20:06:48Z", "2026-05-17T20:06:49Z",
                              "2026-05-17T20:07:18Z"]).as_unit(unit)
    seconds = pd.Series(times).map(unix_time).to_numpy()
    np.testing.assert_array_equal(seconds - seconds[0], [0, 1, 30])


def test_real_annotation_milliseconds_survive_default_string_parsing():
    times = pd.Series(["2026-05-17T20:06:48.691Z", "2026-05-17T20:06:48.861Z",
                       "2026-05-17T20:07:47.059Z"])
    seconds = times.map(unix_time).to_numpy()
    np.testing.assert_allclose(seconds - seconds[0], [0, 0.170, 58.368], rtol=0, atol=5e-7)


def test_annotation_intervals_use_absolute_time_across_timezone_offsets():
    times = pd.Series(["2026-05-17T13:06:48.691-07:00", "2026-05-17T20:06:48.861Z"])
    seconds = times.map(unix_time).to_numpy()
    np.testing.assert_allclose(seconds - seconds[0], [0, 0.170], rtol=0, atol=5e-7)
