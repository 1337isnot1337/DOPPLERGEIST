"""Compare fixed-floor and ordinary scoring on one saved real receiver point."""
import argparse
import json
import tempfile
import time
from pathlib import Path

from dopplergeist.data_access import FlightIndex, content_hash, sha256
from dopplergeist.matching import prepare_events
from dopplergeist.parallel_tiles import initialize_tile_worker, score_tile
from dopplergeist.tiled_search import SearchBudget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True, help='real tile receipt containing a ranked receiver')
    parser.add_argument('--terrain', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True, action='append')
    parser.add_argument('--floor', type=float, required=True, help='test floor; not automatically trusted for search')
    args = parser.parse_args()
    manifest = json.loads((args.job/'search/manifest.json').read_text())
    config = manifest['configuration']
    if content_hash(config) != manifest['run_hash']:
        raise ValueError('Search manifest is corrupt')
    supplied = {FlightIndex(path).report['input_hash']: sha256(path) for path in args.index}
    expected = {item['input_hash']: item['file_sha256'] for item in config['indexes']}
    if supplied != expected:
        raise ValueError('Flight indexes do not match the search manifest')
    events, measurements = prepare_events(json.loads((args.job/'discovery/discovery.json').read_text())['events'])
    if content_hash(events) != content_hash(config['events']):
        raise ValueError('Discovery does not match the search manifest')
    receipt = json.loads(args.receipt.read_text())
    if receipt['payload_hash'] != content_hash(receipt['payload']):
        raise ValueError('Receipt payload does not match its checksum')
    row = receipt['payload']['ranked'][0]
    budget = SearchBudget(**config['budget'])
    x, y = round(row['x']/budget.spacing_m), round(row['y']/budget.spacing_m)
    parameters = dict(config['scoring'])
    window = parameters.pop('recording_start_window_s', None)
    with tempfile.TemporaryDirectory(prefix='doppler-shared-floor-') as temporary:
        initialize_tile_worker(args.index, args.terrain, {'offline':True}, events, measurements,
                               config['bounds'], config['time_range_s'], budget, parameters, config['filters'],
                               window, config['crs'], Path(temporary)/'workers',
                               content_hash({'manifest':manifest['run_hash'], 'purpose':'single-point benchmark'}),
                               'matched_group_support_minus_normalized_residual')
        outputs = []
        for label, floor in (('baseline', None), ('fixed_floor', args.floor)):
            cpu, wall = time.process_time(), time.perf_counter()
            payload, database = score_tile('coarse:benchmark', (x, y, x+1, y+1), score_floor=floor)
            counts = payload['counts']
            print(json.dumps({'mode':label, 'cpu_s':time.process_time()-cpu, 'elapsed_s':time.perf_counter()-wall,
                              'associations':counts['candidates'], 'evaluated_trials':counts['evaluated_trials'],
                              'bounded_candidates':counts['bounded_score_candidates'],
                              'unbounded_candidates':counts['unbounded_score_candidates']}), flush=True)
            outputs.append([candidate for candidate in payload['ranked'] if candidate['score'] >= args.floor])
            Path(database).unlink()
        if outputs[0] != outputs[1]:
            raise ValueError('Retained candidates at or above the floor differ')
        print('All retained candidates at or above the floor match', flush=True)


if __name__ == '__main__':
    main()
