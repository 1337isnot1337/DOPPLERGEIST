"""Analytic and independent spline-oracle controls for the diagnostic audit."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.interpolate import CubicHermiteSpline

spec = importlib.util.spec_from_file_location("motion_audit", Path(__file__).parents[1] / "scripts/audit_trajectory_motion.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_constant_vector_velocity_and_stationary_segment():
    velocity = np.array([30., -40., 12.])
    peak = audit.segment_peak(7., np.zeros(3), 7*velocity, velocity, velocity)
    assert peak["speed_mps"] == pytest.approx(np.linalg.norm(velocity))
    assert audit.segment_peak(7., np.zeros(3), np.zeros(3), np.zeros(3), np.zeros(3))["speed_mps"] == 0


def test_zero_measured_knot_speeds_do_not_bound_interior_motion():
    peak = audit.segment_peak(2., [0, 0, 0], [1000, 0, 0], [0, 0, 0], [0, 0, 0])
    assert peak["endpoint_speeds_mps"] == [0, 0]
    assert peak["mean_displacement_speed_mps"] == 500
    assert peak["fraction"] == pytest.approx(.5)
    assert peak["speed_mps"] == pytest.approx(750)


def test_noncollinear_interior_peak_with_independent_closed_form():
    # v(u)=[4u(1-u),0.6,0]; its integral is [2/3,0.6,0].
    peak = audit.segment_peak(1., [0, 0, 0], [2/3, .6, 0], [0, .6, 0], [0, .6, 0])
    assert peak["fraction"] == pytest.approx(.5)
    assert peak["speed_mps"] == pytest.approx(np.sqrt(1+.6**2))


def test_stationary_point_enumeration_covers_independent_spline_samples():
    rng = np.random.default_rng(640031)
    for _ in range(30):
        dt = rng.uniform(.1, 30)
        p0, displacement, v0, v1 = rng.normal(size=(4, 3))*100
        p1 = p0+displacement
        peak = audit.segment_peak(dt, p0, p1, v0, v1)
        spline = CubicHermiteSpline([0, dt], [p0, p1], [v0, v1])
        sampled = np.linalg.norm(spline.derivative()(np.linspace(0, dt, 8193)), axis=1).max()
        assert peak["speed_mps"] >= sampled-1e-8
        assert peak["speed_mps"]-sampled < 1e-4*max(1, sampled)
        actual = np.linalg.norm(spline.derivative()(peak["fraction"]*dt))
        assert peak["speed_mps"] == pytest.approx(actual, rel=1e-10)


def test_audit_keeps_measured_zeros_and_does_not_bridge_a_gap():
    frame = pd.DataFrame({"flight_id": ["abcdef"]*6, "time_s": [0., 1., 2., 100., 101., 102.],
        "lat": [40.]*6, "lon": [-100., -99.9, -99.8, -95., -94.9, -94.8], "alt_m": [1000.]*6,
        "east_mps": [0.]*6, "north_mps": [0.]*6, "up_mps": [0.]*6,
        "typecode": ["C172"]*6, "altitude_basis": ["ellipsoidal"]*6})
    report = audit.audit_frame(frame, 343)
    assert len(report["segments"]) == 2
    assert all(row["max_knot_speed_mps"] == 0 for row in report["segments"])
    assert sum(row["unsupported_intervals"] for row in report["segments"]) == 4
    assert all(p["end_s"]-p["start_s"] == 1 for row in report["segments"] for p in row["intervals"])
    assert all(not any(row["velocity_inferred_components"].values()) for row in report["segments"])
    fresh = frame.copy()
    fresh.loc[0, "up_mps"] = np.nan
    compared = audit.compare_observations(frame, fresh)
    assert compared["max_ecef_observation_difference_m"] == 0
    assert compared["velocity_components"]["up_mps"]["canonical_zero_fresh_missing"] == 1


def test_clipping_before_normalization_can_remove_height_reference_observations():
    from aircraft_geoloc.tracks import adsblol_frame
    raw = {"icao": "abcdef", "timestamp": 1000., "trace": [
        [i, 40., -100., 1000., None, None, 0, 0, {}, 0, 1450. if i == 0 else None, 0]
        for i in range(3)]}
    full = adsblol_frame(raw)
    window = full[full.time_s >= 1001]
    clipped = adsblol_frame(dict(raw, trace=raw["trace"][1:]))
    comparison = audit.compare_observations(clipped, window)
    assert comparison["paired_times"] == 2
    assert comparison["height_delta_fresh_minus_canonical_m"] == pytest.approx([137.16, 137.16])
    assert comparison["altitude_basis_pairs"] == [{"canonical": "barometric", "fresh": "ellipsoidal_interpolated", "rows": 2}]


@pytest.mark.parametrize("duration", [0., -1., np.inf])
def test_invalid_duration_is_explicit(duration):
    with pytest.raises(ValueError, match="duration"):
        audit.segment_peak(duration, *([np.zeros(3)]*4))
