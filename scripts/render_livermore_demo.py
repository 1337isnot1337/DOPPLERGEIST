#!/usr/bin/env python3
"""Render the real, constrained Livermore N784MB_R04 demonstration."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
from pyproj import Geod

from dopplergeist.geometry import ecef
from dopplergeist.matching import predict_fitted_ridge
from dopplergeist.tracks import load_tracks

# Image extent for the documented USGS NAIP request, WGS84.
BBOX = (-121.82, 37.642, -121.74, 37.687)
# Inferred from the dataset's reported track offsets; not measured microphone GPS.
REFERENCE = (37.66321511833046, -121.78187655936314)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('imagery', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = json.loads((args.run / 'report.json').read_text())
    ranked = json.loads((args.run / 'ranked-grid.json').read_text())
    best, cfg = report['best'], report['config']
    rows = [r for r in ranked if r['flight_ids'] == best['flight_ids']]
    if not rows:
        raise ValueError('No grid scores for winning flight combination')
    tracks, _ = load_tracks(report['imports'][0]['path'], max_gap_s=cfg.get('max_track_gap_s', 30))
    track = {t.id: t for t in tracks}[best['flight_ids'][0]]
    spec = np.load(args.run / 'event-1.npz')
    time, freq = spec['time'], spec['frequency']
    diag = dict(best.get('event_diagnostics', [{}])[0], f0_hz=best['f0_hz'][0])
    model = predict_fitted_ridge(track, ecef(best['lat'], best['lon'], best['elev_m']),
                                 best['recording_start_time_s'] + time, diag,
                                 cfg.get('sound_speed_mps', 343.0))
    distance = Geod(ellps='WGS84').inv(best['lon'], best['lat'], REFERENCE[1], REFERENCE[0])[2]

    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11, 'text.color':'#202d38',
                         'axes.labelcolor':'#5b6875','xtick.color':'#687581','ytick.color':'#687581'})
    fig = plt.figure(figsize=(14.5, 7.1), facecolor='#fbfaf7')
    gs = fig.add_gridspec(1, 2, left=.065, right=.97, bottom=.20, top=.86, wspace=.16)
    ax = fig.add_subplot(gs[0,0])
    ax.pcolormesh(time, freq, spec['contrast'], shading='auto', cmap='Blues',
                  vmin=0, vmax=5, rasterized=True)
    ax.plot(time, model, color='#e76b45', lw=2.6, label='Fitted aircraft model')
    ax.set(title='The recorded flyover', xlabel='Time in recording (s)', ylabel='Frequency (Hz)')
    ax.title.set_fontsize(20); ax.title.set_fontweight('normal'); ax.title.set_position((.5,1.03))
    ax.spines[['top','right']].set_visible(False)
    ax.legend(loc='upper right', frameon=True, framealpha=.9, fontsize=10)

    ax = fig.add_subplot(gs[0,1]); west,south,east,north = BBOX
    ax.imshow(plt.imread(args.imagery), extent=[west,east,south,north], origin='upper', aspect=1/np.cos(np.deg2rad(37.665)))
    # A line connects actual samples from the selected track segment; clipping is visual only.
    ax.plot(track.lon, track.lat, color='#17242c', lw=4, alpha=.8, zorder=1)
    ax.plot(track.lon, track.lat, color='white', lw=2, alpha=.9, zorder=2)
    scores = np.array([r['score'] for r in rows]); order = np.argsort(scores)
    dots = ax.scatter(np.array([r['lon'] for r in rows])[order],
                      np.array([r['lat'] for r in rows])[order], c=scores[order], s=29,
                      cmap='magma', norm=Normalize(vmin=scores.min(), vmax=scores.max()),
                      edgecolor='none', alpha=.88, zorder=3)
    ax.scatter(REFERENCE[1], REFERENCE[0], s=130, facecolor='white', edgecolor='#17242c', linewidth=2, zorder=5)
    ax.scatter(best['lon'], best['lat'], s=145, marker='*', facecolor='#f5d55c', edgecolor='#17242c', linewidth=1, zorder=6)
    ax.set(xlim=(west,east),ylim=(south,north)); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title('The bounded search', fontsize=20, fontweight='normal', pad=15)
    # Longitude of a 1 km eastward geodesic at the latitude of the scale.
    scale_lon = Geod(ellps='WGS84').fwd(west+.003, south+.003, 90, 1000)[0]
    ax.plot([west+.003,scale_lon],[south+.003,south+.003], color='white',lw=5,zorder=8)
    ax.plot([west+.003,scale_lon],[south+.003,south+.003], color='#17242c',lw=2,zorder=9)
    ax.text(west+.003,south+.0042,'1 km',color='white',fontsize=10,weight='bold',zorder=9)
    cb=fig.colorbar(dots, ax=ax, orientation='horizontal', fraction=.038, pad=.025)
    cb.set_label('Fit score  ·  higher is better  ·  not a probability',fontsize=9)
    cb.ax.tick_params(labelsize=8)
    fig.text(.065,.115, f'★  Highest score     ●  Inferred reference     —  Aircraft track       {distance:.0f} m between points',
             fontsize=10, color='#334451')
    fig.text(.065,.075, 'Real recording · supplied aircraft, approximate area and time · reference inferred from track data',
             fontsize=9, color='#5b6875')
    fig.text(.065,.047, 'Research ranking; incomplete model assessment. USGS / USDA NAIP imagery.', fontsize=9, color='#5b6875')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'{args.output}: {distance:.1f} m from inferred reference; {len(rows)} scored grid points')


if __name__ == '__main__':
    main()
