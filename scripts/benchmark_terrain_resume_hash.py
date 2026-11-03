"""Measure repeated verification of an existing real terrain raster."""
import argparse
from collections import OrderedDict
import json
from pathlib import Path
import time

from dopplergeist.data_access import sha256
from dopplergeist.tiled_search import _verified_terrain_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raster', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=4)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    cpu, wall = time.process_time(), time.perf_counter()
    ordinary = [sha256(args.raster) for _ in range(args.repeats)]
    before = {'cpu_s':time.process_time()-cpu, 'elapsed_s':time.perf_counter()-wall,
              'full_hash_reads':args.repeats}
    cache = OrderedDict()
    cpu, wall = time.process_time(), time.perf_counter()
    reused = [_verified_terrain_hash(args.raster, cache) for _ in range(args.repeats)]
    after = {'cpu_s':time.process_time()-cpu, 'elapsed_s':time.perf_counter()-wall,
             'full_hash_reads':1}
    if ordinary != reused:
        raise ValueError('Repeated terrain hashes differ')
    result = {'raster_name':args.raster.name, 'bytes':args.raster.stat().st_size,
              'repeats':args.repeats, 'sha256':ordinary[0], 'ordinary':before, 'reused':after,
              'limitation':'Single-raster hash timing, not a complete resume or search benchmark.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
