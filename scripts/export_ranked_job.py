#!/usr/bin/env python3
"""Export a completed job's rankings and spatially distinct alternatives."""
import argparse
import csv
import json
from pathlib import Path

from pyproj import Geod


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path, help='Completed job result.json')
    parser.add_argument('output', type=Path, help='New output directory')
    parser.add_argument('--reference', nargs=2, type=float, metavar=('LAT', 'LON'),
                        help='Optional evaluation-only reference, used after the search')
    parser.add_argument('--separation-m', type=float, default=300,
                        help='Minimum spacing between displayed alternatives (default: 300 m)')
    args = parser.parse_args()
    if args.separation_m < 0:
        parser.error('--separation-m must be nonnegative')
    result = json.loads(args.result.read_text())
    candidates = result.get('candidates', [])
    if any(a['score'] < b['score'] for a, b in zip(candidates, candidates[1:])):
        raise ValueError('Candidate list is not sorted by descending score')

    args.output.mkdir(parents=True, exist_ok=False)
    geod = Geod(ellps='WGS84')
    fields = ['rank', 'latitude', 'longitude', 'score', 'score_kind', 'recording_start_utc',
              'flight_ids', 'event_ids', 'distance_to_reference_m']
    rows, distinct = [], []
    for rank, candidate in enumerate(candidates, 1):
        lat, lon = float(candidate['lat']), float(candidate['lon'])
        distance = (geod.inv(lon, lat, args.reference[1], args.reference[0])[2]
                    if args.reference else None)
        row = {'rank': rank, 'latitude': lat, 'longitude': lon, 'score': candidate['score'],
               'score_kind': candidate.get('score_kind', ''),
               'recording_start_utc': candidate.get('recording_start_utc', ''),
               'flight_ids': '|'.join(candidate.get('flight_ids', [])),
               'event_ids': '|'.join(candidate.get('event_ids', [])),
               'distance_to_reference_m': round(distance, 1) if distance is not None else ''}
        rows.append(row)
        if all(geod.inv(lon, lat, prior['longitude'], prior['latitude'])[2] >= args.separation_m
               for prior in distinct):
            distinct.append(row)
    for filename, output_rows in [('all-candidates.csv', rows), ('spatially-distinct.csv', distinct)]:
        with (args.output / filename).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            writer.writerows(output_rows)
    print(f"{result.get('status')} / {result.get('reason_code')}; {len(rows)} ranked candidates; "
          f"{len(distinct)} spatial representatives at {args.separation_m:g} m minimum separation")
    for row in distinct[:10]:
        reference = f"  reference distance {row['distance_to_reference_m']} m" if args.reference else ''
        print(f"rank {row['rank']:3d}  {row['latitude']:.6f}, {row['longitude']:.6f}  "
              f"score {row['score']:.6f}{reference}")


if __name__ == '__main__':
    main()
