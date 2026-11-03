"""Geometry regressions from real regional recording searches; no flight fixtures."""

import pytest

from dopplergeist.matching import _geographic_refinement_frame


@pytest.mark.parametrize(
    ("candidate", "area", "axis", "side", "edge"),
    [
        # ESID 762: finalist at the eastern edge of the Texas Hill Country box.
        ({"lat": 30.35453271220664, "lon": -98.73000004871692},
         [-98.98, 30.29, -98.73, 30.47], 0, 1, -98.73),
        # ESID 914: finalist at the northern edge of the south Dallas box.
        ({"lat": 32.63999999897584, "lon": -97.19999995501699},
         [-97.20, 32.46, -97.01, 32.64], 1, 1, 32.64),
        # The same finalist is also at the box's western edge.
        ({"lat": 32.63999999897584, "lon": -97.19999995501699},
         [-97.20, 32.46, -97.01, 32.64], 0, 0, -97.20),
    ],
)
def test_refinement_frame_intersects_real_search_edge(candidate, area, axis, side, edge):
    limits, scales = _geographic_refinement_frame(candidate, 500.0, area)
    assert all(lo <= 0 <= hi for lo, hi in limits)
    assert all(-500.0 <= lo <= hi <= 500.0 for lo, hi in limits)
    origin = (candidate["lon"], candidate["lat"])[axis]
    assert origin + limits[axis][side] / scales[axis] == pytest.approx(edge, abs=1e-12)


def test_refinement_rejects_real_out_of_scope_seed():
    # The top candidate returned by the earlier ESID 914 run escaped both edges.
    with pytest.raises(ValueError, match="seed must lie within"):
        _geographic_refinement_frame(
            {"lat": 32.64565044189285, "lon": -97.20311082897912},
            500.0, [-97.20, 32.46, -97.01, 32.64],
        )
