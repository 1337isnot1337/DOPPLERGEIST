"""Replay recorded empty tiles, comparing ordinary commits with bounded batches.

Supply a restored real flight index. The committed fixture contains 256 actual
completed tiles and their query settings. --search instead replays an existing
search directory against its original index. Every timed path queries the real
data and must reproduce each saved tile.
This measures empty coarse tiles only, not complete search or location accuracy.
"""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import time

from dopplergeist.data_access import FlightIndex, content_hash, sha256, write_json
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.tiled_search import (SearchBudget, _expanded_bounds, _tile_coordinates,
                                      _tracks, grid_tiles, merge_candidates)


def portable_index_identity(report):
    """Preserve every input identity field except the local source file path."""
    keys = ("index_version", "sources", "coverage", "normalizer_sha256",
            "classification_map_hash", "max_gap_s", "max_flight_samples")
    identity = {key: report[key] for key in keys}
    if content_hash(identity) != report["input_hash"]:
        raise ValueError("Flight index input identity is inconsistent")
    identity["sources"] = [{key: value for key, value in source.items() if key != "path"}
                           for source in identity["sources"]]
    return identity


def ledger_contents(ledger):
    with ledger.connect() as db:
        return {table: db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
                for table in ("run", "stages", "records", "bounds")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--search", type=Path,
                        help="Existing real search with completed tile checkpoints and original index")
    inputs.add_argument("--fixture", type=Path,
                        help="Portable recorded-tile fixture; defaults to the committed 256-tile workload")
    parser.add_argument("--index", type=Path, action="append", required=True)
    parser.add_argument("--tiles", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.tiles, args.batch_size, args.passes) <= 0:
        parser.error("tile, batch and pass counts must be positive")
    indexes = [FlightIndex(path) for path in args.index]
    identities = [{"input_hash": index.report["input_hash"], "file_sha256": sha256(index.path)}
                  for index in indexes]
    if args.search:
        manifest = json.loads((args.search / "manifest.json").read_text())
        config, run_hash = manifest["configuration"], manifest["run_hash"]
        if content_hash(config) != run_hash:
            raise ValueError("Saved manifest identity mismatch")
        if identities != config["indexes"]:
            raise ValueError("Indexes differ from the saved real search")
        radius = max(event["slant_range_m"][1] for event in config["events"])
        mode = config["scoring"].get("mode", "brightness")
        score_kind = ("matched_group_support_minus_normalized_residual"
                      if mode == "robust_ridge" and config["filters"]["association"] == "subsets"
                      else {"robust_ridge": "negative_robust_ridge_loss_hz", "ridge": "negative_ridge_rmse_hz",
                            "brightness": "summed_spectral_contrast"}[mode])
        recorded = None
    else:
        args.fixture = args.fixture or Path(__file__).resolve().parents[1] / "tests/data/real-empty-tile-workload.json"
        fixture = json.loads(args.fixture.read_text())
        if fixture["schema_version"] != 1:
            raise ValueError("Unsupported recorded-tile fixture version")
        if [portable_index_identity(index.report) for index in indexes] != fixture["index_inputs"]:
            raise ValueError("Index source bytes or scientific input settings differ from the recorded workload")
        config, run_hash = fixture["query"], fixture["run_hash"]
        radius, score_kind = config["radius_m"], fixture["score_kind"]
        recorded = {}
        for tile in fixture["tiles"]:
            payload = dict(fixture["empty_payload"], cells=tile["cells"])
            if tile["tile_id"] in recorded:
                raise ValueError("Duplicate tile in the recorded workload")
            recorded[tile["tile_id"]] = {"run_hash": run_hash, "payload_hash": tile["payload_hash"],
                                          "payload": payload}
    budget = SearchBudget(**config["budget"])
    bounds, crs = config["bounds"], config["crs"]
    tiles = []
    for tile_id, cells in grid_tiles(bounds, budget.spacing_m, budget.tile_cells, crs):
        if recorded is None:
            path = args.search / f"tile-{tile_id}.json"
            if not path.exists():
                continue
            saved = json.loads(path.read_text())
        else:
            saved = recorded.get(tile_id)
            if saved is None:
                continue
        payload = saved["payload"]
        if (saved["run_hash"] != run_hash or saved["payload_hash"] != content_hash(payload)
                or payload["cells"] != list(cells)):
            raise ValueError(f"Invalid recorded tile: {tile_id}")
        if payload["ranked"] or payload["counts"] or payload["tracks"]:
            continue
        if not len(_tile_coordinates(cells, budget.spacing_m, bounds, crs)):
            continue
        tiles.append((tile_id, cells, saved))
        if len(tiles) == args.tiles:
            break
    if len(tiles) != args.tiles:
        raise ValueError(f"Only {len(tiles)} recorded empty tiles with receiver cells were available")

    args.output.mkdir(parents=True, exist_ok=False)
    expected_contents = None
    results = {"ordinary": [], "batched": []}
    for pass_number in range(args.passes):
        order = ("ordinary", "batched") if pass_number % 2 == 0 else ("batched", "ordinary")
        for name in order:
            output = args.output / f"{name}-{pass_number + 1}"
            output.mkdir()
            ledger = RetentionLedger(output / "retention.sqlite", run_hash, score_kind)
            batch_size = 1 if name == "ordinary" else args.batch_size
            started, cpu_started = time.perf_counter(), time.process_time()
            for first in range(0, len(tiles), batch_size):
                with ledger.batch() if batch_size > 1 else nullcontext():
                    for tile_id, cells, saved in tiles[first:first + batch_size]:
                        points = _tile_coordinates(cells, budget.spacing_m, bounds, crs)
                        tracks = _tracks(indexes, _expanded_bounds(cells, budget.spacing_m, radius, crs),
                                         config["time_range_s"], budget) if len(points) else []
                        if tracks:
                            raise AssertionError(f"Recorded empty tile now has tracks: {tile_id}")
                        stage = f"coarse:{tile_id}"
                        ledger.record(stage, [], [], 0)
                        payload = {"ranked": [], "counts": {}, "grid_points": 0, "tracks": 0,
                                   "cells": list(cells), "terrain_files": [], "terrain_ocean_tiles": [],
                                   "terrain_failures": [], "retention_checksum": ledger.checksum(stage)}
                        checkpoint = {"run_hash": run_hash, "payload_hash": content_hash(payload), "payload": payload}
                        if checkpoint != saved:
                            raise AssertionError(f"Recorded tile changed: {tile_id}")
                        write_json(output / f"tile-{tile_id}.json", checkpoint)
                        merge_candidates([], budget.top_k, ledger=ledger, stage=f"global:{tile_id}")
            results[name].append({"wall_s": time.perf_counter() - started,
                                  "cpu_s": time.process_time() - cpu_started})
            contents = ledger_contents(ledger)
            if expected_contents is None:
                expected_contents = contents
            if contents != expected_contents:
                raise AssertionError("Retention tables changed between runs")
            for tile_id, _, saved in tiles:
                for phase in ("coarse", "global"):
                    if not ledger.stage_valid(f"{phase}:{tile_id}", saved["payload"]["retention_checksum"]):
                        raise AssertionError("Committed stage fails normal resume validation")
    medians = {name: statistics.median(row["wall_s"] for row in rows) for name, rows in results.items()}
    summary = {"scope": "Recorded empty coarse tiles with receiver cells; includes geometry, real index queries, "
                        "coarse/global stages, checksums and checkpoint writes; excludes progress/resume reads",
               "source_search": str(args.search) if args.search else None,
               "source_fixture": str(args.fixture.resolve()) if args.fixture else None,
               "index_identity_check": "original input and file hashes" if args.search else
                                       "all input fields except local source paths",
               "indexes": identities, "tiles": len(tiles),
               "batch_size": args.batch_size, "passes": args.passes,
               "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
               "timings": results, "median_wall_s": medians,
               "speedup": medians["ordinary"] / medians["batched"],
               "all_checkpoints_match_recorded_tiles": True, "all_ledger_tables_match": True,
               "all_committed_stages_valid": True, "stage_count": len(expected_contents["stages"])}
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
