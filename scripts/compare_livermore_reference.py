"""Compare the Livermore run to a reference inferred from other flyovers."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Geod
from scipy.optimize import least_squares

from dopplergeist.tracks import read_kml

parser = argparse.ArgumentParser(
    description="Compare a configured Livermore run to an inferred leave-one-case-out reference"
)
parser.add_argument(
    "dataset",
    type=Path,
    help="Zenodo dataset directory with final CSV and extracted case folders",
)
parser.add_argument("run", type=Path, help="Completed run directory")
args = parser.parse_args()
root = args.dataset
rows = pd.read_csv(root / "final_results_40_cases.csv")
tracks = []
for row in rows.itertuples():
    if row.case == "N784MB_R04":
        continue
    d = root / "extracted" / row.category / row.case
    freq = pd.read_csv(d / "frequency_vs_time_used.csv")
    t = pd.to_datetime(freq.time_utc, utc=True)
    mid = (t.iloc[0].timestamp() + t.iloc[-1].timestamp()) / 2
    tr = read_kml(d / row.track_file)
    tr = tr[abs(tr.time_s - mid) < 300]
    x = (tr.lon.to_numpy() + 121.77) * 111320 * np.cos(np.deg2rad(37.68))
    y = (tr.lat.to_numpy() - 37.68) * 110574
    tracks.append(
        (
            row.case,
            x,
            y,
            float(row.L_ADSB_m),
            tr.alt_m.to_numpy(),
            float(row.H_ADSB_above_recorder_m),
        )
    )


def distance(v, x, y):
    dx = np.diff(x)
    dy = np.diff(y)
    t = np.clip(
        ((v[0] - x[:-1]) * dx + (v[1] - y[:-1]) * dy)
        / np.maximum(dx * dx + dy * dy, 1e-9),
        0,
        1,
    )
    ds = np.hypot(x[:-1] + t * dx - v[0], y[:-1] + t * dy - v[1])
    i = np.argmin(ds)
    return ds[i], i, t[i]


def residual(v, subset):
    return np.array([distance(v, x, y)[0] - L for _, x, y, L, _, _ in subset])


starts = [
    (x, y) for x in range(-10000, 10001, 2500) for y in range(-10000, 10001, 2500)
]
best = min(starts, key=lambda x: sum(abs(residual(x, tracks))))
fit = least_squares(residual, best, args=(tracks,), loss="soft_l1", f_scale=50)
inliers = [t for t, r in zip(tracks, residual(fit.x, tracks)) if abs(r) < 150]
fit = least_squares(residual, fit.x, args=(inliers,), loss="soft_l1", f_scale=50)
lat = 37.68 + fit.x[1] / 110574
lon = -121.77 + fit.x[0] / (111320 * np.cos(np.deg2rad(37.68)))
alt = []
for _, x, y, L, z, h in inliers:
    _, i, u = distance(fit.x, x, y)
    alt.append(z[i] + u * (z[i + 1] - z[i]) - h)
run = json.loads((args.run / "report.json").read_text())
b = run["best"]
_, _, meters = Geod(ellps="WGS84").inv(lon, lat, b["lon"], b["lat"])
out = {
    "method": "inferred from other cases only using published horizontal offsets and flight tracks; not surveyed reference",
    "excluded_target": "N784MB_R04",
    "initial_count": len(tracks),
    "inliers_150m": len(inliers),
    "excluded_outliers": [t[0] for t in tracks if t[0] not in {a[0] for a in inliers}],
    "lat": lat,
    "lon": lon,
    "median_alt_msl_m": float(np.median(alt)),
    "inlier_rms_m": float(np.sqrt(np.mean(residual(fit.x, inliers) ** 2))),
    "distance_top_to_inferred_m": meters,
}
print(json.dumps(out, indent=2))
