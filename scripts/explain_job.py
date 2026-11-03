#!/usr/bin/env python3
"""Print evidence-based next steps for an existing local job."""
import argparse
import json
from pathlib import Path

from dopplergeist.contracts import validate_result
from dopplergeist.guidance import guidance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dir", type=Path, help="directory containing result.json")
    args = parser.parse_args()
    result = validate_result(json.loads((args.job_dir / "result.json").read_text()))
    decision_path = args.job_dir / "decision.json"
    decision = json.loads(decision_path.read_text()) if decision_path.is_file() else None
    print(json.dumps(guidance(result, decision), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
