"""CLI monitoring against an existing real upload job, without cancelling it."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


def test_watch_real_job_and_interrupt_only_the_watcher():
    source = os.environ.get('DOPPLERGEIST_REAL_JOB_ROOT')
    if not source:
        pytest.skip('set DOPPLERGEIST_REAL_JOB_ROOT to a running real upload')
    job = Path(source)
    if json.loads((job / 'result.json').read_text())['status'] != 'running':
        pytest.skip('the real upload is not currently running')
    base = [sys.executable, '-m', 'dopplergeist.cli', 'job', job.name, '--jobs', str(job.parent)]
    once = subprocess.run(base, check=True, capture_output=True, text=True)
    assert json.loads(once.stdout)['job_id'] == job.name
    watcher = subprocess.Popen(base + ['--watch', '--interval', '1'], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(2.5)
        assert watcher.poll() is None
        watcher.send_signal(signal.SIGINT)
        stdout, stderr = watcher.communicate(timeout=15)
    finally:
        if watcher.poll() is None:
            watcher.kill()
            watcher.wait()
    assert watcher.returncode == 130 and stdout == ''
    assert 'local checkpoint pieces' in stderr and 'pieces/min since last check' in stderr
    assert 'Stopped watching; the job continues.' in stderr
    assert json.loads((job / 'result.json').read_text())['status'] == 'running'


def test_real_upload_prints_job_id_before_final_json(tmp_path):
    source = os.environ.get('DOPPLERGEIST_REAL_JOB_ROOT')
    if not source:
        pytest.skip('set DOPPLERGEIST_REAL_JOB_ROOT to the original upload')
    audio = Path(source) / 'input.mp3'
    config = tmp_path / 'operator.json'
    config.write_text(json.dumps({'search_workers': 0}))  # Fail before audio discovery.
    jobs = tmp_path / 'jobs'
    result = subprocess.run([sys.executable, '-m', 'dopplergeist.cli', 'analyze', str(audio),
                             '--jobs', str(jobs), '--config', str(config)],
                            check=True, capture_output=True, text=True, timeout=60)
    value = json.loads(result.stdout)
    assert value['status'] == 'failed' and value['reason_code'] == 'invalid_configuration'
    assert f"Job {value['job_id']} started." in result.stderr
    assert f"dopplergeist job {value['job_id']}" in result.stderr
    assert (jobs / value['job_id'] / 'result.json').is_file()
