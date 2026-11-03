from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from aircraft_geoloc.geometry import Track, ecef, straight_doppler
from aircraft_geoloc.matching import RidgeTimes, fit_ridge, prepare_events, refine_candidate
from aircraft_geoloc.search import event_score, filter_event, pair_candidates, score_candidate


class Flyover:
    def __init__(self, center=30, support=None):
        self.center, self.support = center, support

    def acoustic(self, t, observer, c):
        t = np.asarray(t)
        factor = 1.1 - 0.25 * np.tanh((t - self.center) / 8)
        if self.support is not None:
            factor = np.where(t <= self.support, factor, np.nan)
        return factor, t - 5, np.ones_like(t) * 1700


def measurement(center=30, drift=0.0, noisy=False):
    t = np.arange(center - 25, center + 25, 0.5)
    factor = Flyover(center).acoustic(t, None, 343)[0]
    ridge = factor * (120 + drift * (t - (t[0] + t[-1]) / 2) / np.ptp(t))
    if noisy:
        ridge += np.random.default_rng(17).normal(0, 0.15, len(t))
        ridge[::11] += 18
    return RidgeTimes(t), ridge, np.ones(len(t)), {}


def test_robust_source_drift_and_outliers_preserve_wrong_track_penalty():
    measured = measurement(drift=1.8, noisy=True)
    correct = fit_ridge(Flyover(), None, measured, 0, [118, 122])
    wrong = fit_ridge(Flyover(38), None, measured, 0, [118, 122])
    legacy = event_score(Flyover(), None, *measured[:3], 0, [118, 122], "ridge")
    assert abs(correct["f0_hz"] - 120) < 0.2
    assert abs(correct["source_drift_hz"] - 1.8) < 0.5
    assert correct["score"] > legacy[0]
    assert correct["score"] > wrong["score"] + 1
    assert correct["outlier_fraction"] > 0.05
    assert correct["support_fraction"] == 1
    noise = list(measured)
    noise[1] = np.random.default_rng(3).uniform(90, 160, len(measured[1]))
    assert fit_ridge(Flyover(), None, noise, 0, [118, 122])["score"] < correct["score"] - 1


def test_drift_is_bounded_and_incomplete_support_cannot_win():
    measured = measurement(drift=18)
    fit = fit_ridge(Flyover(), None, measured, 0, [118, 122])
    assert fit["drift_at_bound"]
    assert abs(fit["source_drift_hz"]) <= fit["drift_bound_hz"]
    assert not np.isfinite(fit_ridge(Flyover(support=54), None, measured, 0, [118, 122])["score"])
    zero = list(measured)
    zero[2] = np.zeros(len(measured[1]))
    assert not np.isfinite(fit_ridge(Flyover(), None, zero, 0, [118, 122])["score"])


def test_robust_mode_locks_all_event_clocks_and_rejects_missing_passes():
    point = SimpleNamespace(point_id=0, lat=40, lon=-100, elev_m=0, x=0, y=0)
    events = [{"cpa_receive_s": t, "f0_range_hz": [119.9, 120.1]} for t in (30, 950)]
    candidate = {"passes": [{"flight_id": "a", "receive_time": 30}, {"flight_id": "b", "receive_time": 950}]}
    kwargs = dict(mode="robust_ridge", time_origin=0, time_sweep_s=10, time_step_s=1)
    good = score_candidate(candidate, point, {"a": Flyover(30), "b": Flyover(950)},
                           events, [measurement(30), measurement(950)], **kwargs)
    bad = score_candidate(candidate, point, {"a": Flyover(30), "b": Flyover(958)},
                          events, [measurement(30), measurement(950)], **kwargs)
    assert abs(good["score"]) < 1e-8
    assert bad["score"] < -2
    assert len(bad["event_diagnostics"]) == 2
    with pytest.raises(ValueError, match="exactly one"):
        score_candidate({"passes": candidate["passes"][:1]}, point, {}, events, [], **kwargs)


def detected(identity="a", harmonic=1):
    m = measurement()
    return {"event_id": identity, "start_s": 4, "end_s": 56, "band_hz": [80 * harmonic, 170 * harmonic],
            "harmonic_group_id": "group", "cpa_receive_s": 30,
            "speed_range_mps": [70, 90], "slant_range_m": [800, 1400],
            "ridge": [{"time_s": float(t), "frequency_hz": float(f * harmonic), "weight": 2}
                      for t, f in zip(m[0].time, m[1])]}


