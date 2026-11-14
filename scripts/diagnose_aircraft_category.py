#!/usr/bin/env python3
"""Run optional category inference on saved discovery and its original recording."""
import argparse
import json
from pathlib import Path
import subprocess

from dopplergeist.aircraft_category import diagnose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path,
                        help="Trusted local joblib bundle; loading it executes serialized code")
    parser.add_argument("--output", required=True, type=Path, help="New report file; existing files are refused")
    parser.add_argument("--max-windows", type=int, default=1024)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new report file")
    try:
        discovery = json.loads(args.discovery.read_text())
        if not isinstance(discovery, dict):
            raise ValueError("Discovery must be a JSON object")
        report = diagnose(discovery, args.audio, args.model, max_windows=args.max_windows)
        with args.output.open("x") as output:
            output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, KeyError, ImportError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Category diagnostic failed: {error}\n")
    print(f"Wrote {len(report['events'])} separate category diagnostics to {args.output}")
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
