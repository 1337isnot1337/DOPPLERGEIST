"""Verify worker-ledger imports using an actual running search's evidence."""
import os
from pathlib import Path
import sqlite3

import pytest

from dopplergeist.data_access import DataUnavailable
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.parallel_retention import import_retention_stage


def _run_real_search_in_new_group(index_paths, terrain_root, events, measurements,
                                  times, output, bounds, budget, scoring):
    from dopplergeist.data_access import CachedTerrain, FlightIndex
    from dopplergeist.tiled_search import search_national

    os.setsid()
    terrain = CachedTerrain(terrain_root, offline=True)
    search_national([FlightIndex(path) for path in index_paths], terrain, events, measurements,
                    time_range_s=times, output_dir=output, bounds=bounds, budget=budget,
                    scoring=scoring, workers=2)


def test_real_retention_stages_survive_worker_import(tmp_path):
    source = os.environ.get("DOPPLERGEIST_REAL_RETENTION_LEDGER")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_RETENTION_LEDGER to a real search ledger")
    source = Path(source)
    snapshot = tmp_path / "worker.sqlite"
    with sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True) as current:
        with sqlite3.connect(snapshot) as worker:
            current.backup(worker)
    with sqlite3.connect(snapshot) as worker:
        run_hash, score_kind = worker.execute("SELECT identity, score_kind FROM run").fetchone()
        populated = worker.execute(
            "SELECT s.name, s.checksum FROM stages s JOIN bounds b ON b.stage=s.name "
            "WHERE s.name LIKE 'coarse:%' GROUP BY s.name ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        empty = worker.execute(
            "SELECT name, checksum FROM stages WHERE name LIKE 'coarse:%' AND occurrences=0 LIMIT 1"
        ).fetchone()
    assert populated is not None and empty is not None
    target = RetentionLedger(tmp_path / "parent.sqlite", run_hash, score_kind)
    for stage, checksum in (populated, empty, populated):
        import_retention_stage(target, snapshot, stage, checksum)
        assert target.stage_valid(stage, checksum)
    with pytest.raises(DataUnavailable):
        import_retention_stage(target, snapshot, populated[0], populated[1] + "0")
    assert target.stage_valid(*populated)
    with sqlite3.connect(snapshot) as worker, sqlite3.connect(target.path) as parent:
        for stage, _ in (populated, empty):
            for table, column in (("stages", "name"), ("records", "stage"), ("bounds", "stage")):
                expected = worker.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY 1,2", (stage,)).fetchall()
                actual = parent.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY 1,2", (stage,)).fetchall()
                assert actual == expected