def test_adapter_retains_jet_with_misleading_straight_geometry_and_merges_harmonics():
    primary = dict(detected(), quality={"frequency_uncertainty_hz": 1.5})
    events, measurements = prepare_events([primary, detected("harmonic", 2)])
    table = pd.DataFrame([dict(point_id=0, flight_id="jet", receive_time=42, emission_time=28,
                               speed_mps=155, distance_m=4900)])
    assert len(events) == 1
    assert len(measurements[0][1]) == 200
    assert len(filter_event(table, events[0], time_origin=0)) == 1
    assert events[0]["event_ids"] == ["a", "harmonic"]
    assert events[0]["quality"]["frequency_loss_scale_hz"] == 1.5
    assert events[0]["quality"]["frequency_uncertainty_hz"] == 1.5
    legacy_scale, _ = prepare_events([dict(detected(), quality={"frequency_sigma_hz": 0.2})])
    assert legacy_scale[0]["quality"]["frequency_loss_scale_hz"] == 1.0
    # Duplicating harmonic evidence changes neither the fit nor its normalization.
    single, sm = prepare_events([detected()])
    one = fit_ridge(Flyover(), None, sm[0], 0, single[0]["f0_range_hz"])
    two = fit_ridge(Flyover(), None, measurements[0], 0, events[0]["f0_range_hz"])
    assert abs(one["score"] - two["score"]) < 1e-8
    inconsistent = detected("bad", 2)
    for p in inconsistent["ridge"]:
        p["frequency_hz"] *= 0.75
    with pytest.raises(ValueError, match="integer"):
        prepare_events([detected(), inconsistent])


def test_uncertainty_requires_one_common_recording_start_interval():
    events = [dict(cpa_receive_s=t, speed_range_mps=[70, 90], slant_range_m=[800, 1400],
                   quality={"cpa_tolerance_s": 1}) for t in (30, 130, 230)]
    rows = [dict(point_id=0, flight_id=str(i), receive_time=t + delta, emission_time=t + delta - 5,
                 speed_mps=80, distance_m=1000) for i, (t, delta) in enumerate(zip((30, 130, 230), (100, 103, 97)))]
    assert pair_candidates(pd.DataFrame(rows), events, offset_tolerance_s=2)[0] == []
    rows[-1]["receive_time"] += 6
    candidates, _ = pair_candidates(pd.DataFrame(rows), events, offset_tolerance_s=2)
    assert len(candidates) == 1
    lower, upper = candidates[0]["recording_start_bounds_s"]
    assert lower <= upper


def physical_case():
    observer = ecef(40, -100, 100)
    epoch = 1_790_000_000.0
    inverse = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
    tracks, events, measurements = {}, [], []
    for identity, center, f0, velocity, cross in [
            ("a", 70, 120, [80, 0, 0], [0, 1600, 800]),
            ("b", 250, 160, [0, 80, 0], [1700, 0, 1000])]:
        t = np.arange(center - 120, center + 121, 1.0)
        xyz = observer + (t - center)[:, None] * np.array(velocity) + cross
        lon, lat, altitude = inverse.transform(*xyz.T)
        tracks[identity] = Track(identity, t + epoch, lat, lon, altitude,
                                 velocity=np.tile(velocity, (len(t), 1)))
        tracks[identity].altitude_basis = ["ellipsoidal"]*len(t)
        receive = np.arange(center - 35, center + 35, 1.0)
        slant = np.linalg.norm(cross)
        ridge = straight_doppler(receive, f0, 80, slant, center + slant / 343)
        measurements.append((RidgeTimes(receive), ridge, np.ones(len(receive)), {}))
        events.append(dict(f0_range_hz=[f0 - 1, f0 + 1], quality={"source_drift_fraction": 0}))
    seed = dict(lat=40.0015, lon=-99.998, elev_m=100, recording_start_time_s=epoch + 0.5,
                flight_ids=["a", "b"], point_id=0)
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0), vertical_datum="ellipsoidal")
    return observer, epoch, seed, tracks, events, measurements, terrain


