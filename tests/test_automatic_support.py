"""Real producer-to-product coverage checks; no localization benchmark."""
import pytest

from aircraft_geoloc import tiled_search
from aircraft_geoloc.automatic import _coverage
from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import SearchBudget, search_national
from test_tiled_search import scenario


@pytest.mark.parametrize("missing_accounting", [False, True])
def test_product_coverage_consumes_actual_model_support_report(tmp_path, monkeypatch, missing_accounting):
    index, _, events, measurements, bounds, times, origin = scenario(tmp_path)
    if missing_accounting:
        original = tiled_search.score_candidate

        def unreported(*args, **kwargs):
            row = original(*args, **kwargs)
            row.pop("scoring_assessment", None)
            return row

        monkeypatch.setattr(tiled_search, "score_candidate", unreported)
    report = search_national([index], Terrain(constant_m=0), events, measurements,
        time_range_s=times, output_dir=tmp_path/"search", bounds=bounds,
        budget=SearchBudget(spacing_m=1000, tile_cells=4, refine_spacing_m=1000),
        scoring={"mode": "robust_ridge", "recording_start_window_s": [origin, origin], "time_sweep_s": 0})
    assert report["ranked"]
    coverage = _coverage({"search": {"coverage": "conus"}}, report, {})
    assert coverage["data_status"] == "available"
    assert coverage["search_complete"] is (not missing_accounting)
    if missing_accounting:
        assert report["model_support"]["unknown_trials"] == 0
        count = report["model_support"]["unreported_trial_envelopes"]
        assert count > 0
        assert f"unreported trial envelopes: {count}" in " ".join(coverage["limitations"])
    else:
        assert report["model_support_complete"] is True
        assert not any("Trajectory model assessment is incomplete" in item for item in coverage["limitations"])
