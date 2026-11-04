#!/usr/bin/env python3
"""Submit a public recording to the real local HTTP pipeline with regional priors."""
import argparse
import json
from pathlib import Path

from verify_upload_http import verify_http

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--audio', type=Path, required=True)
parser.add_argument('--operator-config', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--start-utc', required=True)
parser.add_argument('--end-utc', required=True)
parser.add_argument('--bounds', type=float, nargs=4, metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'), required=True)
parser.add_argument('--timeout-s', type=float, default=3600)
args = parser.parse_args()
request = {
    'schema_version': 1,
    'time_window': {'start_utc': args.start_utc, 'end_utc': args.end_utc, 'source': 'user',
                    'source_detail': 'Publisher filename UTC with an assumed clock margin; site-specific clock error unverified.'},
    'search': {'coverage': 'conus', 'bounds_wsen': args.bounds},
}
operator = json.loads(args.operator_config.read_text())
receipt = verify_http(args.audio, args.output, request=request, operator=operator,
                      expect_status='inconclusive', timeout_s=args.timeout_s,
                      require_full_pipeline=False)
print(json.dumps({key: receipt.get(key) for key in ('verification_passed', 'status',
      'reason_code', 'full_pipeline_observed', 'full_pipeline_requirements_met', 'job_id', 'error')}))
