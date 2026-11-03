"""Run a fresh bounded HTTP workflow with explicit real-recording inputs.

The input directory must contain recording.mp3, request.json, and operator.json.
Pass the src directory of a pinned source checkout and a new output directory
for each arm. The fixed archived receiver bounds are source-informed and do not
establish independent location accuracy. No observations or fixtures are generated.
"""
import argparse
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--inputs", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--timeout-s", type=float, default=900.0)
args = parser.parse_args()
source = args.source.resolve()
sys.path[:0] = [str(source), str(source.parent / "scripts")]

import dopplergeist
from verify_upload_http import verify_http

if Path(dopplergeist.__file__).resolve().parent != source / "dopplergeist":
    raise RuntimeError("Verifier imported a different source tree")
request = json.loads((args.inputs / "request.json").read_text())
operator = json.loads((args.inputs / "operator.json").read_text())
if request.get("search", {}).get("bounds_wsen") != [-73.545, 40.865, -73.505, 40.895]:
    raise ValueError("This benchmark requires the archived four-point receiver bounds")
receipt = verify_http(args.inputs / "recording.mp3", args.output,
    request=request, operator=operator, expect_status="inconclusive",
    expect_reason="search_incomplete", timeout_s=args.timeout_s,
    poll_interval_s=1.0, require_full_pipeline=True)
print(json.dumps({key: receipt.get(key) for key in
    ("verification_passed", "status", "reason_code", "full_pipeline_observed",
     "full_pipeline_requirements_met", "elapsed_s", "job_id")}))
raise SystemExit(0 if receipt["verification_passed"] else 1)
