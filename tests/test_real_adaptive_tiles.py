"""Optional subdivision/restart checks on recorded audio and flight tracks."""
import json
import os
from pathlib import Path
import shutil

import pytest

from dopplergeist.data_access import CachedTerrain, FlightIndex
from dopplergeist.matching import prepare_events
from dopplergeist.tiled_search import SearchBudget, search_national


def _run_interrupted_search(index_path, terrain_root, geoid, events, measurements, clock, output):
    os.setsid()
    index = FlightIndex(index_path)
    terrain = CachedTerrain(terrain_root, offline=True, geoid_path=geoid, adopt_existing=True)
    search_national([index], terrain, events, measurements,
        time_range_s=index.report["coverage"]["time_range_s"], output_dir=output,
        bounds=(-73.56, 40.85, -73.50, 40.90),
        budget=SearchBudget(spacing_m=2000, tile_cells=4, top_k=5, refine_spacing_m=2000,
                            max_candidates_per_tile=50),
        scoring={"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0.,
                 "recording_start_window_s": [clock, clock]}, workers=2)


def test_real_overloaded_tiles_split_and_resume(tmp_path):
    import multiprocessing
    import signal
    import time
    source, cache, reference, index_path = (os.environ.get(name) for name in (
        "DOPPLERGEIST_REAL_JOB_ROOT", "DOPPLERGEIST_REAL_CACHE_ROOT",
        "DOPPLERGEIST_REAL_REFERENCE_ROOT", "DOPPLERGEIST_REAL_DEVELOPMENT_INDEX"))
    if not all((source, cache, reference, index_path)):
        pytest.skip("set the real job, cache, reference and development index paths")
    job, cache, reference = Path(source), Path(cache), Path(reference)
    index = FlightIndex(index_path)
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    clock = json.loads((reference / "results/reference-local/ranked.json").read_text())[0]["recording_start_time_s"]
    terrain_root = tmp_path / "terrain"
    terrain_root.mkdir()
    for name in ("tileList.txt", "tileList.txt.sha256.json"):
        shutil.copy2(cache / "terrain" / name, terrain_root / name)
    raster = "Copernicus_DSM_COG_30_N40_00_W074_00_DEM.tif"
    shutil.copy2(reference / "data/terrain/copernicus90" / raster, terrain_root / raster)
    geoid = cache / "terrain/us_nga_egm08_25.tif"
    scoring = {"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0.,
               "recording_start_window_s": [clock, clock]}

    def run(name, capacity, workers, *, fine=False, progress=None):
        terrain = CachedTerrain(terrain_root, offline=True, geoid_path=geoid, adopt_existing=True)
        return search_national([index], terrain, events, measurements,
            time_range_s=index.report["coverage"]["time_range_s"], output_dir=tmp_path / name,
            bounds=(-73.56, 40.85, -73.50, 40.90),
            budget=SearchBudget(spacing_m=2000, tile_cells=4, top_k=5, refine_spacing_m=1000 if fine else 2000,
                                refine_finalists=1 if fine else 10,
                                max_candidates_per_tile=capacity), scoring=scoring, workers=workers,
            search_progress=progress)

    # This fixed clock and bounded region are an engineering replay, not location truth.
    baseline = run("baseline", 20000, 2)
    progress = []
    split = run("split", 50, 2, progress=progress.append)
    keys = ("score", "lat", "lon", "elev_m", "flight_ids", "recording_start_time_s", "event_ids")
    projection = lambda report: [{key: row.get(key) for key in keys} for row in report["ranked"]]
    assert projection(baseline) == projection(split)
    assert split["grid_points_searched"] == baseline["grid_points_searched"] > 0
    assert not split["tile_failures"]
    assert list((tmp_path / "split").glob("split-*.json"))
    assert split["finite_search_evidence"]["pruning_accounted_for"]
    assert progress and progress == sorted(progress) and progress[-1] == 1.0
    assert any(0 < value < .8 for value in progress) and .8 in progress
    resumed = run("split", 50, 1)
    assert resumed["tiles_resumed"] == split["tiles_completed"]
    assert resumed["ranked"] == split["ranked"]
    assert resumed["finite_search_evidence"] == split["finite_search_evidence"]

    shutil.copytree(tmp_path / "split", tmp_path / "corrupt")
    marker = next((tmp_path / "corrupt").glob("split-*.json"))
    value = json.loads(marker.read_text())
    value["children"].pop()
    marker.write_text(json.dumps(value))
    corrupt = run("corrupt", 50, 1)
    assert any("Corrupt tile subdivision checkpoint" in item["reason"] for item in corrupt["tile_failures"])
    assert corrupt["status"] == "partial"

    fine = run("fine", 100, 2, fine=True)
    assert fine["refinement_failure"] is None and fine["refinement_points_searched"] > 0
    assert fine["finite_search_evidence"]["stages"]["fine"]["stages"] > 4
    assert fine["finite_search_evidence"]["pruning_accounted_for"]

    if not hasattr(os, "setsid") or not Path("/proc").is_dir():
        return
    output = tmp_path / "interrupted"
    child = multiprocessing.get_context("spawn").Process(
        target=_run_interrupted_search,
        args=(index_path, terrain_root, geoid, events, measurements, clock, output))
    child.start()
    checkpoints = []
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and child.is_alive():
            checkpoints = list(output.glob("tile-*~*.json")) if output.exists() else []
            if checkpoints and os.getpgid(child.pid) == child.pid:
                break
            time.sleep(.05)
        else:
            pytest.fail("adaptive search did not checkpoint a child tile before interruption")
        os.killpg(child.pid, signal.SIGTERM)
        child.join(15)
        assert not child.is_alive()
        live = []
        for _ in range(50):
            live = []
            for proc in Path("/proc").iterdir():
                if not proc.name.isdigit():
                    continue
                try:
                    fields = (proc / "stat").read_text().split(") ", 1)[1].split()
                    if int(fields[2]) == child.pid and fields[0] != "Z":
                        live.append(int(proc.name))
                except (OSError, ValueError, IndexError):
                    pass
            if not live:
                break
            time.sleep(.1)
        assert not live
    finally:
        if child.is_alive():
            if os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGTERM)
            else:
                child.terminate()
            child.join(15)
    interrupted = run("interrupted", 50, 2)
    assert interrupted["tiles_resumed"] >= len(checkpoints)
    assert interrupted["ranked"] == split["ranked"]
    assert interrupted["finite_search_evidence"] == split["finite_search_evidence"]
