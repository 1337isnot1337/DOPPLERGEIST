"""Exercise clustered worker scheduling on actual saved full-day search tiles."""
import json
import os
from pathlib import Path

import pytest

from dopplergeist.data_access import _index_pool
from dopplergeist.matching import prepare_events
from dopplergeist.parallel_tiles import initialize_tile_worker, ordered_tile_results
from dopplergeist.tiled_search import SearchBudget


def test_saved_real_tiles_keep_payloads_and_result_order(tmp_path):
    job_path = os.environ.get('DOPPLERGEIST_REAL_JOB_ROOT')
    cache_path = os.environ.get('DOPPLERGEIST_REAL_CACHE_ROOT')
    if not job_path or not cache_path:
        pytest.skip('set the real job and cache paths')
    job, cache = Path(job_path), Path(cache_path)
    search = job/'search-before-combined-cb996dc'
    manifest = json.loads((search/'manifest.json').read_text())
    config = manifest['configuration']
    events, measurements = prepare_events(json.loads((job/'discovery/discovery.json').read_text())['events'])
    options = []
    for path in search.glob('tile-*.json'):
        if '~' in path.name:
            continue
        record = json.loads(path.read_text())
        payload = record['payload']
        counts = payload.get('counts', {})
        if (payload.get('grid_points', 0) > 0 and counts.get('cpa_rows') == counts.get('candidates') == 0):
            options.append((payload['grid_points'] * payload['tracks'], path.name, payload))
    chosen = sorted(options)[:4]
    assert len(chosen) == 4
    chosen.reverse()
    budget = SearchBudget(**config['budget'])
    parameters = dict(config['scoring'])
    window = parameters.pop('recording_start_window_s', None)
    indexes = [cache/'flights'/day/'staging-0/all-types-v2-543f483cee75.sqlite'
               for day in ('2026-09-08', '2026-09-09')]
    initargs = (indexes, cache/'terrain', {'offline': True}, events, measurements, config['bounds'],
                config['time_range_s'], budget, parameters, config['filters'], window, config['crs'],
                tmp_path/'workers', manifest['run_hash'], 'matched_group_support_minus_normalized_residual')
    jobs = [('coarse:'+name[len('tile-'):-len('.json')], tuple(payload['cells']), None, None)
            for _, name, payload in chosen]

    def finish(stage, cells, future):
        payload, database = future.result()
        Path(database).unlink()
        return payload

    with _index_pool(2, initialize_tile_worker, initargs) as pool:
        results = list(ordered_tile_results(pool, jobs, 2, finish))
    assert [result[0] for result in results] == [job[0] for job in jobs]
    assert [result[2] for result in results] == [item[2] for item in chosen]
