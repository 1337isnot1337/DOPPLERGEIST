"""Terrain sampling and common projected grids."""
from pathlib import Path

import numpy as np
from pyproj import Transformer


class Terrain:
    def __init__(self, paths=None, constant_m=None, geoid_path=None):
        import rasterio
        self.rasters = [rasterio.open(p) for p in (paths or [])]
        self.constant = constant_m
        self.geoid = Terrain([geoid_path]) if geoid_path else None
        if not self.rasters and constant_m is None:
            raise ValueError("Supply DEM raster paths or an explicit constant ground elevation")

    def sample(self, lat, lon):
        lat, lon = np.broadcast_arrays(lat, lon)
        elevation = np.full(lat.shape, np.nan)
        for raster in self.rasters:
            transform = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True)
            x, y = transform.transform(lon.ravel(), lat.ravel())
            values = np.ma.asarray(list(raster.sample(zip(x, y), masked=True)))[:, 0]
            valid = ~np.ma.getmaskarray(values)
            flat = elevation.ravel()
            flat[valid] = np.asarray(values)[valid]
        if self.constant is not None:
            elevation[~np.isfinite(elevation)] = self.constant
        if not np.all(np.isfinite(elevation)):
            raise ValueError(f"DEM coverage missing for {np.sum(~np.isfinite(elevation))} candidate points")
        if self.geoid:
            elevation += self.geoid.sample(lat,lon)
        return elevation


def corridor_grid(tracks, events, spacing_m, terrain, crs="EPSG:5070", bounds=None, time_origin=None):
    """Only materialize grid cells near plausible aircraft segments.

    Coordinates use one shared CRS and grid origin, so overlapping flight corridors
    deduplicate. There is no recording-position prior hidden in grid construction.
    """
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    cells = []
    for track in tracks:
        for event in events:
            lo_v, hi_v = event["speed_range_mps"]
            radius = event["slant_range_m"][1]
            # Sampling by travelled distance prevents a long path from producing
            # a huge empty bounding rectangle. Expand disks for the anchor gap.
            anchor_step = max(1.0, radius / 3 / max(hi_v, 1))
            t = np.arange(track.time[0], track.time[-1], anchor_step)
            if time_origin is not None:
                lo = time_origin + event["start_s"] - radius / event.get("sound_speed_mps", 343) - 10
                hi = time_origin + event["end_s"] + 10
                t = t[(t >= lo) & (t <= hi)]
            if not len(t):
                continue
            speed = np.linalg.norm(track.speed_vector(t), axis=1)
            t = t[(speed >= lo_v) & (speed <= hi_v)]
            if not len(t):
                continue
            lat = np.interp(t, track.time, track.lat)
            lon = np.interp(t, track.time, track.lon)
            x, y = forward.transform(lon, lat)
            anchors = np.unique(np.round(np.column_stack((x, y)) / spacing_m).astype(np.int64), axis=0)
            # EPSG:5070 grid scale is close to unity over CONUS; 10% padding
            # plus an anchor gap protects corridor coverage under distortion.
            pad = radius * 1.45 + spacing_m
            size = int(np.ceil(pad / spacing_m))
            dx, dy = np.meshgrid(np.arange(-size, size+1), np.arange(-size,size+1))
            offsets = np.column_stack((dx.ravel(), dy.ravel()))
            offsets = offsets[np.linalg.norm(offsets, axis=1) * spacing_m <= pad]
            for anchor in anchors:
                cells.append(anchor + offsets)
    if not cells:
        raise ValueError("No flight segments meet event speed/time bounds")
    cells = np.unique(np.concatenate(cells), axis=0)
    x, y = cells[:,0] * spacing_m, cells[:,1] * spacing_m
    lon, lat = inverse.transform(x, y)
    if bounds:
        west, south, east, north = bounds
        keep = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
        x, y, lon, lat = (a[keep] for a in (x,y,lon,lat))
    height = terrain.sample(lat,lon)
    import pandas as pd
    return pd.DataFrame({"point_id": np.arange(len(x)), "x":x, "y":y, "lat":lat, "lon":lon, "elev_m":height})


def refine_grid(points, coarse_spacing, fine_spacing, terrain, crs="EPSG:5070"):
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    radius = int(np.ceil(coarse_spacing / fine_spacing))
    dx, dy = np.meshgrid(np.arange(-radius,radius+1),np.arange(-radius,radius+1))
    offsets = np.column_stack((dx.ravel(),dy.ravel())) * fine_spacing
    coords = np.unique(np.concatenate([np.array([r.x,r.y])+offsets for r in points.itertuples()]),axis=0)
    lon,lat = inverse.transform(coords[:,0],coords[:,1])
    import pandas as pd
    return pd.DataFrame({"point_id":np.arange(len(coords)),"x":coords[:,0],"y":coords[:,1],
                         "lat":lat,"lon":lon,"elev_m":terrain.sample(lat,lon)})
