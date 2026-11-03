"""Real-geometry controls for the declared bounded-trial assessment contract.

These controls use the actual propagation and robust scorer without monkeypatches.
They establish classification behavior, not localization accuracy.
"""
import math

import numpy as np

from aircraft_geoloc.geometry import ecef
from aircraft_geoloc.search import score_candidate
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import tile_points
from test_tiled_search import scenario


def score(tmp_path, *, offset_s=0., sweep_s=0., incompatible_ridges=False):
    _, tracks, events, measurements, bounds, _, origin = scenario(tmp_path)
    point = next(tile_points((0, 1900, 1, 1901), 1000, bounds,
                            Terrain(constant_m=0), "EPSG:5070").itertuples())
    observer = ecef(point.lat, point.lon, point.elev_m)
    passes = [track.closest_approaches(observer, 4000)[0] for track in tracks]
    if incompatible_ridges:
        measurements = [(spec, ridge + 100.*(np.arange(len(ridge)) % 2), weight, fit)
                        for spec, ridge, weight, fit in measurements]
    candidate = {"point_id": point.point_id, "passes": passes, "event_indices": [0, 1]}
    return score_candidate(candidate, point, {track.id: track for track in tracks},
                           events, measurements, mode="robust_ridge",
                           time_origin=origin+offset_s, time_sweep_s=sweep_s, time_step_s=200.)


def assessment(row):
    result = row.get("scoring_assessment")
    assert isinstance(result, dict), "Every bounded robust scoring call needs trial accounting"
    assert type(result.get("complete")) is bool
    for key in ("evaluated_trials", "rejected_trials", "unknown_trials"):
        assert type(result.get(key)) is int and result[key] >= 0
    return result


def test_actual_supported_fixed_clock_is_classified(tmp_path):
    row = score(tmp_path)
    assert math.isfinite(row["score"]) and row["score"] > 1.99
    result = assessment(row)
    assert result["complete"] is True
    assert result["evaluated_trials"] >= 1 and result["unknown_trials"] == 0


def test_actual_finite_winner_cannot_hide_unsupported_clock_trials(tmp_path):
    # Each real trajectory spans 300 seconds. The center clock fits; the two
    # +/-200-second trials place all ridge samples outside trajectory support.
    row = score(tmp_path, sweep_s=200.)
    assert math.isfinite(row["score"]) and row["score"] > 1.99
    result = assessment(row)
    assert result["complete"] is False
    assert result["evaluated_trials"] >= 1 and result["unknown_trials"] >= 2


def test_actual_all_unsupported_trials_are_not_admissible_rejections(tmp_path):
    row = score(tmp_path, offset_s=200.)
    assert row["score"] == -math.inf
    result = assessment(row)
    assert result["complete"] is False and result["unknown_trials"] >= 1


def test_actual_supported_acoustic_loss_rejection_is_classified(tmp_path):
    # Positive-frequency observations deliberately disagree with the bounded
    # source model. Geometry is supported; the actual association loss rejects.
    row = score(tmp_path, incompatible_ridges=True)
    assert row["score"] == -math.inf
    result = assessment(row)
    assert result["complete"] is True
    assert result["unknown_trials"] == 0 and result["rejected_trials"] >= 1
