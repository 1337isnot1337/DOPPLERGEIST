"""Empty-worker transport controls using saved real checkpoints and ADS-B rows.

The aircraft excerpt is incomplete. These checks test transaction and worker
behavior; they do not establish flight absence, coverage, or location accuracy.
"""
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from dopplergeist import parallel_tiles
from dopplergeist.data_access import DataUnavailable, FlightIndex
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.parallel_retention import (
    EmptyRetentionStage, discard_retention_stage, import_retention_stage)
from dopplergeist.tiled_search import SearchBudget


ROOT = Path(__file__).resolve().parents[1]


def saved_empty_tiles():
    return json.loads((ROOT / "tests/data/reference-empty-tiles-real.json").read_text())


def table_rows(ledger):
    with sqlite3.connect(ledger.path) as db:
        return {name: db.execute(f"SELECT * FROM {name} ORDER BY 1,2").fetchall()
                for name in ("run", "stages", "records", "bounds")}


def recorded_descriptor(tile, score_kind):
    checkpoint = tile["checkpoint"]
    return EmptyRetentionStage(checkpoint["run_hash"], score_kind,
                               "coarse:" + tile["tile_id"],
                               checkpoint["payload"]["retention_checksum"])


def test_recorded_empty_descriptors_match_file_imports_and_resume(tmp_path):
    fixture = saved_empty_tiles()
    run_hash = fixture["tiles"][0]["checkpoint"]["run_hash"]
    score_kind = fixture["score_kind"]
    files = RetentionLedger(tmp_path / "files.sqlite", run_hash, score_kind)
    descriptors = RetentionLedger(tmp_path / "descriptors.sqlite", run_hash, score_kind)
    for number, tile in enumerate(fixture["tiles"]):
        descriptor = recorded_descriptor(tile, score_kind)
        worker = RetentionLedger(tmp_path / f"worker-{number}.sqlite", run_hash, score_kind)
        assert worker.record(descriptor.stage, [], [], 0) == descriptor.checksum
        import_retention_stage(files, worker.path, descriptor.stage, descriptor.checksum)
        import_retention_stage(descriptors, descriptor, descriptor.stage, descriptor.checksum)
        assert descriptors.stage_valid(descriptor.stage, descriptor.checksum)
        discard_retention_stage(worker.path)
        discard_retention_stage(descriptor)
        assert not worker.path.exists()
    assert table_rows(files) == table_rows(descriptors)
    before = table_rows(descriptors)
    for tile in fixture["tiles"]:
        descriptor = recorded_descriptor(tile, score_kind)
        import_retention_stage(descriptors, descriptor, descriptor.stage, descriptor.checksum)
    assert table_rows(descriptors) == before


@pytest.mark.parametrize("field", ["run_hash", "score_kind", "stage", "checksum", "expected_checksum"])
def test_recorded_empty_descriptor_identity_rejects_without_mutation(tmp_path, field):
    fixture = saved_empty_tiles()
    descriptor = recorded_descriptor(fixture["tiles"][0], fixture["score_kind"])
    ledger = RetentionLedger(tmp_path / "parent.sqlite", descriptor.run_hash, descriptor.score_kind)
    import_retention_stage(ledger, descriptor, descriptor.stage, descriptor.checksum)
    before = table_rows(ledger)
    damaged = (descriptor if field == "expected_checksum" else
               replace(descriptor, **{field: getattr(descriptor, field) + "invalid"}))
    checksum = descriptor.checksum + "invalid" if field == "expected_checksum" else descriptor.checksum
    with pytest.raises(DataUnavailable, match="identity/checksum mismatch"):
        import_retention_stage(ledger, damaged, descriptor.stage, checksum)
    assert table_rows(ledger) == before


