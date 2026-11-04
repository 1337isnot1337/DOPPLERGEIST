"""Optional regression using an archived real audio/aircraft regional run."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from dopplergeist.data_access import CachedTerrain, FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.tiled_search import (SearchBudget, _expanded_bounds, _latest_event_receive_time,
                                       _score, _tracks_for_points, tile_points)


def test_real_clock_excludes_late_unsupported_trajectories(tmp_path, monkeypatch):
    value = os.environ.get("DOPPLERGEIST_REAL_CLOCK_JOB")
    index_path = os.environ.get("DOPPLERGEIST_REAL_CLOCK_INDEX")
    terrain_path = os.environ.get("DOPPLERGEIST_REAL_CLOCK_TERRAIN")
    if not all((value, index_path, terrain_path)):
        pytest.skip("set the archived real job, aircraft index and terrain cache paths")
    job = Path(value)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    raw = json.loads((job / "discovery/discovery.json").read_text())["events"]
    params = dict(config["scoring"])
    window = params.pop("recording_start_window_s")
    filters = config["filters"]
    radius = max(event["slant_range_m"][1] for event in config["events"])
    events, measurements = prepare_events(raw, c=params["c"], max_distance_m=radius)
    assert events == config["events"]
    budget = SearchBudget(**config["budget"])
    terrain = CachedTerrain(terrain_path, offline=True)
    index = FlightIndex(index_path)
    spec = importlib.util.spec_from_file_location("verify_upload_http",
        Path(__file__).parents[1] / "scripts/verify_upload_http.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    support_files = sorted((job / "search/support").glob("coarse-*.json"))
    tested = 0
    for support_path in support_files:
        support = json.loads(support_path.read_text())
        failures = support.get("unsupported_cpa_tracks", [])
        if not failures:
            continue
        tile_id = support_path.stem.removeprefix("coarse-")
        payload = json.loads((job / "search" / f"tile-{tile_id}.json").read_text())["payload"]
        points = tile_points(payload["cells"], budget.spacing_m, config["bounds"], terrain, config["crs"])
        tracks = list(index.lookup([item["track_id"] for item in failures]))
        assert tracks
        latest = _latest_event_receive_time(events, params, filters, window)
        assert latest is not None and all(track.time[0] > latest for track in tracks)
        rows, counts = _score(points, tracks, events, measurements, budget, params, filters, window)
        assert rows == [] and not counts["unsupported_cpa_tracks"]
        assert {item["track_id"] for item in counts["clock_excluded_unsupported_tracks"]} == {t.id for t in tracks}
        for item in counts["clock_excluded_unsupported_tracks"]:
            assert verifier.valid_clock_exclusion(item, config)
            assert not verifier.valid_clock_exclusion({**item, "earliest_emission_s": item["latest_event_receive_s"]}, config)
            assert not verifier.valid_clock_exclusion({**item, "latest_event_receive_s": item["latest_event_receive_s"] - 1}, config)
            assert not verifier.valid_clock_exclusion(item, {**config, "filters": {**filters, "silence": {"edge_margin_s": 60}}})
        # A clock that reaches the same unmodified flight must not suppress it.
        shift = float(tracks[0].time[0] - latest + 1.0)
        overlapping = [window[0] + shift, window[1] + shift]
        _, unknown = _score(points, tracks, events, measurements, budget, params, filters, overlapping)
        assert any(item["track_id"] == tracks[0].id for item in unknown["unsupported_cpa_tracks"])
        assert _latest_event_receive_time(events, params, {**filters, "silence": {"edge_margin_s": 60}}, window) is None
        assert _latest_event_receive_time(events, params, filters, None) is None
        if not tested:
            # Probe the actual track against clock windows on both sides of its
            # first recorded emission, including the inclusive boundary.
            boundary_shift = float(tracks[0].time[0] - latest)
            before = [value + boundary_shift - 0.01 for value in window]
            after = [value + boundary_shift + 0.01 for value in window]
            assert tracks[0].time[0] > _latest_event_receive_time(events, params, filters, before)
            assert tracks[0].time[0] <= _latest_event_receive_time(events, params, filters, after)
            _, before_counts = _score(points, tracks, events, measurements, budget, params, filters, before)
            _, after_counts = _score(points, tracks, events, measurements, budget, params, filters, after)
            assert any(item["track_id"] == tracks[0].id for item in before_counts["clock_excluded_unsupported_tracks"])
            assert any(item["track_id"] == tracks[0].id for item in after_counts["unsupported_cpa_tracks"])
        tested += len(tracks)
    assert tested == 12

    # Compare full-tile scoring on original tracks and measurements with the
    # old conservative exclusion; every actual retained candidate must agree.
    supported_stages = [json.loads(path.read_text()) for path in support_files]
    supported_stages = [value for value in supported_stages if value.get("unsupported_cpa_tracks")]
    def ranked_count(value):
        tile_name = value["stage"].removeprefix("coarse:")
        return len(json.loads((job / "search" / f"tile-{tile_name}.json").read_text())["payload"]["ranked"])
    support = max(supported_stages, key=ranked_count)
    assert ranked_count(support) > 0
    tile_id = support["stage"].removeprefix("coarse:")
    cells = json.loads((job / "search" / f"tile-{tile_id}.json").read_text())["payload"]["cells"]
    points = tile_points(cells, budget.spacing_m, config["bounds"], terrain, config["crs"])
    tracks, points = _tracks_for_points([index], _expanded_bounds(cells, budget.spacing_m, radius, config["crs"]),
                                       config["time_range_s"], budget, points, terrain, radius, params["c"])
    import dopplergeist.tiled_search as tiled
    with monkeypatch.context() as patch:
        patch.setattr(tiled, "_latest_event_receive_time", lambda *args: None)
        previous_rows, previous_counts = _score(points, tracks, events, measurements, budget, params, filters, window)
    rows, counts = _score(points, tracks, events, measurements, budget, params, filters, window)
    assert rows and counts["candidates"] > 0
    assert rows == previous_rows
    assert counts["cpa_rows"] == previous_counts["cpa_rows"]
    assert counts["candidates"] == previous_counts["candidates"]
    assert counts["unclassified_candidate_assessments"] == previous_counts["unclassified_candidate_assessments"]
    assert len(previous_counts["unsupported_cpa_tracks"]) == len(counts["clock_excluded_unsupported_tracks"]) > 0
    assert not counts["unsupported_cpa_tracks"]


def test_real_clock_exclusion_evidence_rejects_tampering():
    value = os.environ.get("DOPPLERGEIST_REAL_CLOCK_REPLAY_JOB")
    if not value:
        pytest.skip("set the completed real clock-exclusion upload job path")
    job = Path(value)
    spec = importlib.util.spec_from_file_location("verify_upload_clock_evidence",
        Path(__file__).parents[1] / "scripts/verify_upload_http.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    def read(name):
        return json.loads((job / name).read_text())

    artifact = lambda name: job / name
    search = read("search/search-report.json")
    config = read("search/manifest.json")["configuration"]
    refinement = read("refined-candidates.json")
    assert search["model_support"]["clock_excluded_unsupported_track_evaluations"] > 0
    report = verifier.inspect_finite_search(artifact, read, search, config, refinement)
    assert report["complete"] is True
    def read_with_damaged_bound(name):
        data = read(name)
        if name.startswith("search/support/") and data.get("clock_excluded_unsupported_tracks"):
            item = data["clock_excluded_unsupported_tracks"][0]
            item["earliest_emission_s"] = item["latest_event_receive_s"]
        return data
    with pytest.raises(ValueError, match="Invalid unsupported-track clock exclusion evidence"):
        verifier.inspect_finite_search(artifact, read_with_damaged_bound, search, config, refinement)
    changed = {**search, "model_support": {**search["model_support"],
        "clock_excluded_unsupported_track_evaluations": search["model_support"]["clock_excluded_unsupported_track_evaluations"] + 1}}
    with pytest.raises(ValueError, match="Clock-excluded unsupported-track totals"):
        verifier.inspect_finite_search(artifact, read, changed, config, refinement)