def test_real_tiles_match_sequential_scoring_and_preserve_ledgers(tmp_path):
    import json
    import multiprocessing
    import shutil
    from concurrent.futures import ProcessPoolExecutor

    from dopplergeist.data_access import FlightIndex, content_hash
    from dopplergeist.matching import prepare_events
    from dopplergeist.parallel_tiles import TileFailure, initialize_tile_worker, ordered_tile_results, score_tile
    from dopplergeist.tiled_search import SearchBudget

    source = os.environ.get("DOPPLERGEIST_REAL_JOB_ROOT")
    cache = os.environ.get("DOPPLERGEIST_REAL_CACHE_ROOT")
    if not source or not cache:
        pytest.skip("set the real job and cache roots")
    job, cache = Path(source), Path(cache)
    manifest = json.loads((job / "search/manifest.json").read_text())
    config = manifest["configuration"]
    tiles = [(name, json.loads((job / f"search/tile-{name}.json").read_text())["payload"])
             for name in ("-10_1", "-9_1")]
    # A previously scored clock makes the development replay small. It is not
    # supplied to the real automatic job or treated as location truth.
    clock = tiles[0][1]["ranked"][0]["recording_start_time_s"]
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    assert content_hash(events) == content_hash(config["events"])
    available = {FlightIndex(path).report["input_hash"]: str(path)
                 for path in (cache / "flights").glob("*/staging-0/*.sqlite")}
    index_paths = [available[index["input_hash"]] for index in config["indexes"]]
    budget = SearchBudget(**config["budget"])
    params = dict(config["scoring"], time_origin=clock, time_sweep_s=0.)
    params.pop("recording_start_window_s", None)
    run_hash = content_hash({"source_run": manifest["run_hash"], "development_clock_s": clock})
    score_kind = "matched_group_support_minus_normalized_residual"
    args = (index_paths, cache / "terrain", {"offline": True}, events, measurements,
            config["bounds"], config["time_range_s"], budget, params, config["filters"],
            None, config["crs"], tmp_path / "workers", run_hash, score_kind)
    stages = [(f"coarse:{name}", payload["cells"]) for name, payload in tiles]

    initialize_tile_worker(*args)
    serial = [score_tile(stage, cells) for stage, cells in stages]
    jobs = [(stage, cells, None, None) for stage, cells in stages]
    jobs.append((stages[0][0], stages[0][1], serial[0][0], None))
    parallel = []
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_tile_worker, initargs=args) as pool:
        for stage, cells, result, was_cached in ordered_tile_results(
                pool, jobs, 2, lambda stage, cells, future: future.result()):
            if was_cached:
                assert stage == stages[0][0] and result == serial[0][0]
            else:
                assert stage == stages[len(parallel)][0] and cells == stages[len(parallel)][1]
                parallel.append(result)
    parent = RetentionLedger(tmp_path / "parallel-parent.sqlite", run_hash, score_kind)
    assert sum(p[0]["counts"].get("candidates", 0) for p in serial) > 0
    for (stage, _), (expected, expected_db), (actual, worker_db) in zip(stages, serial, parallel):
        assert json.dumps(actual, sort_keys=True, allow_nan=True) == json.dumps(expected, sort_keys=True, allow_nan=True)
        checksum = actual["retention_checksum"]
        assert RetentionLedger(expected_db, run_hash, score_kind).stage_valid(stage, checksum)
        import_retention_stage(parent, worker_db, stage, checksum)
        assert parent.stage_valid(stage, checksum)

    # A real tile with its terrain file deliberately unavailable must carry
    # the provider failure back from the worker instead of losing provenance.
    missing = tmp_path / "missing-terrain"
    missing.mkdir()
    for name in ("tileList.txt", "tileList.txt.sha256.json"):
        shutil.copy2(cache / "terrain" / name, missing / name)
    failure_args = list(args)
    failure_args[1] = missing
    failure_args[2] = {"offline": True, "geoid_path": cache / "terrain/us_nga_egm08_25.tif"}
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_tile_worker, initargs=tuple(failure_args)) as pool:
        future = pool.submit(score_tile, *stages[0])
        with pytest.raises(TileFailure) as caught:
            future.result()
    assert "Terrain coverage unavailable" in str(caught.value)
    assert caught.value.provenance["terrain_failures"]
    assert any(Path(item["path"]).name == "tileList.txt" for item in caught.value.provenance["terrain_files"])


def test_real_terrain_tracks_ocean_tiles_per_sample():
    import json
    import math

    from dopplergeist.data_access import CachedTerrain

    source = os.environ.get("DOPPLERGEIST_REAL_JOB_ROOT")
    cache = os.environ.get("DOPPLERGEIST_REAL_CACHE_ROOT")
    if not source or not cache:
        pytest.skip("set the real job and cache roots")
    job, cache = Path(source), Path(cache)
    terrain = CachedTerrain(cache / "terrain", offline=True)
    ocean_rows = json.loads((job / "search/tile-0_2.json").read_text())["payload"]["ranked"]
    for row in ocean_rows:
        north = math.floor(row["lat"]-1/2400)
        east = math.floor(row["lon"]+1/2400)
        tag = (f"Copernicus_DSM_COG_30_{'N' if north >= 0 else 'S'}{abs(north):02d}_00_"
               f"{'E' if east >= 0 else 'W'}{abs(east):03d}_00_DEM")
        if tag not in terrain.catalog:
            break
    else:
        pytest.fail("the saved real tile no longer contains the expected ocean point")
    land = json.loads((job / "search/tile--10_1.json").read_text())["payload"]["ranked"][0]
    terrain.sample([row["lat"]], [row["lon"]])
    assert terrain.last_sample_ocean_tiles == {tag}
    terrain.sample([land["lat"]], [land["lon"]])
    assert not terrain.last_sample_ocean_tiles and tag in terrain.ocean_tiles


