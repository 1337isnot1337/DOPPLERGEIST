#!/usr/bin/env python3
"""Render the real ESID 920 acoustic proposal and the saved ranked search."""
import argparse
import csv
from pathlib import Path
import subprocess

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
from scipy.signal import spectrogram

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--audio', type=Path, required=True)
p.add_argument('--job', type=Path, required=True)
p.add_argument('--ranking', type=Path, required=True)
p.add_argument('--basemap', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()

start, duration, sample_rate = 315, 55, 4000
raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(start), '-t', str(duration),
    '-i', str(a.audio), '-ac', '1', '-ar', str(sample_rate), '-f', 'f32le', '-'])
samples = np.frombuffer(raw, dtype='<f4')
freq, times, power = spectrogram(samples, fs=sample_rate, nperseg=4096, noverlap=3584,
                                  scaling='spectrum', mode='psd')
select = (freq >= 90) & (freq <= 330)
db = 10 * np.log10(np.maximum(power[select], 1e-16))
rows = list(csv.DictReader(a.ranking.open()))
lat = np.array([float(r['latitude']) for r in rows])
lon = np.array([float(r['longitude']) for r in rows])
score = np.array([float(r['score']) for r in rows])

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 12, 'text.color': '#24364a',
    'axes.labelcolor': '#42576b', 'xtick.color': '#607184', 'ytick.color': '#607184',
    'axes.spines.top': False, 'axes.spines.right': False, 'figure.facecolor': '#f8f8f6'})
fig = plt.figure(figsize=(15, 7.7), facecolor='#f8f8f6')
gs = fig.add_gridspec(1, 2, width_ratios=[1, 1.08], left=.07, right=.97, top=.78, bottom=.19, wspace=.18)
ax = fig.add_subplot(gs[0, 0])
ax.pcolormesh(times + start, freq[select], db, shading='auto', cmap='Blues',
              vmin=np.percentile(db, 30), vmax=np.percentile(db, 99.2), rasterized=True)
for name in ['event-0006', 'event-0006-harmonic-2']:
    data = np.genfromtxt(a.job / 'discovery' / (name + '.csv'), delimiter=',', names=True)
    ax.plot(data['time_s'], data['frequency_hz'], color='#ef6542', lw=2.2)
ax.set(xlim=(start, start + duration), ylim=(90, 330), xlabel='Time in recording (seconds)', ylabel='Frequency (Hz)')
ax.set_title('An acoustic proposal', loc='left', fontsize=19, weight='medium', pad=14)
ax.text(.02, .96, 'Detected ridges', transform=ax.transAxes, va='top', color='#a52d20',
        bbox={'facecolor':'white', 'edgecolor':'none', 'alpha':.84, 'pad':4})

ax = fig.add_subplot(gs[0, 1])
ax.imshow(plt.imread(a.basemap), extent=[-77.92, -77.48, 43.05, 43.31], origin='upper', aspect='auto')
ax.add_patch(plt.Rectangle((-77.90,43.08),.40,.22, fill=False, edgecolor='white',
                           linewidth=1.0, linestyle='--', alpha=.8))
points = ax.scatter(lon, lat, c=score, cmap='magma', norm=Normalize(vmin=.35, vmax=.65),
                    s=30, edgecolors='white', linewidths=.35, zorder=3)
ax.scatter([lon[0]], [lat[0]], marker='*', s=230, facecolor='#ffdd83',
           edgecolor='#182a3a', linewidth=1.2, zorder=4)
ax.scatter([-77.75444], [43.18657], s=130, facecolor='white',
           edgecolor='#162a3a', linewidth=2.1, zorder=5)
ax.annotate('Published site', (-77.75444,43.18657), xytext=(-77.744,43.195), color='white',
            fontsize=11, weight='bold', bbox={'boxstyle':'round,pad=.28','fc':'#1b2b3a','ec':'none','alpha':.85})
ax.annotate('Top candidate', (lon[0],lat[0]), xytext=(-77.705,43.056), color='white',
            fontsize=11, weight='bold', bbox={'boxstyle':'round,pad=.28','fc':'#1b2b3a','ec':'none','alpha':.85})
ax.set(xlim=(-77.92,-77.48), ylim=(43.05,43.31), xlabel='Longitude', ylabel='Latitude')
ax.set_title('Ranked locations', loc='left', fontsize=19, weight='medium', pad=14)
cbar = fig.colorbar(points, ax=ax, orientation='horizontal', fraction=.05, pad=.14, aspect=30)
cbar.set_label('Fit score · higher is better', labelpad=3)
cbar.outline.set_visible(False)
fig.text(.07, .94, 'A public recording near Rochester', fontsize=23, weight='bold')
fig.text(.07, .89, 'The highest-ranked location is 14.1 km from the publisher’s site', fontsize=13, color='#53697c')
fig.text(.07, .05, 'Eclipse Soundscapes ESID 920  ·  ADSB.lol  ·  Imagery: Esri, Vantor, Earthstar Geographics, GIS User Community', fontsize=9, color='#637589')
fig.text(.07, .025, 'Dashed: input area. Clock and site accuracy unverified. Acoustic source unconfirmed; search inconclusive.', fontsize=9, color='#637589')
a.output.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(a.output, dpi=180, facecolor=fig.get_facecolor())
