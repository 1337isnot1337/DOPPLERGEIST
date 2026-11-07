"""Exercise platform services without starting an analysis or generating audio."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from dopplergeist.data_access import cache_lock
from dopplergeist.jobs import JobManager
from dopplergeist.resource_usage import process_peak_rss_kib
import dopplergeist.tiled_search  # noqa: F401

with tempfile.TemporaryDirectory() as root:
    root = Path(root)
    with cache_lock(root / 'cache.lock'):
        pass
    manager = JobManager(root / 'jobs')
    try:
        try:
            JobManager(root / 'jobs')
        except ValueError:
            pass
        else:
            raise AssertionError('second job manager acquired the same lock')
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                   start_new_session=(os.name != 'nt'),
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        JobManager._stop(process)
        assert process.poll() is not None
    finally:
        manager.close()
    manager = JobManager(root / 'jobs')
    manager.close()
    assert process_peak_rss_kib() > 0
print('Platform smoke checks passed')