def test_real_search_parallel_resume_and_terrain_failures(tmp_path):
    import json
    import shutil

    from dopplergeist.data_access import CachedTerrain, FlightIndex
    from dopplergeist.matching import prepare_events
    from dopplergeist.tiled_search import SearchBudget, search_national

    source = os.environ.get("DOPPLERGEIST_REAL_JOB_ROOT")
    cache = os.environ.get("DOPPLERGEIST_REAL_CACHE_ROOT")
    reference = os.environ.get("DOPPLERGEIST_REAL_REFERENCE_ROOT")
    index_path = os.environ.get("DOPPLERGEIST_REAL_DEVELOPMENT_INDEX")
    if not all((source, cache, reference, index_path)):
        pytest.skip("set the real job, cache, reference and development index paths")
    job, cache, reference = Path(source), Path(cache), Path(reference)
    index = FlightIndex(index_path)
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    # This fitted clock and small regional index are for an engineering replay,
    # not evidence for the recording's actual location or complete coverage.
    clock = json.loads((reference / "results/reference-local/ranked.json").read_text())[0]["recording_start_time_s"]
    budget = SearchBudget(spacing_m=2000, tile_cells=4, top_k=5, refine_spacing_m=2000)
    bounds = (-73.56, 40.85, -73.50, 40.90)
    scoring = {"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0.,
               "recording_start_window_s": [clock, clock]}
    geoid = cache / "terrain/us_nga_egm08_25.tif"
    raster = "Copernicus_DSM_COG_30_N40_00_W074_00_DEM.tif"
    roots = {name: tmp_path / name for name in ("terrain", "missing-terrain")}
    for root in roots.values():
        root.mkdir()
        for name in ("tileList.txt", "tileList.txt.sha256.json"):
            shutil.copy2(cache / "terrain" / name, root / name)
    shutil.copy2(reference / "data/terrain/copernicus90" / raster, roots["terrain"] / raster)

    def run(name, workers, terrain_root):
        terrain = CachedTerrain(terrain_root, offline=True, geoid_path=geoid, adopt_existing=True)
        result = search_national([index], terrain, events, measurements,
                                 time_range_s=index.report["coverage"]["time_range_s"],
                                 output_dir=tmp_path / name, bounds=bounds, budget=budget,
                                 scoring=scoring, workers=workers)
        provenance = terrain.provenance()
        provenance["files"] = sorted(provenance["files"], key=lambda item: item["path"])
        return result, provenance

    serial, serial_sources = run("serial", 1, roots["terrain"])
    parallel, parallel_sources = run("parallel", 2, roots["terrain"])
    resumed, resumed_sources = run("parallel", 3, roots["terrain"])
    resumed_one, resumed_one_sources = run("parallel", 1, roots["terrain"])
    automatic, automatic_sources = run("automatic", None, roots["terrain"])
    for key in ("ranked", "coarse_ranked", "status", "tiles_completed", "grid_points_searched",
                "core_assessed_mode_ids", "scope"):
        assert json.dumps(serial[key], sort_keys=True, allow_nan=True) == json.dumps(parallel[key], sort_keys=True, allow_nan=True)
    for key in ("pruning_accounted_for", "complete", "best_discarded_score", "discarded_bound_status", "retained_modes"):
        assert serial["finite_search_evidence"][key] == parallel["finite_search_evidence"][key]
    assert serial_sources == parallel_sources == resumed_sources == resumed_one_sources == automatic_sources
    assert parallel["bounded_concurrency"] == 2 and resumed["bounded_concurrency"] == 3
    assert resumed["tiles_resumed"] == parallel["tiles_completed"] and resumed["ranked"] == parallel["ranked"]
    assert resumed_one["bounded_concurrency"] == 1
    assert resumed_one["tiles_resumed"] == parallel["tiles_completed"] and resumed_one["ranked"] == parallel["ranked"]
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    assert automatic["bounded_concurrency"] == min(max(1, available - 1), automatic["tiles_total"])
    assert automatic["ranked"] == parallel["ranked"]

    serial_missing, serial_failure_sources = run("serial-missing", 1, roots["missing-terrain"])
    parallel_missing, parallel_failure_sources = run("parallel-missing", 2, roots["missing-terrain"])
    assert serial_missing["tile_failures"]
    assert serial_missing["tile_failures"] == parallel_missing["tile_failures"]
    assert serial_failure_sources == parallel_failure_sources


