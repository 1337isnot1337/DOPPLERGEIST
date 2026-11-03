"""Compare empty parallel-worker handoffs using recorded real tile queries.

Both paths query the same historical aircraft index and must reproduce every
recorded tile payload. The original worker writes a private SQLite ledger; the
current worker returns a verified empty descriptor. Both import into a durable
parent ledger before writing the same checkpoint. No scoring or localization
claim is made by this empty-work benchmark.
"""
import argparse
from contextlib import contextmanager
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time

from dopplergeist.data_access import DataUnavailable, FlightIndex, content_hash, write_json
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.parallel_retention import EmptyRetentionStage, import_retention_stage
from dopplergeist import parallel_tiles
from dopplergeist.tiled_search import SearchBudget, merge_candidates


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _contents(ledger):
    with sqlite3.connect(ledger.path) as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                for table in ("run", "stages", "records", "bounds")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True,
                        help="Recorded real-empty-tile-workload.json from the repository")
    parser.add_argument("--events", type=Path, required=True,
                        help="Recorded event JSON; only the search radius is used for empty queries")
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline checkout")
    parser.add_argument("--terrain-root", type=Path, required=True, help="Verified existing terrain cache")
    parser.add_argument("--geoid", type=Path, help="Existing verified geoid raster; no terrain is sampled")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--tiles", type=int, default=256)
    args = parser.parse_args()
    if min(args.passes, args.tiles) < 1:
        parser.error("Pass and tile counts must be positive")
    fixture = json.loads(args.fixture.read_text())
    config = fixture["query"]
    index = FlightIndex(args.index)
    expected_inputs = fixture["index_inputs"]
    if len(expected_inputs) != 1:
        raise ValueError("This benchmark requires the recorded single-index workload")
    actual_inputs = {key: index.report[key] for key in expected_inputs[0]}
    actual_inputs["sources"] = [{key: value for key, value in row.items() if key != "path"}
                                for row in actual_inputs["sources"]]
    if actual_inputs != expected_inputs[0]:
        raise ValueError("Real index source bytes or scientific settings differ from the recorded workload")
    events = json.loads(args.events.read_text())["events"]
    if max(event["slant_range_m"][1] for event in events) != config["radius_m"]:
        raise ValueError("Recorded event radius differs from the empty-tile workload")
    tiles = fixture["tiles"][:args.tiles]
    if len(tiles) != args.tiles:
        raise ValueError("Insufficient recorded tiles")
    baseline = _module(args.baseline / "src/dopplergeist/parallel_tiles.py",
                       "dopplergeist._baseline_empty_workers")
    baseline_retention = _module(args.baseline / "src/dopplergeist/parallel_retention.py",
                                 "dopplergeist._baseline_empty_retention")
    args.output.mkdir(parents=True, exist_ok=False)
    budget = SearchBudget(**config["budget"])
    run_hash, score_kind = fixture["run_hash"], fixture["score_kind"]
    implementations = {"baseline": (baseline, baseline_retention.import_retention_stage),
                       "current": (parallel_tiles, import_retention_stage)}
    results = {name: [] for name in implementations}
    reference_contents = None
    last_ledger = last_descriptor = None
    for trial in range(args.passes):
        for name in (("baseline", "current") if trial % 2 == 0 else ("current", "baseline")):
            implementation, import_stage = implementations[name]
            output = args.output / f"{name}-{trial + 1}"
            output.mkdir()
            implementation.initialize_tile_worker(
                [args.index], args.terrain_root, {"offline": True, "geoid_path": args.geoid}, events, [],
                config["bounds"], config["time_range_s"], budget, {}, {}, None,
                config["crs"], output / "workers", run_hash, score_kind)
            ledger = RetentionLedger(output / "retention.sqlite", run_hash, score_kind)
            wall, cpu = time.perf_counter(), time.process_time()
            file_count = 0
            for tile in tiles:
                stage, cells = "coarse:" + tile["tile_id"], tuple(tile["cells"])
                payload, worker = implementation.score_tile(stage, cells)
                expected = dict(fixture["empty_payload"], cells=list(cells))
                if content_hash(expected) != tile["payload_hash"] or payload != expected:
                    raise AssertionError("Real empty tile payload changed")
                import_stage(ledger, worker, stage, payload["retention_checksum"])
                write_json(output / ("tile-" + tile["tile_id"] + ".json"),
                           {"run_hash": run_hash, "payload_hash": tile["payload_hash"], "payload": payload})
                if isinstance(worker, EmptyRetentionStage):
                    last_descriptor = worker
                else:
                    file_count += 1
                    Path(worker).unlink()
                merge_candidates([], budget.top_k, ledger=ledger, stage="global:" + tile["tile_id"])
            timing = {"wall_s": time.perf_counter() - wall, "cpu_s": time.process_time() - cpu,
                      "worker_sqlite_files": file_count}
            results[name].append(timing)
            contents = _contents(ledger)
            if reference_contents is None:
                reference_contents = contents
            if contents != reference_contents:
                raise AssertionError("Parent retention ledger differs")
            for tile in tiles:
                for phase in ("coarse:", "global:"):
                    if not ledger.stage_valid(phase + tile["tile_id"], fixture["empty_payload"]["retention_checksum"]):
                        raise AssertionError("Imported stage fails normal resume validation")
            if name == "current":
                last_ledger = ledger
            print(json.dumps({"implementation": name, "pass": trial + 1, **timing}), flush=True)
    # Rejected descriptors must not modify previously committed evidence.
    before = _contents(last_ledger)
    for damaged in (replace(last_descriptor, run_hash=last_descriptor.run_hash + "0"),
                    replace(last_descriptor, score_kind=last_descriptor.score_kind + "0"),
                    replace(last_descriptor, stage=last_descriptor.stage + "0"),
                    replace(last_descriptor, checksum=last_descriptor.checksum + "0")):
        try:
            import_retention_stage(last_ledger, damaged, last_descriptor.stage, last_descriptor.checksum)
        except DataUnavailable:
            pass
        else:
            raise AssertionError("Invalid empty stage descriptor was accepted")
        if _contents(last_ledger) != before:
            raise AssertionError("Invalid descriptor changed parent evidence")
    # Repeated delivery replaces the same stage instead of inflating counts.
    import_retention_stage(last_ledger, last_descriptor, last_descriptor.stage, last_descriptor.checksum)
    if _contents(last_ledger) != before:
        raise AssertionError("Repeated descriptor import changed evidence")
    # Storage errors must stay recoverable tile failures, as on the file path.
    @contextmanager
    def read_only_connection():
        with sqlite3.connect(last_ledger.path) as db:
            db.execute("PRAGMA query_only=ON")
            yield db
    ordinary_connect = last_ledger.connect
    last_ledger.connect = read_only_connection
    try:
        try:
            import_retention_stage(last_ledger, last_descriptor, last_descriptor.stage, last_descriptor.checksum)
        except DataUnavailable:
            pass
        else:
            raise AssertionError("Read-only ledger unexpectedly accepted an import")
    finally:
        last_ledger.connect = ordinary_connect
    if _contents(last_ledger) != before:
        raise AssertionError("Failed import changed parent evidence")
    medians = {name: {kind: statistics.median(row[kind] for row in runs)
                     for kind in ("wall_s", "cpu_s")} for name, runs in results.items()}
    report = {"scope": "Recorded empty worker tiles, parent imports, global merges and checkpoint writes; "
                       "excludes process startup, populated tiles and localization",
              "index_sources": expected_inputs[0]["sources"], "tiles": len(tiles), "passes": args.passes,
              "timings": results, "medians": medians,
              "wall_speedup": medians["baseline"]["wall_s"] / medians["current"]["wall_s"],
              "cpu_speedup": medians["baseline"]["cpu_s"] / medians["current"]["cpu_s"],
              "all_recorded_payloads_match": True, "all_parent_tables_match": True,
              "all_stages_pass_resume_validation": True,
              "invalid_descriptor_rejected_without_mutation": True,
              "duplicate_delivery_is_idempotent": True,
              "storage_failure_remains_data_unavailable": True}
    write_json(args.output / "summary.json", report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
