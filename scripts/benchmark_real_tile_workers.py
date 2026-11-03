"""Compare serial and parallel workers on two points from a real saved job.

The selected points and clocks are search hypotheses, not location truth. This
replays recorded audio and historical tracks; it does not create new data or
establish nationwide runtime or accuracy.
"""
import argparse
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import tempfile
import time

from dopplergeist.data_access import FlightIndex, content_hash
from dopplergeist.finite_search import RetentionLedger
from dopplergeist.matching import prepare_events
from dopplergeist.parallel_retention import import_retention_stage
from dopplergeist.parallel_tiles import initialize_tile_worker, ordered_tile_results, score_tile
from dopplergeist.tiled_search import SearchBudget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path, help="Saved job directory")
    parser.add_argument("cache", type=Path, help="That job's provider cache")
    parser.add_argument("tiles", nargs=2, help="Two completed tile IDs with ranked candidates")
    parser.add_argument("output", type=Path, help="New JSON report path")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new output file to preserve previous measurements")
    search = args.job / "search"
    manifest = json.loads((search / "manifest.json").read_text())
    config = manifest["configuration"]
    events, measurements = prepare_events(json.loads((args.job / "discovery/discovery.json").read_text())["events"])
    if content_hash(events) != content_hash(config["events"]):
        raise ValueError("Discovery events do not match the saved search")
    available = {FlightIndex(path).report["input_hash"]: path
                 for path in (args.cache / "flights").glob("*/staging-0/*.sqlite")}
    paths = [available[item["input_hash"]] for item in config["indexes"]]
    budget = SearchBudget(**config["budget"])
    rows = [json.loads((search / f"tile-{tile}.json").read_text())["payload"]["ranked"][0]
            for tile in args.tiles]
    cells = []
    for row in rows:
        x, y = round(row["x"] / budget.spacing_m), round(row["y"] / budget.spacing_m)
        cells.append((x, y, x+1, y+1))
    stages = [f"coarse:worker-replay-{i}" for i in range(len(cells))]
    parameters = dict(config["scoring"])
    start_window = parameters.pop("recording_start_window_s", None)
    identity = content_hash({"source_run": manifest["run_hash"], "worker_replay_tiles": args.tiles})
    score_kind = "matched_group_support_minus_normalized_residual"
    with tempfile.TemporaryDirectory(prefix="doppler-real-workers-") as directory:
        temporary = Path(directory)
        initargs = (paths, args.cache / "terrain", {"offline": True}, events, measurements,
                    config["bounds"], config["time_range_s"], budget, parameters, config["filters"],
                    start_window, config["crs"], temporary / "workers", identity, score_kind)
        initialize_tile_worker(*initargs)
        serial_ledger = RetentionLedger(temporary / "serial.sqlite", identity, score_kind)
        started = time.perf_counter()
        serial = []
        for stage, cell in zip(stages, cells):
            payload, path = score_tile(stage, cell)
            import_retention_stage(serial_ledger, path, stage, payload["retention_checksum"])
            Path(path).unlink()
            serial.append(payload)
        serial_s = time.perf_counter() - started
        parallel_ledger = RetentionLedger(temporary / "parallel.sqlite", identity, score_kind)
        parallel = []

        def finish(stage, cell, future):
            payload, path = future.result()
            import_retention_stage(parallel_ledger, path, stage, payload["retention_checksum"])
            Path(path).unlink()
            return payload

        started = time.perf_counter()
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn"),
                                 initializer=initialize_tile_worker, initargs=initargs) as pool:
            jobs = [(stage, cell, None, None) for stage, cell in zip(stages, cells)]
            for stage, cell, payload, cached in ordered_tile_results(pool, jobs, 2, finish):
                if cached:
                    raise RuntimeError("Unexpected cached tile in worker benchmark")
                parallel.append(payload)
        parallel_s = time.perf_counter() - started
        same = (json.dumps(serial, sort_keys=True, allow_nan=True)
                == json.dumps(parallel, sort_keys=True, allow_nan=True))
        report = {"source_run_hash": manifest["run_hash"], "tile_ids": args.tiles,
                  "serial_wall_s": serial_s, "parallel_wall_s_including_startup": parallel_s,
                  "same_payloads_and_ledgers": same,
                  "candidates": [p["counts"].get("candidates", 0) for p in serial],
                  "clock_trials": [sum(p["counts"].get(k, 0) for k in
                                       ("evaluated_trials", "rejected_trials", "unknown_trials")) for p in serial]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as output:
            json.dump(report, output, indent=2, allow_nan=False)
            output.write("\n")
        if not same:
            raise AssertionError("Serial and parallel worker payloads differed")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