def test_real_ocean_provenance_survives_parallel_resume(tmp_path):
    import json
    import math
    import multiprocessing
    import signal
    import time

    from dopplergeist.data_access import CachedTerrain, FlightIndex
    from dopplergeist.matching import prepare_events
    from dopplergeist.tiled_search import SearchBudget, search_national

    source = os.environ.get("DOPPLERGEIST_REAL_JOB_ROOT")
    cache = os.environ.get("DOPPLERGEIST_REAL_CACHE_ROOT")
    if not source or not cache:
        pytest.skip("set the real job and cache roots")
    job, cache = Path(source), Path(cache)
    terrain = CachedTerrain(cache / "terrain", offline=True)
    rows = json.loads((job / "search/tile-0_2.json").read_text())["payload"]["ranked"]
    for row in rows:
        north, east = math.floor(row["lat"]-1/2400), math.floor(row["lon"]+1/2400)
        tag = (f"Copernicus_DSM_COG_30_{'N' if north >= 0 else 'S'}{abs(north):02d}_00_"
               f"{'E' if east >= 0 else 'W'}{abs(east):03d}_00_DEM")
        if tag not in terrain.catalog:
            break
    else:
        pytest.fail("the saved real tile no longer contains the expected ocean point")
    # This is a previously evaluated search hypothesis, not location truth.
    clock = row["recording_start_time_s"]
    times = (clock-120, clock+3720)
    config = json.loads((job / "search/manifest.json").read_text())["configuration"]
    available = {FlightIndex(path).report["input_hash"]: path
                 for path in (cache / "flights").glob("*/staging-0/*.sqlite")}
    indexes = [FlightIndex(available[item["input_hash"]]) for item in config["indexes"]]
    enclosing = [index for index in indexes
                 if index.report["coverage"]["time_range_s"][0] <= times[0]
                 and index.report["coverage"]["time_range_s"][1] >= times[1]]
    indexes = enclosing or indexes
    events, measurements = prepare_events(json.loads((job / "discovery/discovery.json").read_text())["events"])
    budget = SearchBudget(spacing_m=2000, tile_cells=1, top_k=5, refine_spacing_m=2000)
    bounds = (row["lon"]-.00005, row["lat"]-.00005, row["lon"]+.00005, row["lat"]+.00005)
    scoring = {"mode": "robust_ridge", "time_origin": clock, "time_sweep_s": 0.,
               "recording_start_window_s": [clock, clock]}

    def run(name, workers):
        terrain = CachedTerrain(cache / "terrain", offline=True)
        result = search_national(indexes, terrain, events, measurements, time_range_s=times,
                                 output_dir=tmp_path / name, bounds=bounds, budget=budget,
                                 scoring=scoring, workers=workers)
        provenance = terrain.provenance()
        provenance["files"] = sorted(provenance["files"], key=lambda item: item["path"])
        return result, provenance

    serial, serial_sources = run("serial-ocean", 1)
    parallel, parallel_sources = run("parallel-ocean", 2)
    resumed, resumed_sources = run("parallel-ocean", 3)
    assert serial["grid_points_searched"] > 0 and serial["ranked"] == parallel["ranked"] == resumed["ranked"]
    assert serial["status"] == parallel["status"] == resumed["status"]
    assert parallel["tiles_completed"] == resumed["tiles_resumed"]
    assert serial_sources == parallel_sources == resumed_sources
    assert tag in resumed_sources["catalogue_absent_ocean_tiles"]

    if not hasattr(os, "setsid") or not Path("/proc").is_dir():
        pytest.skip("process-group interruption check requires Linux")
    output = tmp_path / "interrupted-ocean"
    child = multiprocessing.get_context("spawn").Process(
        target=_run_real_search_in_new_group,
        args=([index.path for index in indexes], cache / "terrain", events, measurements,
              times, output, bounds, budget, scoring),
    )
    child.start()
    checkpoints = []
    children = []
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and child.is_alive():
            children_file = Path(f"/proc/{child.pid}/task/{child.pid}/children")
            children = [int(pid) for pid in children_file.read_text().split()] if children_file.exists() else []
            workers = [pid for pid in children if Path(f"/proc/{pid}/cmdline").exists()
                       and b"spawn_main" in Path(f"/proc/{pid}/cmdline").read_bytes()]
            checkpoints = list(output.glob("tile-*.json")) if output.exists() else []
            if workers and checkpoints and os.getpgid(child.pid) == child.pid:
                break
            time.sleep(.05)
        else:
            pytest.fail("parallel search ended or did not checkpoint before interruption")
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
        # If the parent exited unexpectedly, stop only its observed, still
        # matching multiprocessing children; never signal an unrelated group.
        for pid in children:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
                if fields[0] != "Z" and int(fields[2]) == child.pid and b"multiprocessing." in command:
                    os.kill(pid, signal.SIGTERM)
            except (OSError, ValueError, IndexError):
                pass
    interrupted, interrupted_sources = run("interrupted-ocean", 3)
    assert interrupted["tiles_resumed"] >= len(checkpoints)
    assert interrupted["ranked"] == parallel["ranked"] and interrupted["status"] == parallel["status"]
    assert interrupted_sources == parallel_sources
