"""Clock-neighborhood regression using complete observed ADS-B segments.

The receiver points are existing search-grid hypotheses, not microphone truth.
Only query windows change; aircraft positions/times are never generated or cut.
"""
from contextlib import nullcontext
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from dopplergeist.geometry import AcousticSupportError, Track, ecef
from dopplergeist.search import _PreparedCPATrack, _ordered_cpa_rows


CASES = json.loads((Path(__file__).parent / "data/real-cpa-clock-tracks.json").read_text())["cases"]


def prepare(case):
    d, point = case["track"], case["point"]
    track = Track(d["id"], *(np.asarray(d[k]) for k in ("time", "lat", "lon", "altitude")),
                  d["typecode"], None if d["velocity"] is None else np.asarray(d["velocity"]))
    track.altitude_basis = d["altitude_basis"]
    observer = np.asarray([ecef(point["lat"], point["lon"], point["elev_m"])])
    prepared = _PreparedCPATrack(track, case["c"], 2.,
                                 motion_observers=observer, max_distance=case["radius_m"])
    assert bool(prepared.motion_support) == case.get("interval_supported", False)
    return prepared, observer


def rows(prepared, observers, radius, bounds=None):
    return _ordered_cpa_rows(prepared.raw_rows(observers, np.array([0]), radius,
                                              receive_time_bounds=bounds), 2.)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["track"]["id"])
@pytest.mark.parametrize("python_edges", [False, True])
def test_real_clock_edges_keep_every_eligible_cpa_and_restore_full_cache(case, python_edges):
    # Both implementations must preserve their own full-path arithmetic/order.
    with patch("dopplergeist.search.try_cpa_edges", return_value=None) if python_edges else nullcontext():
        prepared, observer = prepare(case)
        full = rows(prepared, observer, case["radius_m"])
        assert full
        original_time, original_position = prepared.time.copy(), prepared.position.copy()
        original_step = prepared.max_step
        for cpa in full:
            arrival = cpa[3]
            for bounds in [(arrival, arrival),
                           (np.nextafter(arrival, -np.inf), np.nextafter(arrival, np.inf)),
                           (arrival - .1, arrival + .1)]:
                clipped = rows(prepared, observer, case["radius_m"], bounds)
                assert [r for r in full if bounds[0] <= r[3] <= bounds[1]] == [
                    r for r in clipped if bounds[0] <= r[3] <= bounds[1]]
                assert np.array_equal(prepared.time, original_time)
                assert np.array_equal(prepared.position, original_position)
                assert prepared.max_step == original_step
        assert rows(prepared, observer, case["radius_m"]) == full
        assert prepared.tree.n == len(prepared.time)
        # Windows entirely before/after the observations cannot invent a pass
        # by treating the cropped boundary as a trajectory endpoint.
        for bounds in [(prepared.time[0] - 1000, prepared.time[0] - 900),
                       (prepared.time[-1] + 900, prepared.time[-1] + 1000)]:
            assert rows(prepared, observer, case["radius_m"], bounds) == []


@pytest.mark.parametrize("case", [c for c in CASES if "endpoint" in c], ids=lambda case: case["track"]["id"])
def test_real_true_trajectory_endpoints_survive_clock_clipping(case):
    prepared, observer = prepare(case)
    full = rows(prepared, observer, case["radius_m"])
    lo, hi = prepared.time[-2:] if case["endpoint"] == "final" else prepared.time[:2]
    edge = [r for r in full if lo < r[2] < hi]
    assert len(edge) == 1
    arrival = edge[0][3]
    clipped = rows(prepared, observer, case["radius_m"], (arrival, arrival))
    assert [r for r in clipped if r[3] == arrival] == edge


def test_real_clock_crop_keeps_interval_motion_proof_guards():
    case = next(case for case in CASES if case.get("interval_supported"))
    prepared, observer = prepare(case)
    with pytest.raises(AcousticSupportError):
        prepared.track.validate_motion_support(case["c"])
    # Even an irrelevant clock window cannot bypass the receiver/radius proof.
    outside_clock = (prepared.time[-1] + 900, prepared.time[-1] + 1000)
    with pytest.raises(AcousticSupportError):
        prepared.raw_rows(observer, np.array([0]), case["radius_m"] + 1,
                          receive_time_bounds=outside_clock)
