"""Replay refinement and decision from an existing recorded-audio job.

The job must have a saved search result, prebuilt flight indexes, and local
terrain files. All referenced inputs must remain available. No audio or aircraft
observations are generated, and no data are downloaded. Timing excludes imports,
input preparation, and output comparison. This is a phase benchmark, not a new
search or an independent location-accuracy evaluation.

Run once with a baseline source tree, then use --compare-to on the second run
to compare every refined candidate, sensitivity result, and decision exactly.
Use a new output directory for each run and alternate source order for repeats.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


def read_json(path):
    return json.loads(Path(path).read_text())


def write_new(path, value):
    with Path(path).open("x") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")


def compare_outputs(actual, reference):
    """Ignore object-key order; require exact scalar values and array order."""
    names = ["refined-candidates.json", "decision.json", "result.json"]
    if any((Path(folder) / "spectral-comparison.json").exists() for folder in (actual, reference)):
        names.append("spectral-comparison.json")
    mismatches = []
    for name in names:
        paths = [Path(folder) / name for folder in (actual, reference)]
        if not all(path.is_file() for path in paths):
            mismatches.append(name)
            continue
        values = [json.dumps(read_json(path), sort_keys=True, separators=(",", ":")) for path in paths]
        if values[0] != values[1]:
            mismatches.append(name)
    return {"reference": str(Path(reference).resolve()), "artifacts": names,
            "equal": not mismatches, "mismatches": mismatches}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Source directory containing the dopplergeist package")
    parser.add_argument("--job", type=Path, required=True,
                        help="Existing real job directory with saved search and input metadata")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--compare-to", type=Path,
                        help="Previous replay directory; fail if any result artifact differs")
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(f"Choose a new output directory: {args.output}")
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[variable] = "1"
    source = args.source.resolve()
    sys.path.insert(0, str(source))

    import dopplergeist
    from dopplergeist import automatic
    from dopplergeist.contracts import validate_event
    from dopplergeist.data_access import FlightIndex
    from dopplergeist.intake import IntakeRecording
    from dopplergeist.matching import prepare_events
    from dopplergeist.resource_usage import process_peak_rss_kib
    from dopplergeist.terrain import Terrain

    if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
        raise RuntimeError("Replay imported a different source tree")
    config = read_json(args.job / "operator.json")
    search = read_json(args.job / "search/search-report.json")
    ground = config.get("terrain", {})
    if not config.get("flight_indexes") or not (ground.get("rasters") or "constant_m" in ground):
        raise ValueError("Replay requires explicit flight_indexes and local terrain in operator.json")
    if not search.get("ranked"):
        raise ValueError("The recorded search result contains no finalists to refine")
    events = [validate_event(event) for event in read_json(args.job / "discovery/discovery.json")["events"]]
    prepared, measurements = prepare_events(
        events, c=config.get("sound_speed_mps", 343.0),
        max_distance_m=config.get("max_distance_m", 20000.0))
    indexes = [FlightIndex(path) for path in config["flight_indexes"]]
    terrain = Terrain(ground.get("rasters"), constant_m=ground.get("constant_m"),
                      geoid_path=ground.get("geoid_raster"))
    recording = IntakeRecording(args.job / "intake/recording.f32",
                                read_json(args.job / "intake/recording.json"),
                                read_json(args.job / "intake/intake.json"))
    state = {"recording": recording.metadata,
             "coverage": automatic._coverage(read_json(args.job / "request.json"), search, config)}
    args.output.mkdir(parents=True, exist_ok=False)

    def finish(status, reason, message, **fields):
        return dict(status=status, reason_code=reason, message=message, **fields)

    start, cpu_start = time.perf_counter(), time.process_time()
    result = automatic._decide(
        search, events, prepared, measurements, indexes, terrain, state,
        args.output, config, finish, lambda *_args, **_kwargs: None, recording=recording)
    elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu_start
    summary = {
        "wall_seconds": elapsed, "cpu_seconds": cpu,
        "process_peak_rss_mib": process_peak_rss_kib() / 1024,
        "source": str(source), "job": str(args.job.resolve()),
        "numerical_library_threads": 1,
        "ridge_records": len(events), "independent_groups": len(prepared),
        "search_finalists": len(search["ranked"]),
        "refinement_limit": config.get("refine_finalists", 5),
        "returned_candidates": len(result.get("candidates", [])),
        "status": result["status"], "reason_code": result["reason_code"],
        "scope": "Refinement/decision from frozen recorded-audio finalists; no search or accuracy measurement",
    }
    write_new(args.output / "result.json", result)
    if args.compare_to is not None:
        summary["comparison"] = compare_outputs(args.output, args.compare_to)
    write_new(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    if args.compare_to is not None and not summary["comparison"]["equal"]:
        raise SystemExit("Decision replay differs: " + ", ".join(summary["comparison"]["mismatches"]))


if __name__ == "__main__":
    main()
