"""Reproduce inherited RSS high-water marks without audio fixtures."""
import json
import subprocess
import sys

import pytest


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux VmHWM regression")
def test_child_reports_its_own_post_exec_high_water():
    child = r'''
import json, resource
from dopplergeist.resource_usage import process_peak_rss_kib
measured = process_peak_rss_kib()
with open('/proc/self/status') as f:
    actual = int(next(line for line in f if line.startswith('VmHWM:')).split()[1])
print(json.dumps({'reported': measured, 'vmhwm': actual,
                  'getrusage': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))
'''
    parent = r'''
import subprocess, sys
allocation = bytearray(160 * 1024 * 1024)
allocation[0] = 1
result = subprocess.check_output([sys.executable, '-c', sys.argv[1]], text=True)
print(result, end='')
'''
    result = subprocess.run([sys.executable, "-c", parent, child], check=True,
                            capture_output=True, text=True)
    observed = json.loads(result.stdout)
    assert abs(observed["vmhwm"] - observed["reported"]) <= 1024