def test_joint_refinement_uses_nonparallel_passes_and_profiles_altitude():
    observer, epoch, seed, tracks, events, measurements, terrain = physical_case()
    result = refine_candidate(seed, tracks, events, measurements, terrain, radius_m=500, clock_radius_s=3)
    error = np.linalg.norm(ecef(result["lat"], result["lon"], 100) - observer)
    assert error < 10
    assert abs(result["recording_start_time_s"] - epoch) < 0.1
    assert len(result["sensitivity"]["profiles"]) == 3
    assert result["sensitivity"]["radius_m"] > 0
    assert result["sensitivity"]["kind"] == "sensitivity"
    assert result["sensitivity"]["complete"]


@pytest.mark.parametrize("window", [(0.0, 0.0), (0.0, 0.25)])
def test_refinement_cannot_move_a_trusted_clock_outside_its_window(window):
    seed = dict(lat=40, lon=-100, recording_start_time_s=0.0, flight_ids=["a"])
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0))
    event = dict(f0_range_hz=[119, 121], quality={"source_drift_fraction": 0})
    # A freely fitted clock would move +2 seconds; the request forbids that.
    result = refine_candidate(seed, {"a": Flyover(32)}, [event], [measurement()], terrain,
                              altitude_offsets_m=(0.0,), recording_start_window_s=window)
    assert window[0] <= result["recording_start_time_s"] <= window[1]
    assert result["refinement_clock_bounds_s"] == list(window)
    if window[0] == window[1]:
        assert result["recording_start_time_s"] == 0
        assert not result["clock_boundary_limited"]
    with pytest.raises(ValueError, match="do not intersect"):
        refine_candidate(seed, {"a": Flyover()}, [event], [measurement()], terrain,
                         recording_start_window_s=(100, 101))


def test_source_fit_matches_independent_bounded_solver_on_interior_and_edges():
    from scipy.optimize import lsq_linear
    from aircraft_geoloc.matching import _source_fit
    rng = np.random.default_rng(440)
    factor, u = rng.uniform(0.7, 1.4, 80), np.linspace(-0.5, 0.5, 80)
    for _ in range(30):
        y = factor*(rng.uniform(110, 130)+rng.uniform(-15, 15)*u)
        weight = rng.uniform(0.1, 2, len(y))
        cap, scale = 2.4, 1.0
        matrix = np.vstack((np.column_stack((factor, factor*u))*np.sqrt(weight[:, None]), [0, 2*scale/cap]))
        target = np.r_[y*np.sqrt(weight), 0]
        expected = lsq_linear(matrix, target, bounds=([119, -cap], [121, cap]), tol=1e-12).x
        actual = _source_fit(factor, u, y, weight, [119, 121], cap, scale)
        np.testing.assert_allclose(actual, expected, atol=1e-7, rtol=0)


def test_full_sensitivity_reoptimizes_all_sources_without_moving_exact_utc():
    from aircraft_geoloc.matching import profile_candidate
    observer, epoch, seed, tracks, events, measurements, terrain = physical_case()
    for event in events:
        event["quality"]["frequency_loss_scale_hz"] = 0.05
    result = profile_candidate(seed, tracks, events, measurements, terrain,
        recording_start_window_s=(epoch, epoch), altitude_uncertainty_m=25,
        sound_speed_uncertainty_mps=1, radius_m=500, clock_radius_s=3)
    sensitivity = result["sensitivity"]
    assert set(sensitivity["sources"]) >= {"frequency", "clock", "altitude", "sound_speed", "source_frequency"}
    assert sensitivity["complete"] and not sensitivity["boundary_limited"]
    assert sensitivity["terrain_vertical_datum"] == "ellipsoidal"
    assert sensitivity["radius_m"] > 0
    assert all(p["recording_start_time_s"] == epoch for p in sensitivity["profiles"])
    assert len(sensitivity["profiles"]) >= 15
    assert len([p for p in sensitivity["profiles"] if p["flight_altitude_bias"] is not None]) == 4
    assert np.linalg.norm(ecef(result["lat"], result["lon"], 100)-observer) < 10


