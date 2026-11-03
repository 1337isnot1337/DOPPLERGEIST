"""Verify worker-ledger imports using an actual running search's evidence."""
import os
from pathlib import Path
import sqlite3

import pytest

from dopplergeist.data_access import DataUnavailable
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.parallel_retention import import_retention_stage


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
