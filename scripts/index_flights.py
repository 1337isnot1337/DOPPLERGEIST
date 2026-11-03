"""Build/reuse a provenance-labelled index from an operator-supplied Parquet.

Normal uploads use FlightCache acquisition. This adapter restores checkpoint
data without re-downloading a daily archive and records its actual limitations.
"""
import argparse
import json
import resource
import time

from dopplergeist.data_access import FlightIndex, write_json
from dopplergeist.tracks import unix_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet")
    parser.add_argument("index")
    parser.add_argument("--bounds", type=float, nargs=4, required=True)
    parser.add_argument("--time-range", nargs=2, required=True, metavar=("START_UTC", "END_UTC"))
    parser.add_argument("--all-aircraft", action="store_true", help="Only if source ingestion retained all classes")
    parser.add_argument("--source-note", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    began = time.monotonic()
    coverage = {"bounds": args.bounds, "time_range_s": [unix_time(t) for t in args.time_range],
                "all_aircraft": args.all_aircraft, "source_note": args.source_note}
    index = FlightIndex.from_parquet(args.index, args.parquet, coverage=coverage)
    report = dict(index.report, index_path=str(index.path), elapsed_s=time.monotonic() - began,
                  process_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
