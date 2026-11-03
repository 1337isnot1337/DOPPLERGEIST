"""Clock-query checks on recorded audio settings and historical flight segments.

The numeric boundary controls vary floating-point endpoints, not aircraft/audio.
The optional dense replay uses the real fixture from benchmark_prepared_measurements.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from dopplergeist.data_access import FlightIndex
from dopplergeist.matching import association_candidates, prepare_events
from dopplergeist.tiled_search import _partition_query_time_range


@pytest.fixture
def observed_settings():
    fixture = json.loads((Path(__file__).parent / "data/reference-cpa-real.json").read_text())
    events, rows = fixture["events"], fixture["cpa_rows"]
    day = math.floor(rows[0]["emission_time"] / 86400) * 86400
    anchor = [row["receive_time"] - events[0]["cpa_receive_s"] for row in rows[:2]]
    return [day, day + 86400], events, {"mode": "robust_ridge"}, {}, anchor


def test_recorded_clock_query_defaults_and_fallbacks(observed_settings):
    original, events, parameters, filters, anchor = observed_settings
    narrowed = _partition_query_time_range(*observed_settings)
    assert original[0] < narrowed[0] < narrowed[1] < original[1]
    assert _partition_query_time_range(original, events, parameters, {"association": "subsets"}, anchor) == narrowed
    for changes in (
        {4: None}, {4: [anchor[0], anchor[0]]}, {4: [math.nan, anchor[1]]},
        {4: [anchor[0], math.inf]}, {4: [anchor[0], 10 ** 1000]},
        {2: {"mode": "ridge"}}, {2: {"mode": "robust_ridge", "c": 0}},
        {2: {"mode": "robust_ridge", "c": math.inf}},
        {3: {"association": "full"}}, {3: {"silence": {"edge_margin_s": -1}}},
        {3: {"offset_tolerance_s": -1}}, {3: {"offset_tolerance_s": math.inf}},
        {1: []},
    ):
        args = list(observed_settings)
        for index, value in changes.items():
            args[index] = value
        assert _partition_query_time_range(*args) is original
    for name in ("cpa_tolerance_s", "speed_tolerance_mps", "slant_tolerance_m"):
        for value in (-1, math.nan, math.inf, "invalid", 10 ** 1000):
            changed = deepcopy(events)
            changed[0].setdefault("quality", {})[name] = value
            assert _partition_query_time_range(original, changed, parameters, filters, anchor) is original
    malformed = deepcopy(events)
    del malformed[0]["speed_range_mps"]
    assert _partition_query_time_range(original, malformed, parameters, filters, anchor) is original
    # Complete segments can bridge disjoint windows, so retain the original query.
    disjoint = [original[0], math.nextafter(narrowed[0], -math.inf)]
    assert _partition_query_time_range(disjoint, events, parameters, filters, anchor) is disjoint


def test_recorded_clock_query_contains_rounded_interval_boundaries(observed_settings):
    original, events, parameters, filters, anchor = observed_settings
    lower, upper = _partition_query_time_range(*observed_settings)
    tolerances = [event["quality"]["cpa_tolerance_s"] + 2.5 for event in events]
    radius = max(event["slant_range_m"][1] for event in events)
    overlaps = 0
    for first in (anchor[0], math.nextafter(anchor[0], math.inf), math.nextafter(anchor[1], -math.inf)):
        for first_tolerance in tolerances:
            for event, tolerance in zip(events, tolerances):
                for boundary in (first - first_tolerance - tolerance, first + first_tolerance + tolerance):
                    for start in (math.nextafter(boundary, -math.inf), boundary, math.nextafter(boundary, math.inf)):
                        if max(first - first_tolerance, start - tolerance) > min(first + first_tolerance, start + tolerance):
                            continue
                        for distance in (0.0, radius):
                            received = start + event["cpa_receive_s"]
                            for emitted in (math.nextafter(received - distance / 343.0, -math.inf),
                                            received - distance / 343.0,
                                            math.nextafter(received - distance / 343.0, math.inf)):
                                assert lower <= emitted <= upper
                                overlaps += 1
    assert overlaps > 10000


@pytest.fixture
def dense_recorded_input():
    fixture_path = os.environ.get("DOPPLERGEIST_REAL_DENSE_QUERY")
    index_path = os.environ.get("DOPPLERGEIST_REAL_DEVELOPMENT_INDEX")
    if not fixture_path or not index_path:
        pytest.skip("set DOPPLERGEIST_REAL_DENSE_QUERY and DOPPLERGEIST_REAL_DEVELOPMENT_INDEX")
    fixture = json.loads(Path(fixture_path).read_text())
    index = FlightIndex(index_path, track_cache_bytes=0)
    assert index.report["input_hash"] == fixture["index_input_hash"]
    events, measurements = prepare_events(fixture["events"])
    return fixture, index, events, measurements


def test_dense_recorded_query_preserves_candidates_and_complete_segments(dense_recorded_input):
    fixture, index, events, _ = dense_recorded_input
    narrowed = _partition_query_time_range(fixture["query_time_s"], events, fixture["scoring"], {},
                                          fixture["anchor_window_s"])
    tracks = list(index.query(fixture["query_bounds"], narrowed))
    ids = {track.id for track in tracks}
    original_count = fixture["track_query_preparation"]["queried_trajectories"]
    assert 0 < len(tracks) < original_count / 10
    assert any(track.time[0] < narrowed[0] or track.time[-1] > narrowed[1] for track in tracks)
    complete = {track.id: track for track in index.lookup(ids)}
    for track in tracks:
        np.testing.assert_array_equal(track.time, complete[track.id].time)
        np.testing.assert_array_equal(track.xyz, complete[track.id].xyz)
        np.testing.assert_array_equal(track.spline.c, complete[track.id].spline.c)
    table = pd.DataFrame(fixture["cpa_rows"])
    selected = table.loc[table.flight_id.isin(ids)]
    options = dict(anchor_window=fixture["anchor_window_s"], max_candidates=fixture["budget"]["max_candidates_per_tile"])
    before, before_counts = association_candidates(table, events, **options)
    after, after_counts = association_candidates(selected, events, **options)
    assert before and before == after
    assert after_counts["hypotheses_examined"] == before_counts["hypotheses_examined"]
    assert after_counts["work_units"] < before_counts["work_units"]
    missing = {item["track_id"] for item in fixture["unsupported_cpa_tracks"]} - ids
    assert missing
    with index.connect() as connection:
        intervals = dict((name, (start, end)) for name, start, end in
                         connection.execute("SELECT name, start, end FROM segments"))
    assert all(intervals[name][1] < narrowed[0] or intervals[name][0] > narrowed[1] for name in missing)
    print(f"real dense query: {original_count} -> {len(tracks)} complete segments; "
          f"{len(table)} -> {len(selected)} CPA rows; {len(after)} identical association payloads")


@pytest.mark.parametrize("driver", ["serial", "worker"])
def test_recorded_partition_driver_queries_before_scoring(dense_recorded_input, tmp_path, monkeypatch, driver):
    """Exercise each driver up to scoring with the recorded receiver and index."""
    import dopplergeist.parallel_tiles as parallel
    import dopplergeist.tiled_search as tiled
    from dopplergeist.native_cpa import CPA_BACKEND

    fixture, index, events, measurements = dense_recorded_input
    parameters, filters = fixture["scoring"], {"association": "subsets"}
    start_window = fixture["anchor_window_s"]
    budget = tiled.SearchBudget(**fixture["budget"])
    bounds = fixture["query_bounds"]
    tile, cells = next(tiled.grid_tiles(bounds, budget.spacing_m, budget.tile_cells, "EPSG:5070"))
    tile += "~t0"
    anchor = tiled._tile_anchor_window(tile, start_window, parameters, filters, events)
    expected = tiled._partition_query_time_range(fixture["query_time_s"], events, parameters, filters, anchor)
    point = pd.DataFrame([fixture["point"]])
    terrain = SimpleNamespace(last_sample_files=set(), last_sample_ocean_tiles=set(), failures=[])
    queries = []
    original_query = index.query

    def query(query_bounds, query_time):
        queries.append(query_time)
        yield from original_query(query_bounds, query_time)

    class ReachedScoring(RuntimeError):
        pass

    def score(points, tracks, *args, **kwargs):
        assert queries == [expected]
        assert kwargs["anchor_window"] == anchor
        assert 0 < len(tracks) < fixture["track_query_preparation"]["queried_trajectories"] / 10
        assert points.equals(point)
        raise ReachedScoring

    monkeypatch.setattr(index, "query", query)
    target = tiled if driver == "serial" else parallel
    monkeypatch.setattr(target, "_tile_coordinates", lambda *args: point.copy())
    monkeypatch.setattr(target, "_expanded_bounds", lambda *args: bounds)
    monkeypatch.setattr(target, "_score", score)
    if driver == "serial":
        monkeypatch.setattr(tiled, "grid_tiles", lambda *args: iter([(tile, cells)]))
        with pytest.raises(ReachedScoring):
            tiled.search_national([index], terrain, events, measurements,
                time_range_s=fixture["query_time_s"], output_dir=tmp_path, bounds=bounds, budget=budget,
                scoring=dict(parameters, recording_start_window_s=start_window), filters=filters, workers=1)
        runtime = json.loads((tmp_path / "manifest.json").read_text())["configuration"]["runtime"]
        if CPA_BACKEND == "python-cpa-v1":
            assert "cpa_backend" not in runtime
        else:
            assert runtime["cpa_backend"] == CPA_BACKEND
    else:
        monkeypatch.setattr(parallel, "_worker", dict(indexes=[index], terrain=terrain, events=events,
            measurements=measurements, bounds=bounds, time_range=fixture["query_time_s"], budget=budget,
            parameters=parameters, filters=filters, start_window=start_window, crs="EPSG:5070",
            ledger_directory=tmp_path, run_hash="recorded-query-test", score_kind="matched_group_support_minus_normalized_residual"))
        with pytest.raises(ReachedScoring):
            parallel.score_tile(f"coarse:{tile}", cells)
