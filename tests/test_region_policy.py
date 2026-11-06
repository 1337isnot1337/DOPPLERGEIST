import pytest

from dopplergeist.region_policy import ResultRegionPolicy, redact_location_outputs


@pytest.mark.parametrize(
    "lat,lon",
    [
        (50.4501, 30.5234),
        (49.8397, 24.0297),
        (46.4825, 30.7233),
        (48.4647, 35.0462),
    ],
)
def test_nonoccupied_ukraine_is_restricted(lat, lon):
    assert ResultRegionPolicy().restricted_region(lat, lon) == "ukraine"


@pytest.mark.parametrize(
    "lat,lon",
    [
        (44.9521, 34.1024),
        (48.0159, 37.8028),
        (47.0971, 37.5434),
    ],
)
def test_occupied_ukraine_is_allowed(lat, lon):
    assert ResultRegionPolicy().restricted_region(lat, lon) is None


@pytest.mark.parametrize(
    "lat,lon",
    [
        (32.0853, 34.7818),
        (31.5017, 34.4668),
    ],
)
def test_israel_and_gaza_are_restricted(lat, lon):
    assert ResultRegionPolicy().restricted_region(lat, lon) == "israel_gaza"


@pytest.mark.parametrize(
    "lat,lon",
    [
        (31.9539, 35.9106),
        (41.0082, 28.9784),
        (40.7128, -74.0060),
    ],
)
def test_other_locations_are_allowed(lat, lon):
    assert ResultRegionPolicy().restricted_region(lat, lon) is None


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError):
        ResultRegionPolicy().restricted_region(float("nan"), 30.0)


def test_redaction_removes_location_artifacts(tmp_path):
    (tmp_path / "search").mkdir()
    (tmp_path / "search" / "search-report.json").write_text("{}")
    for name in ("refined-candidates.json", "decision.json", "spectral-comparison.json", "keep.txt"):
        (tmp_path / name).write_text("{}")
    redact_location_outputs(tmp_path)
    assert not (tmp_path / "search").exists()
    assert not (tmp_path / "refined-candidates.json").exists()
    assert not (tmp_path / "decision.json").exists()
    assert not (tmp_path / "spectral-comparison.json").exists()
    assert (tmp_path / "keep.txt").is_file()
