#!/usr/bin/env python3
"""Render the saved real MP3 upload's spectrogram and retained search scores."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
from pyproj import Geod

from dopplergeist.audio import spectrogram
from dopplergeist.data_access import FlightIndex
from dopplergeist.geometry import ecef
from dopplergeist.matching import predict_fitted_ridge

# Extent of the documented USGS image request, WGS84.
BBOX = (-121.82, 37.642, -121.74, 37.687)
REFERENCE = (37.66321511833046, -121.78187655936314)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path, help='Completed local MP3 upload job directory')
    parser.add_argument('flight_index', type=Path, help='Flight index used by the job')
    parser.add_argument('imagery', type=Path, help='USGS NAIP image for the documented extent')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()

    result = json.loads((args.job / 'result.json').read_text())
    refined = json.loads((args.job / 'refined-candidates.json').read_text())['ranked']
    discovery = json.loads((args.job / 'discovery/discovery.json').read_text())
    recording = json.loads((args.job / 'intake/recording.json').read_text())
    best = refined[0]
    if (best['lat'], best['lon'], best['score']) != tuple(result['candidates'][0][k] for k in ('lat', 'lon', 'score')):
        raise ValueError('Refined winner and API ranking do not match')
    geod = Geod(ellps='WGS84')
    alternative = next(row for row in result['candidates'][1:]
                       if geod.inv(best['lon'], best['lat'], row['lon'], row['lat'])[2] >= 250)
    distances = [geod.inv(REFERENCE[1], REFERENCE[0], row['lon'], row['lat'])[2]
                 for row in (best, alternative)]

    event = next(item for item in discovery['events'] if item['event_id'] == best['event_ids'][0])
    sample_rate = recording['sample_rate_hz']
    samples = np.memmap(args.job / 'intake/recording.f32', dtype='<f4', mode='r')
    spec = spectrogram(np.asarray(samples), sample_rate, event['band_hz'])
    tracks = list(FlightIndex(args.flight_index).lookup(best['flight_ids']))
    by_id = {track.id: track for track in tracks}
    track = by_id[best['flight_ids'][0]]
    diagnostic = dict(best['event_diagnostics'][0], f0_hz=best['f0_hz'][0])
    model = predict_fitted_ridge(track, ecef(best['lat'], best['lon'], best['elev_m']),
                                 best['recording_start_time_s'] + spec.time, diagnostic)

    # Each tile retained its highest-scoring hypotheses. Plot the best retained
    # score per receiver point; absent points are not interpolated or scored here.
    points = {}
    for tile in sorted((args.job / 'search').glob('tile-*.json')):
        for row in json.loads(tile.read_text())['payload']['ranked']:
            key = (row['lat'], row['lon'])
            points[key] = max(points.get(key, float('-inf')), row['score'])
    if not points:
        raise ValueError('No retained tile scores found')
    coords = np.array(list(points))
    scores = np.array(list(points.values()))
    order = np.argsort(scores)

    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11, 'text.color':'#202d38',
                         'axes.labelcolor':'#5b6875', 'xtick.color':'#687581', 'ytick.color':'#687581'})
    fig = plt.figure(figsize=(14.5, 7.1), facecolor='#fbfaf7')
    gs = fig.add_gridspec(1, 2, left=.065, right=.97, bottom=.18, top=.86, wspace=.16)
    ax = fig.add_subplot(gs[0, 0])
    ax.pcolormesh(spec.time, spec.frequency, spec.contrast, shading='auto', cmap='Blues',
                  vmin=0, vmax=5, rasterized=True)
    ax.plot(spec.time, model, color='#e76b45', lw=2.6, label='Fitted aircraft model')
    ax.set(title='The recorded flyover', xlabel='Time in recording (s)', ylabel='Frequency (Hz)')
    ax.title.set_fontsize(20); ax.title.set_fontweight('normal'); ax.title.set_position((.5, 1.03))
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(loc='upper right', frameon=True, framealpha=.9, fontsize=10)

    ax = fig.add_subplot(gs[0, 1]); west, south, east, north = BBOX
    ax.imshow(plt.imread(args.imagery), extent=[west, east, south, north], origin='upper',
              aspect=1 / np.cos(np.deg2rad(37.665)))
    ax.plot(track.lon, track.lat, color='#17242c', lw=4, alpha=.8, zorder=1)
    ax.plot(track.lon, track.lat, color='white', lw=2, alpha=.9, zorder=2)
    dots = ax.scatter(coords[order, 1], coords[order, 0], c=scores[order], s=29,
                      cmap='magma', norm=Normalize(vmin=scores.min(), vmax=scores.max()),
                      edgecolor='none', alpha=.88, zorder=3)
    ax.scatter(REFERENCE[1], REFERENCE[0], s=130, facecolor='white', edgecolor='#17242c', linewidth=2, zorder=5)
    ax.scatter(alternative['lon'], alternative['lat'], s=95, marker='D', facecolor='#69d5c8',
               edgecolor='#17242c', linewidth=1, zorder=6)
    ax.scatter(best['lon'], best['lat'], s=145, marker='*', facecolor='#f5d55c',
               edgecolor='#17242c', linewidth=1, zorder=7)
    ax.set(xlim=(west, east), ylim=(south, north)); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title('The search, up close', fontsize=20, fontweight='normal', pad=15)
    scale_lon = geod.fwd(west + .005, south + .005, 90, 1000)[0]
    ax.plot([west + .005, scale_lon], [south + .005, south + .005], color='white', lw=5, zorder=8)
    ax.plot([west + .005, scale_lon], [south + .005, south + .005], color='#17242c', lw=2, zorder=9)
    ax.text(west + .005, south + .0075, '1 km', color='white', fontsize=10, weight='bold', zorder=9)
    cb = fig.colorbar(dots, ax=ax, orientation='horizontal', fraction=.038, pad=.025)
    cb.set_label('Retained fit score  ·  higher is better', fontsize=9)
    cb.ax.tick_params(labelsize=8)
    fig.text(.5, .078, f'★  Highest score ({distances[0]:.0f} m)     ◆  Alternative ({distances[1]:.0f} m)'
             '     ●  Inferred reference     —  Aircraft track', ha='center', fontsize=10, color='#334451')
    fig.text(.065, .035, 'USGS / USDA NAIP imagery', fontsize=9, color='#5b6875')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'{args.output}: {len(points)} retained points; {distances[0]:.1f} m and {distances[1]:.1f} m from inferred reference')


if __name__ == '__main__':
    main()
