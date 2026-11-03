"""Physical small-grid oracles for the agreed finite-search report contract.

No fake scorer, candidate table, acceptance flag or reference location is passed
to the driver. These regional controls establish accounting, not real accuracy.
"""
from dataclasses import replace

from aircraft_geoloc.terrain import Terrain
from aircraft_geoloc.tiled_search import SearchBudget, merge_candidates, search_national
from test_tiled_search import scenario


def execute(tmp_path, *, count=2, refine=False, top_k=10000, tile_cells=2):
    index, _, events, measurements, bounds, times, origin = scenario(
        tmp_path, count=count, receiver_offset=(250, 250) if refine else (0, 0))
    for i, event in enumerate(events):
        event["event_id"] = f"event-{i}"
    budget = SearchBudget(spacing_m=1000, refine_spacing_m=250 if refine else 1000,
                          refine_finalists=1, top_k=top_k, tile_cells=tile_cells)
    kwargs = dict(indexes=[index], terrain=Terrain(constant_m=0), events=events,
                  measurements=measurements, time_range_s=times, bounds=bounds,
                  scoring={"mode": "robust_ridge", "recording_start_window_s": [origin, origin],
                           "time_sweep_s": 0.0})
    report = search_national(**kwargs, budget=budget, output_dir=tmp_path/"wide")
    return report, kwargs, budget


def identity(row):
    return (tuple(row["event_indices"]), tuple(row["flight_ids"]),
            tuple(row["pass_emission_times_s"]), row["lat"], row["lon"],
            row["recording_start_time_s"])


def check_bound(full, retained):
    full_rows = {identity(row): row for row in full["ranked"]}
    kept = {identity(row): row for row in retained["ranked"]}
    assert kept.keys() <= full_rows.keys()
    discarded = [row for key, row in full_rows.items() if key not in kept]
    assert discarded
    finite = retained["finite_search_evidence"]
    assert finite["schema_version"] == 1 and finite["scope"] == "evaluated_finite_grid"
    assert finite["complete"] is True and finite["pruning_accounted_for"] is True
    # The bound must cover the largest dropped physical score, including losses
    # inside tiles. It must not be reconstructed from only the retained rows.
    assert finite["best_discarded_score"] >= max(row["score"] for row in discarded)
    assert finite["discarded_count"] >= len(discarded)
    assert finite["score_kind"] == retained["ranked"][0]["score_kind"]
    modes = {item["mode_id"]: item for item in finite["retained_modes"]}
    assert len(modes) == len(retained["ranked"])
    assert set(modes) == {row["mode_id"] for row in retained["ranked"]}
    for key, row in kept.items():
        assert row["mode_id"] == full_rows[key]["mode_id"]
        assert modes[row["mode_id"]]["score"] == row["score"]
        assert modes[row["mode_id"]]["event_groups"] == len(row["event_indices"])


def test_actual_grid_drop_bound_and_mode_ids_survive_partition_and_resume(tmp_path):
    full, kwargs, budget = execute(tmp_path)
    narrow_budget = replace(budget, top_k=3)
    narrow = search_national(**kwargs, budget=narrow_budget, output_dir=tmp_path/"narrow")
    check_bound(full, narrow)
    assert full["finite_search_evidence"]["discarded_count"] == 0
    assert full["finite_search_evidence"]["best_discarded_score"] is None
    # With disjoint coarse cells and no refinement, each dropped seed occurs once.
    assert narrow["finite_search_evidence"]["discarded_count"] == len(full["ranked"])-3
    resumed = search_national(**kwargs, budget=narrow_budget, output_dir=tmp_path/"narrow")
    assert resumed["tiles_resumed"] == resumed["tiles_total"]
    for key in ("complete", "pruning_accounted_for", "discarded_count", "best_discarded_score", "retained_modes"):
        assert resumed["finite_search_evidence"][key] == narrow["finite_search_evidence"][key]
    repartitioned = search_national(**kwargs, budget=replace(narrow_budget, tile_cells=4),
                                   output_dir=tmp_path/"repartitioned")
    check_bound(full, repartitioned)
    assert [row["mode_id"] for row in narrow["ranked"]] == [row["mode_id"] for row in repartitioned["ranked"]]


def test_actual_fine_grid_retention_cannot_hide_the_best_dropped_score(tmp_path):
    full, kwargs, budget = execute(tmp_path, refine=True)
    narrow = search_national(**kwargs, budget=replace(budget, top_k=3), output_dir=tmp_path/"narrow")
    # Both runs select the same single coarse refinement seed. Therefore the
    # high-retention run is an oracle over the same declared evaluated points.
    assert identity(full["coarse_ranked"][0]) == identity(narrow["coarse_ranked"][0])
    check_bound(full, narrow)
    assert narrow["finite_search_evidence"]["refine_spacing_m"] == 250


def test_event_omission_and_unfinished_tiles_cannot_certify_finite_completion(tmp_path):
    _, kwargs, budget = execute(tmp_path, count=4)
    capped = search_national(**kwargs, budget=budget, filters={"max_events": 3},
                            output_dir=tmp_path/"capped")
    stopped = search_national(**kwargs, budget=replace(budget, max_tiles=1),
                             output_dir=tmp_path/"stopped")
    for report in (capped, stopped):
        assert report["status"] == "partial"
        assert report["finite_search_evidence"]["complete"] is False


def test_nearby_distinct_seeds_are_not_erased_as_exact_duplicates():
    original = {"score": 1.0, "event_indices": [0], "flight_ids": ["a"],
                "pass_emission_times_s": [100.0], "x": 0.0, "y": 0.0,
                "lat": 40.0, "lon": -100.0, "recording_start_time_s": 0.0}
    moved = dict(original, x=1e-7, lon=-100.0+1e-12)
    later = dict(original, recording_start_time_s=1e-7)
    other_pass = dict(original, pass_emission_times_s=[100.0001])
    rows = merge_candidates([original, moved, later, other_pass, original], 10)
    assert len(rows) == 4
    assert {identity(row) for row in rows} == {identity(row) for row in [original, moved, later, other_pass]}
