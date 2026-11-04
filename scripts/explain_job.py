#!/usr/bin/env python3
"""Print evidence-based next steps for an existing local job without changing it."""
import argparse
import json
from pathlib import Path

from dopplergeist.guidance import explain_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dir", type=Path, help="directory containing result.json")
    args = parser.parse_args()
    print(json.dumps(explain_job(args.job_dir), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
