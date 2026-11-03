"""Physical model boundary controls independent of acoustic-fit success."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from aircraft_geoloc.geometry import AcousticSupportError, Track, ecef
from aircraft_geoloc.matching import RidgeTimes
from aircraft_geoloc.search import score_candidate
from aircraft_geoloc.search import cpa_table, cpa_table_dense


def side_view(displacement=1000):
    """Zero knot velocities hide a 1.5*displacement/2 interior peak."""
    observer = ecef(40, -100, 100)
    lat, lon = np.deg2rad([40, -100])
    east = np.array([-np.sin(lon), np.cos(lon), 0])
    north = np.array([-np.sin(lat)*np.cos(lon), -np.sin(lat)*np.sin(lon), np.cos(lat)])
    up = np.array([np.cos(lat)*np.cos(lon), np.cos(lat)*np.sin(lon), np.sin(lat)])
    x = np.array([-displacement/2-160, -displacement/2, displacement/2, displacement/2+160])
    positions = observer + x[:, None]*east + 2000*north + 1000*up
    longitude, latitude, height = Transformer.from_crs(4978, 4979, always_xy=True).transform(*positions.T)
    track = Track("side-view", [-2, 0, 2, 4], latitude, longitude, height,
                  velocity=np.array([80, 0, 0, 80])[:, None]*east)
    emitted = np.linspace(.1, 1.9, 37)
    u = emitted/2
    source_x = -displacement/2 + displacement*(3*u**2-2*u**3)
    speed = 3*displacement*u*(1-u)
    distance = np.sqrt(source_x**2+2000**2+1000**2)
    received = emitted + distance/343
    factor = 343/(343+source_x*speed/distance)
    return track, observer, emitted, received, factor


def test_side_view_cannot_certify_unphysical_interior_motion():
    track, observer, emitted, received, factor = side_view()
    assert np.linalg.norm(track.speed_vector(1)) == pytest.approx(750)
    # Arrival remains strictly monotone, so the old radial guard accepts it.
    assert np.all(np.diff(received) > 0)
    assert np.all(np.isfinite(factor))
    with pytest.raises(AcousticSupportError) as failure:
        track.acoustic(received, observer)
    assert failure.value.reason == "non_subsonic_motion"
    assert failure.value.emission_intervals_s == [[0., 2.]]


def test_unsupported_motion_is_unknown_even_when_ridge_matches_its_formula():
    track, _, _, received, factor = side_view()
    point = SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=100, x=0, y=0)
    candidate = {"passes": [{"flight_id": track.id, "receive_time": 7.5}], "event_indices": [0]}
    event = {"event_id": "automatic-proposal", "cpa_receive_s": 7.5,
             "f0_range_hz": [119, 121], "quality": {"source_drift_fraction": 0}}
    measurement = (RidgeTimes(received), 120*factor, np.ones_like(factor), {})
    result = score_candidate(candidate, point, {track.id: track}, [event], [measurement],
                             mode="robust_ridge", time_origin=0, time_sweep_s=0)
    assert result["score"] == -np.inf
    assert not result["scoring_assessment"]["complete"]
    assert result["scoring_assessment"]["unknown_trials"] > 0
    assert result["scoring_assessment"]["rejected_trials"] == 0


def test_subsonic_control_retains_original_emission_time_solution():
    track, observer, emitted, received, factor = side_view(400)
    actual, solved, _ = track.acoustic(received, observer)
    np.testing.assert_allclose(actual, factor, atol=1e-10)
    np.testing.assert_allclose(solved, emitted, atol=1e-9)


def test_invalid_remote_interval_does_not_erase_clean_emission_support():
    track, observer, _, _, _ = side_view()
    # Add a later stationary segment, well separated in emission/arrival time.
    xyz = np.vstack([track.xyz, track.xyz[-1], track.xyz[-1]])
    lon, lat, height = Transformer.from_crs(4978, 4979, always_xy=True).transform(*xyz.T)
    velocities = np.vstack([track.speed_vector(track.time), np.zeros((2, 3))])
    extended = Track("separated", [-2, 0, 2, 4, 30, 60], lat, lon, height, velocity=velocities)
    emitted = np.linspace(40, 50, 21)
    distance = np.linalg.norm(xyz[-1]-observer)
    factor, solved, _ = extended.acoustic(emitted+distance/343, observer)
    np.testing.assert_allclose(factor, 1, atol=1e-12)
    np.testing.assert_allclose(solved, emitted, atol=1e-9)


@pytest.mark.parametrize("table", [cpa_table, cpa_table_dense])
def test_actual_unsupported_track_reaches_cpa_typed_boundary(table):
    bad, _, _, _, _ = side_view()
    clean, _, _, _, _ = side_view(400)
    points = pd.DataFrame({"point_id": [0], "lat": [40], "lon": [-100], "elev_m": [100]})
    assert len(table([clean], points, 5000, step_s=.25)) == 1
    with pytest.raises(AcousticSupportError) as failure:
        table([bad], points, 5000, step_s=.25)
    assert failure.value.track_id == bad.id
    assert failure.value.emission_intervals_s == [[0., 2.]]
    assert failure.value.receive_intervals_s is None


def test_sound_speed_profile_reuses_extrema_but_rechecks_physical_boundary():
    track, observer, _, received, _ = side_view(400)
    track.acoustic(received, observer)
    with pytest.raises(AcousticSupportError, match="non_subsonic_motion"):
        track.validate_motion_support(c=290)
    track.validate_motion_support(c=343)


def test_conservative_arrival_box_contains_all_unsupported_interval_arrivals():
    track, observer, _, received, _ = side_view()
    with pytest.raises(AcousticSupportError) as failure:
        track.acoustic(received, observer)
    emitted = np.linspace(0, 2, 1001)
    actual = emitted+np.linalg.norm(track.position(emitted)-observer, axis=1)/343
    lo, hi = failure.value.receive_intervals_s[0]
    assert lo <= actual.min() <= actual.max() <= hi


def test_continuous_speed_extrema_cover_independent_dense_spline_oracle():
    rng = np.random.default_rng(640311)
    inverse = Transformer.from_crs(4978, 4979, always_xy=True)
    observer = ecef(40, -100, 100)
    for _ in range(25):
        time = np.array([0., rng.uniform(.2, 5), rng.uniform(6, 10)])
        positions = observer+rng.normal(size=(3, 3))*1000
        velocities = rng.normal(size=(3, 3))*150
        lon, lat, height = inverse.transform(*positions.T)
        track = Track("oracle", time, lat, lon, height, velocity=velocities)
        track._unsupported_motion_intervals(c=1e-6)
        for i in range(2):
            sample = np.linspace(time[i], time[i+1], 8193)
            peak = np.linalg.norm(track.speed_vector(sample), axis=1).max()
            assert track._speed_peak[i] >= peak-1e-7
            assert track._speed_peak[i]-peak <= 1e-5*max(1, peak)