def test_missing_sensitivity_scenario_is_retained_as_incomplete_evidence():
    from aircraft_geoloc.matching import profile_candidate
    class LimitedTrack(Flyover):
        def acoustic(self, t, observer, c):
            factor, emitted, distance = super().acoustic(t, observer, c)
            return (factor if c >= 343 else np.full_like(factor, np.nan)), emitted, distance
    seed = dict(lat=40, lon=-100, recording_start_time_s=0, flight_ids=["a"])
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0))
    event = dict(f0_range_hz=[119, 121])
    result = profile_candidate(seed, {"a": LimitedTrack()}, [event], [measurement()], terrain,
                               recording_start_window_s=(0, 0), altitude_uncertainty_m=0)
    assert not result["sensitivity"]["complete"]
    assert any(p["source"] == "sound_speed" for p in result["sensitivity"]["failures"])


def test_exhausted_real_optimizer_cannot_report_complete_sensitivity(monkeypatch):
    import aircraft_geoloc.matching as matching
    real_minimize = matching.minimize
    def exhausted(*args, **kwargs):
        kwargs["options"] = dict(kwargs.get("options", {}), maxiter=0)
        return real_minimize(*args, **kwargs)
    monkeypatch.setattr(matching, "minimize", exhausted)
    seed = dict(lat=40, lon=-100, recording_start_time_s=0, flight_ids=["a"])
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0))
    result = refine_candidate(seed, {"a": Flyover()}, [dict(f0_range_hz=[119, 121])], [measurement()], terrain)
    assert not result["sensitivity"]["complete"]
    assert not any(p["optimizer_success"] for p in result["sensitivity"]["profiles"])


def test_flight_altitude_bias_preserves_derivatives_and_original_track():
    from aircraft_geoloc.matching import _altitude_bias
    observer, epoch, seed, tracks, events, measurements, terrain = physical_case()
    original = tracks["a"]
    shifted = _altitude_bias(original, 150)
    np.testing.assert_allclose(shifted.altitude-original.altitude, 150)
    assert np.max(np.linalg.norm(shifted.position(original.time)-original.position(original.time), axis=1)) > 149.9
    delta = shifted.xyz-original.xyz
    expected = original.speed_vector(original.time)+np.gradient(delta, original.relative_time, axis=0)
    np.testing.assert_allclose(shifted.speed_vector(original.time), expected, atol=1e-9)
    assert tracks["b"].altitude_basis == ["ellipsoidal"]*len(tracks["b"].time)


def test_unestablished_flight_datum_prevents_complete_sensitivity():
    from aircraft_geoloc.matching import profile_candidate
    track = Flyover()
    track.altitude_basis = ["barometric", "unspecified"]
    seed = dict(lat=40, lon=-100, recording_start_time_s=0, flight_ids=["a"])
    terrain = SimpleNamespace(sample=lambda lat, lon: np.array(100.0))
    result = profile_candidate(seed, {"a": track}, [dict(f0_range_hz=[119, 121])], [measurement()], terrain,
                               recording_start_window_s=(0, 0), altitude_uncertainty_m=0,
                               sound_speed_uncertainty_mps=0)
    assert not result["sensitivity"]["complete"]
    assert result["sensitivity"]["altitude_basis"]["a"] == ["barometric", "unspecified"]
    assert any("datum" in p["reason"] for p in result["sensitivity"]["failures"])


def test_overlay_prediction_uses_fitted_emission_drift_and_preserves_support():
    from aircraft_geoloc.matching import predict_fitted_ridge
    epoch = 1_790_000_000.0
    measured = measurement(drift=1.8)
    track = Flyover(epoch+30)
    fit = fit_ridge(track, None, measured, epoch, [118, 122])
    predicted = predict_fitted_ridge(track, None, epoch+measured[0].time, fit)
    rms = np.sqrt(np.mean((predicted-measured[1])**2))
    assert abs(rms-fit["rmse_hz"]) < 1e-10
    assert rms < 0.1
    constant = fit["f0_hz"]*track.acoustic(epoch+measured[0].time, None, 343)[0]
    assert np.sqrt(np.mean((constant-measured[1])**2)) > 0.4
    assert epoch < fit["source_reference_emission_time_s"] < epoch+60
    limited = Flyover(epoch+30, support=epoch+54)
    assert np.isnan(predict_fitted_ridge(limited, None, [epoch+55], fit)[0])
    incomplete = {k:v for k,v in fit.items() if k != "source_reference_emission_time_s"}
    with pytest.raises(ValueError, match="reference"):
        predict_fitted_ridge(track, None, epoch+measured[0].time, incomplete)
