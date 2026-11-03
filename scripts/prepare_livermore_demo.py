#!/usr/bin/env python3
"""Prepare the explicitly prior-constrained Livermore demonstration inputs."""
import argparse
import json
from pathlib import Path

from dopplergeist.terrain import Terrain
from dopplergeist.tracks import read_kml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('case', type=Path, help='Extracted N784MB_R04 directory from Zenodo 23424278')
    parser.add_argument('geoid', type=Path, help='EGM96 geoid raster')
    parser.add_argument('output', type=Path, help='New preparation directory')
    args = parser.parse_args()
    case, geoid, output = args.case.resolve(), args.geoid.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    frame = read_kml(case / 'N784MB-track-EGM96.kml')
    frame['alt_m'] += Terrain([geoid]).sample(frame.lat.to_numpy(), frame.lon.to_numpy())
    frame['altitude_basis'] = 'ellipsoidal_from_egm96_msl'
    track = output / 'track-ellipsoid.csv'
    frame.to_csv(track, index=False)
    config = {
        'audio': str(case / 'audio.wav'), 'tracks': [str(track)],
        'terrain': {'constant_m': 150, 'geoid_raster': str(geoid)},
        'grid': {'bounds': [-121.84, 37.65, -121.70, 37.73], 'spacing_m': 300,
                 'scoring_spacing_m': 150, 'refine_spacing_m': 50, 'refine_pairs': 1},
        'recording_start_utc': '2026-05-14T17:41:32.238656Z',
        'filters': {'known_time_tolerance_s': 10},
        'scoring': {'mode': 'brightness', 'time_sweep_s': 5.01, 'time_step_s': .5},
        'events': [{'start_s': 0, 'end_s': 85., 'band_hz': [99, 164],
                    'max_slope_hz_s': 4, 'max_up_slope_hz_s': 1}],
        'scoring_workers': 2,
    }
    (output / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    print(output / 'config.json')


if __name__ == '__main__':
    main()
