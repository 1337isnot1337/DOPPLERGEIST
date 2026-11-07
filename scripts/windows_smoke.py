"""Exercise platform services without starting an analysis or generating audio."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
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
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, '-c',
                               'from dopplergeist.cli import main; main()',
                               'serve', '--jobs', str(root / 'service-jobs'), '--port', str(port)],
                              start_new_session=(os.name != 'nt'),
                              creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    try:
        for attempt in range(100):
            if server.poll() is not None:
                raise AssertionError(f'Service exited: {server.returncode}')
            try:
                with urlopen(f'http://127.0.0.1:{port}/', timeout=1) as response:
                    assert response.status == 200
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError('Service did not start')
    finally:
        JobManager._stop(server)
print('Platform smoke checks passed')