def test_recorded_empty_import_reports_storage_failure_without_mutation(tmp_path, monkeypatch):
    fixture = saved_empty_tiles()
    descriptor = recorded_descriptor(fixture["tiles"][0], fixture["score_kind"])
    ledger = RetentionLedger(tmp_path / "parent.sqlite", descriptor.run_hash, descriptor.score_kind)
    import_retention_stage(ledger, descriptor, descriptor.stage, descriptor.checksum)
    before = table_rows(ledger)

    @contextmanager
    def read_only_connection():
        with sqlite3.connect(ledger.path) as db:
            db.execute("PRAGMA query_only=ON")
            yield db

    monkeypatch.setattr(ledger, "connect", read_only_connection)
    with pytest.raises(DataUnavailable, match="Cannot import empty worker retention stage"):
        import_retention_stage(ledger, descriptor, descriptor.stage, descriptor.checksum)
    assert table_rows(ledger) == before


class UnsampledTerrain:
    """An empty query must not request any terrain values."""

    def __init__(self):
        self._tile_cache = {}

    def sample(self, *args, **kwargs):
        raise AssertionError("No terrain may be sampled for these observed empty queries")


def initialize_recorded_empty_worker(index_path, directory):
    fixture = json.loads((ROOT / "tests/data/real-empty-tile-workload.json").read_text())
    query = fixture["query"]
    events = json.loads((ROOT / "tests/data/reference-cpa-real.json").read_text())["events"]
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # All numerical inputs are archived observations/search settings. The terrain
    # sentinel supplies no elevations and fails if the empty path requests them.
    parallel_tiles._worker = {
        "indexes": [FlightIndex(index_path)], "terrain": UnsampledTerrain(),
        "events": events, "measurements": [], "bounds": query["bounds"],
        "time_range": query["time_range_s"], "budget": SearchBudget(**query["budget"]),
        "parameters": {}, "filters": {}, "start_window": None, "crs": query["crs"],
        "ledger_directory": directory, "run_hash": fixture["run_hash"],
        "score_kind": fixture["score_kind"],
    }


@pytest.fixture
def observed_index(tmp_path):
    source = ROOT / "research/trajectory-motion/frozen/canonical-observations.json"
    frame = pd.DataFrame(json.loads(source.read_text()))
    frame = frame.loc[frame.typecode.isin(["C172", "H500"])].copy()
    coverage = {"bounds": [-180., -90., 180., 90.],
                "time_range_s": [float(frame.time_s.min()), float(frame.time_s.max())],
                "all_aircraft": False, "source_note": "Archived real observations; incomplete excerpt"}
    index = FlightIndex.build(tmp_path / "observed.sqlite", [frame], sources=[], coverage=coverage)
    assert index.report["segments"] > 0
    return index


def test_recorded_empty_workers_preserve_payloads_and_order_across_processes(
        observed_index, tmp_path, monkeypatch):
    fixture = saved_empty_tiles()
    monkeypatch.setattr(parallel_tiles, "_worker", None)
    directory = tmp_path / "workers"
    initialize_recorded_empty_worker(observed_index.path, directory)
    serial = []
    tasks = [("coarse:" + tile["tile_id"], tuple(tile["checkpoint"]["payload"]["cells"]))
             for tile in fixture["tiles"]]
    for tile, task in zip(fixture["tiles"], tasks):
        payload, descriptor, cache_keys = parallel_tiles.score_tile_with_cache_state(*task)
        assert payload == tile["checkpoint"]["payload"]
        assert descriptor == recorded_descriptor(tile, fixture["score_kind"])
        assert cache_keys == ()
        serial.append((payload, descriptor))
    assert not list(directory.iterdir())

    parallel = []
    parent = RetentionLedger(tmp_path / "parent.sqlite", serial[0][1].run_hash, fixture["score_kind"])

    def finish(stage, cells, future):
        payload, descriptor = future.result()
        import_retention_stage(parent, descriptor, stage, payload["retention_checksum"])
        discard_retention_stage(descriptor)
        return payload, descriptor

    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_recorded_empty_worker,
                             initargs=(observed_index.path, directory)) as pool:
        jobs = [(stage, cells, None, None) for stage, cells in tasks]
        for stage, cells, result, cached in parallel_tiles.ordered_tile_results(pool, jobs, 2, finish):
            assert not cached
            assert (stage, cells) == tasks[len(parallel)]
            assert parent.stage_valid(stage, result[0]["retention_checksum"])
            parallel.append(result)
    assert parallel == serial
    assert not list(directory.iterdir())
