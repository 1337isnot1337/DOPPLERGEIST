"""Prepare a separately named real flight index for repeated search queries.

The copy retains observations, coverage and input identity. It adds validated
numeric track inputs and keeps the original JSON for older readers and later
normalization changes. No trajectories are generated.
"""
import argparse
import json
from pathlib import Path
import time

from dopplergeist.data_access import FlightIndex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    began = time.perf_counter()
    result = FlightIndex(args.index).prepare(args.output)
    print(json.dumps({"output": str(args.output.resolve()),
                      "elapsed_s": time.perf_counter() - began,
                      "source_bytes": args.index.stat().st_size,
                      "prepared_bytes": args.output.stat().st_size,
                      "input_hash": result.report["input_hash"],
                      "prepared_tracks": result.report["prepared_tracks"]}, indent=2))


if __name__ == "__main__":
    main()
