"""Prepare the restored reference recording's automatic development replay.

The regional flight data are incomplete, and the clock interval comes from a
historical fit. This replay does not establish independent location acceptance.
Restore the reference ADS-B and terrain bundles before running this helper.
"""
import argparse
import json
from pathlib import Path
import time


def save(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Restored data directory containing adsb/ and terrain/")
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory for the index, report, operator and request")
    args = parser.parse_args()
    data = args.data_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    parquet = data / "adsb/2026-09-08/reference-region.parquet"
    dem = data / "terrain/Copernicus_DSM_COG_10_N40_00_W074_00_DEM.tif"
    geoid = data / "terrain/us_nga_egm96_15.tif"
    if output.exists():
        parser.error(f"Output already exists; choose a new directory: {output}")
    for path in (parquet, dem, geoid):
        if not path.is_file():
            parser.error(f"Required restored input is missing: {path}")

    from dopplergeist.data_access import FlightIndex

    output.mkdir(parents=True, exist_ok=False)
    coverage = {
        "bounds": [-74.299988, 40.100005, -72.700011, 41.599964],
        "time_range_s": [1788825600.17, 1788911999.6],
        "all_aircraft": False,
        "source_note": (
            "Restored historical reference-region.parquet. The listed bounds and "
            "times are observed sample extrema, not established selection coverage. "
            "Original geographic selection bounds are unknown. The original ingestion "
            "excluded known jets. This index cannot establish complete coverage."
        ),
        "selection_bounds_known": False,
        "extent_kind": "observed_sample_extrema_only",
    }
    began = time.monotonic()
    index = FlightIndex.from_parquet(output / "reference-region.sqlite", parquet, coverage=coverage)
    save(output / "index-report.json", dict(index.report, elapsed_s=time.monotonic() - began))
    operator = {
        "flight_indexes": [str(index.path.resolve())],
        "offline": True,
        "terrain": {"rasters": [str(dem)], "geoid_raster": str(geoid)},
        "search_budget": {
            "spacing_m": 2000,
            "tile_cells": 16,
            "top_k": 20,
            "refine_spacing_m": 500,
            "refine_finalists": 3,
        },
        "refine_finalists": 3,
    }
    request = {
        "schema_version": 1,
        "search": {"coverage": "conus"},
        "time_window": {
            "start_utc": "2026-09-08T20:17:20Z",
            "end_utc": "2026-09-08T20:17:40Z",
            "source": "user",
            "source_detail": (
                "Source-informed development replay interval around historical fitted "
                "sample-zero 2026-09-08T20:17:29.662Z from "
                "evidence/results/reference-local-fast/report.json. "
                "This is not an independently measured recording clock."
            ),
        },
    }
    save(output / "operator.json", operator)
    save(output / "request.json", request)
    print(json.dumps({
        "index": str(index.path),
        "rows": index.report["rows"],
        "segments": index.report["segments"],
        "operator": str(output / "operator.json"),
        "request": str(output / "request.json"),
        "source_coverage_complete": False,
        "validation_scope": "Source-informed development replay; not independent acceptance",
        "elapsed_s": time.monotonic() - began,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
