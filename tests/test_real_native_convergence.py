"""Native convergence state stays exact across bounded allocation paths."""
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from dopplergeist import geometry, native_acoustic
from dopplergeist.tracks import _segment_velocity


pytestmark = pytest.mark.skipif(native_acoustic._native is None,
                                reason="optional acoustic extension is not built")


@pytest.fixture(scope="module")
def observed_query():
    root = Path(__file__).resolve().parents[1]
    for source in sorted((root / "research/trajectory-motion/frozen").glob("fresh-*.json")):
        frame = pd.DataFrame(json.loads(source.read_text())).sort_values("time_s")
        for _, rows in frame.groupby((frame.time_s.diff() > 30.).cumsum()):
            if len(rows) < 3:
                continue
            velocity, _ = _segment_velocity(rows)
            track = geometry.Track(str(rows.flight_id.iloc[0]), rows.time_s.to_numpy(),
                rows.lat.to_numpy(), rows.lon.to_numpy(), rows.alt_m.to_numpy(),
                str(rows.typecode.iloc[0]), velocity)
            try:
                track.validate_motion_support()
            except geometry.AcousticSupportError:
                continue
            observer = geometry.ecef(track.lat[0], track.lon[0], 0.)
            receive = track.time + np.linalg.norm(track.xyz-observer, axis=1)/343.
            return track, observer, receive
    pytest.fail("No supported archived aircraft observations")


@pytest.mark.parametrize("count", (1, 63, 64, 65, 257))
def test_observed_requests_preserve_bytes_at_state_allocation_boundary(observed_query, count):
    track, observer, receive = observed_query
    query = np.resize(receive, count)
    with patch.object(native_acoustic, "_native", None):
        expected = track.acoustic(query, observer)
    before = native_acoustic._native.successful_calls()
    actual = track.acoustic(query, observer)
    assert native_acoustic._native.successful_calls() == before + 1
    for left, right in zip(actual, expected):
        assert left.dtype == right.dtype and left.shape == right.shape
        assert left.tobytes() == right.tobytes()


def test_repeated_observed_requests_above_state_budget_stay_native(observed_query):
    track, observer, receive = observed_query
    with patch.object(native_acoustic, "_native", None):
        expected = track.acoustic(receive, observer)
    # Repeat identical recorded requests to cross the 2 MiB state budget.
    # Their global maximum correction and iteration count are unchanged.
    repetitions = (2 * 1024 * 1024 // np.dtype(np.uint16).itemsize) // len(receive) + 1
    query = np.tile(receive, (repetitions, 1))
    before = native_acoustic._native.successful_calls()
    actual = track.acoustic(query, observer)
    assert native_acoustic._native.successful_calls() == before + 1
    for left, right in zip(actual, expected):
        expected_bits = np.broadcast_to(right.view(np.uint64), query.shape)
        np.testing.assert_array_equal(left.view(np.uint64), expected_bits)
