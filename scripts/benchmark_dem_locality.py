"""Measure clustered versus interleaved sampling of actual saved search tiles."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import rasterio

from dopplergeist.data_access import CachedTerrain
from dopplergeist.tiled_search import _tile_coordinates

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--job', type=Path, required=True, help='real job with saved tile receipts')
parser.add_argument('--cache', type=Path, required=True, help='real data cache containing terrain/')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
JOB = args.job
config = json.loads((JOB/'search/manifest.json').read_text())['configuration']
eligible = []
for path in sorted((JOB/'search').glob('tile-*.json')):
    try:
        payload = json.loads(path.read_text())['payload']
        if payload.get('grid_points', 0) >= 500 and len(payload.get('terrain_files', [])) >= 3:
            eligible.append((path.name, payload['cells']))
    except (OSError, ValueError, KeyError):
        pass
assert len(eligible) >= 12
chosen = [eligible[i] for i in np.linspace(0, len(eligible)-1, 12, dtype=int)]
points = [_tile_coordinates(tuple(cells), config['budget']['spacing_m'], config['bounds'], config['crs'])
          for _, cells in chosen]
original_open = rasterio.open


def run(order):
    terrain = CachedTerrain(args.cache/'terrain', offline=True, adopt_existing=True)
    # The same cache is visited in the same order before either measurement.
    for point in points:
        terrain.sample(point.lat.to_numpy(), point.lon.to_numpy())
    opened = {'total':0, 'dem':0}
    def instrumented_open(path, *args, **kwargs):
        opened['total'] += 1
        opened['dem'] += Path(path).name.startswith('Copernicus_DSM_COG_30_')
        return original_open(path, *args, **kwargs)
    results = {}
    cpu, wall = time.process_time(), time.perf_counter()
    rasterio.open = instrumented_open
    try:
        for i in order:
            point = points[i]
            result = terrain.sample(point.lat.to_numpy(), point.lon.to_numpy())
            if i in results:
                np.testing.assert_array_equal(results[i], result)
            else:
                results[i] = result
    finally:
        rasterio.open = original_open
    return results, {'cpu_s':time.process_time()-cpu, 'elapsed_s':time.perf_counter()-wall,
                     'raster_opens':opened, 'cache_bytes':terrain._tile_cache_bytes}


clustered = [i for i in range(len(points)) for _ in range(3)]
interleaved = list(range(len(points)))*3
first, a = run(clustered)
second, b = run(interleaved)
for key in first:
    np.testing.assert_array_equal(first[key], second[key])
output = {'actual_saved_tiles':[name for name, _ in chosen], 'points':[len(p) for p in points],
          'repetitions':3, 'clustered':a, 'interleaved':b, 'elevation_arrays_equal':True,
          'elevation_sha256':{str(key): hashlib.sha256(value.tobytes()).hexdigest() for key, value in first.items()},
          'note':'Cached-terrain locality microbenchmark; not a complete search speed estimate.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(output, indent=2)+'\n')
print(json.dumps(output, indent=2), flush=True)
