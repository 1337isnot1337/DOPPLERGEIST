"""Terrain sampling and common projected grids."""
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
import stat
from threading import RLock
from weakref import ref

import numpy as np
from pyproj import Transformer

_PIXEL_CACHE_MAX_ENTRIES = 1024


def _glo90_tile_degrees(lat, lon):
    """Select the published COG footprint, including latitude-dependent widths."""
    # GLO-90 removes its southern/eastern overlap pixels. Latitude footprints
    # are south-exclusive/north-inclusive, shifted north by half a 3" pixel.
    north = np.ceil(np.asarray(lat) - 1 / 2400).astype(int) - 1
    # Use the selected tile's latitude band, not the point latitude: the N49
    # footprint extends slightly north of 50 degrees; S50 has 1200 columns.
    # https://copernicus-dem-90m.s3.amazonaws.com/readme.html
    band = np.searchsorted([50, 60, 70, 80, 85], np.abs(north + .5))
    width = np.asarray([1200, 800, 600, 400, 240, 120])[band]
    east = np.floor(np.asarray(lon) + .5 / width).astype(int)
    return np.column_stack((north, east))


@lru_cache(maxsize=32)
def _raster_transformer(crs):
    """Reuse a raster's unchanged coordinate operation across refinement calls."""
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True)


def _raster_file_signature(paths):
    """Notice replacement, writes, removal and new sidecars without reading data."""
    try:
        records = [path.stat() for path in paths]
        if not stat.S_ISREG(records[0].st_mode):
            return None
        return tuple((record.st_dev, record.st_ino, record.st_size,
                      record.st_mtime_ns, record.st_ctime_ns) for record in records)
    except OSError:
        return None


def _raster_pixel_source(raster):
    """Admit only an ordinary read-only single-file local GeoTIFF reader."""
    from rasterio.io import DatasetReader
    from rasterio._io import DatasetReaderBase

    if (type(raster) is not DatasetReader or raster.closed or raster.mode != "r"
            or DatasetReader.read is not DatasetReaderBase.read
            or "read" in getattr(raster, "__dict__", {})
            or raster.driver != "GTiff" or raster.files != [raster.name]):
        return None
    try:
        path = Path(raster.name).absolute()
        # Directory stamps also notice a mask/auxiliary file created later.
        paths = (path, *dict.fromkeys((path.parent, path.resolve().parent)))
        signature = _raster_file_signature(paths)
        return (ref(raster), DatasetReader.read, paths, signature) if signature is not None else None
    except (OSError, ValueError, TypeError):
        return None


class Terrain:
    def __init__(self, paths=None, constant_m=None, geoid_path=None):
        import rasterio
        self.rasters = [rasterio.open(p) for p in (paths or [])]
        self._pixel_cache = OrderedDict()
        self._pixel_cache_lock = RLock()
        self._pixel_sources = {}
        for raster in self.rasters:
            source = _raster_pixel_source(raster)
            if source is not None:
                self._pixel_sources[id(raster)] = source
        self.constant = constant_m
        self.geoid = Terrain([geoid_path]) if geoid_path else None
        if not self.rasters and constant_m is None:
            raise ValueError("Supply DEM raster paths or an explicit constant ground elevation")

    def _read_window(self, raster, window):
        # Only reuse the exact 1x1 reads already requested by the original path.
        # Array coordinates, floor arithmetic, masks and raster order stay there.
        sources = getattr(self, "_pixel_sources", None)
        source = sources.get(id(raster)) if sources is not None else None
        if source is None or window.width != 1 or window.height != 1:
            return raster.read(1, window=window, masked=True)
        with self._pixel_cache_lock:
            signature = _raster_file_signature(source[2])
            if (raster is not source[0]() or raster.closed or raster.mode != "r"
                    or type(raster).read is not source[1]
                    or "read" in getattr(raster, "__dict__", {}) or signature != source[3]):
                # Do not re-enable a changed reader: an open handle can still
                # refer to the old inode after its path is replaced.
                self._pixel_sources.pop(id(raster), None)
                for key in list(self._pixel_cache):
                    if key[0] == id(raster):
                        del self._pixel_cache[key]
                return raster.read(1, window=window, masked=True)
            key = (id(raster), window.row_off, window.col_off)
            if key in self._pixel_cache:
                self._pixel_cache.move_to_end(key)
                return self._pixel_cache[key]
            data = raster.read(1, window=window, masked=True)
            if _raster_file_signature(source[2]) != signature:
                self._pixel_sources.pop(id(raster), None)
                for old in list(self._pixel_cache):
                    if old[0] == id(raster):
                        del self._pixel_cache[old]
                return raster.read(1, window=window, masked=True)
            # The cache never escapes sample(). Returned elevations stay fresh
            # and writable. Both numeric values and masks belong to this entry.
            data.flags.writeable = False
            if isinstance(data.mask, np.ndarray):
                data.mask.flags.writeable = False
            self._pixel_cache[key] = data
            if len(self._pixel_cache) > _PIXEL_CACHE_MAX_ENTRIES:
                self._pixel_cache.popitem(last=False)
            return data

    def sample(self, lat, lon):
        from rasterio.windows import Window

        lat, lon = np.broadcast_arrays(lat, lon)
        elevation = np.full(lat.shape, np.nan)
        for raster in self.rasters:
            transform = _raster_transformer(raster.crs)
            x, y = transform.transform(lon.ravel(), lat.ravel())
            col,row=(~raster.transform) @ (np.asarray(x),np.asarray(y))
            col,row=np.floor(col).astype(int),np.floor(row).astype(int)
            if lat.size == 1:
                c, r = int(col[0]), int(row[0])
                if 0 <= c < raster.width and 0 <= r < raster.height:
                    # Preserve the exact read window and all reader/source
                    # guards while avoiding vector mask assembly for one pixel.
                    data = self._read_window(raster, Window(c, r, 1, 1))
                    if not np.ma.getmaskarray(data)[0, 0]:
                        elevation.ravel()[0] = np.asarray(data)[0, 0]
                continue
            inside=(col>=0)&(col<raster.width)&(row>=0)&(row<raster.height)
            values=np.ma.masked_all(len(col))
            if np.any(inside):
                rows,cols=row[inside],col[inside]
                r0,c0=int(rows.min()),int(cols.min())
                window=Window(c0,r0,int(cols.max())-c0+1,int(rows.max())-r0+1)
                data=self._read_window(raster,window)
                values[inside]=data[rows-r0,cols-c0]
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


class CopernicusTerrain:
    """Public GLO-90 DSM tiles, cached locally; water-only missing tiles are zero.

    At this CONUS search scope the published tile catalogue covers land. An absent
    tile is accepted as ocean only when it is absent from that catalogue, not when
    a network download fails. EGM2008 DSM heights use the configured geoid grid.
    """
    def __init__(self,cache,geoid_path=None):
        import requests
        self.cache=Path(cache)
        self.cache.mkdir(parents=True,exist_ok=True)
        self.session=requests.Session()
        catalog=self.cache/"tileList.txt"
        if not catalog.exists():
            response=self.session.get("https://copernicus-dem-90m.s3.amazonaws.com/tileList.txt",timeout=60)
            response.raise_for_status();catalog.write_text(response.text)
        self.catalog=set(catalog.read_text().splitlines())
        self.geoid=Terrain([geoid_path]) if geoid_path else None

    def sample(self,lat,lon):
        lat,lon=np.broadcast_arrays(lat,lon)
        shape=lat.shape
        lat,lon=lat.ravel(),lon.ravel()
        degrees=_glo90_tile_degrees(lat,lon)
        tiles,inverse=np.unique(degrees,axis=0,return_inverse=True)
        height=np.zeros(len(lat))
        for index,(north,east) in enumerate(tiles):
            tag=f"Copernicus_DSM_COG_30_{'N' if north>=0 else 'S'}{abs(north):02d}_00_{'E' if east>=0 else 'W'}{abs(east):03d}_00_DEM"
            if tag not in self.catalog and tag+"/" not in self.catalog:
                continue
            path=self.cache/(tag+".tif")
            if not path.exists():
                import fcntl
                with path.with_suffix(".lock").open("a") as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX)
                    if not path.exists():
                        url=f"https://copernicus-dem-90m.s3.amazonaws.com/{tag}/{tag}.tif"
                        r=self.session.get(url,timeout=120);r.raise_for_status()
                        temporary=path.with_suffix(".part");temporary.write_bytes(r.content);temporary.replace(path)
            selected=inverse==index
            sampler=Terrain([path])
            height[selected]=sampler.sample(lat[selected],lon[selected])
            for raster in sampler.rasters:raster.close()
        if self.geoid:height+=self.geoid.sample(lat,lon)
        return height.reshape(shape)


def corridor_grid(tracks, events, spacing_m, terrain, crs="EPSG:5070", bounds=None, time_origin=None,
                  receiver_mask=None):
    """Only materialize grid cells near plausible aircraft segments.

    Coordinates use one shared CRS and grid origin, so overlapping flight corridors
    deduplicate. There is no recording-position prior hidden in grid construction.
    """
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    clipbox=forward.transform_bounds(*bounds,densify_pts=21) if bounds else None
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
            # Padding includes an anchor gap and projection distortion over the
            # supported search regions. It applies to complete aircraft tracks.
            pad = radius * 1.45 + spacing_m
            if clipbox:
                left,bottom,right,top=clipbox
                ax,ay=anchors[:,0]*spacing_m,anchors[:,1]*spacing_m
                anchors=anchors[(ax>=left-pad)&(ax<=right+pad)&(ay>=bottom-pad)&(ay<=top+pad)]
            if not len(anchors):
                continue
            size = int(np.ceil(pad / spacing_m))
            dx, dy = np.meshgrid(np.arange(-size, size+1), np.arange(-size,size+1))
            offsets = np.column_stack((dx.ravel(), dy.ravel()))
            offsets = offsets[np.linalg.norm(offsets, axis=1) * spacing_m <= pad]
            event_cells=[]
            for anchor in anchors:
                expanded=anchor+offsets
                if clipbox:
                    ex,ey=expanded[:,0]*spacing_m,expanded[:,1]*spacing_m
                    expanded=expanded[(ex>=left-spacing_m)&(ex<=right+spacing_m)&
                                      (ey>=bottom-spacing_m)&(ey<=top+spacing_m)]
                if len(expanded):event_cells.append(expanded)
            if event_cells:
                cells.append(np.unique(np.concatenate(event_cells),axis=0))
    if not cells:
        raise ValueError("No flight segments meet event speed/time bounds")
    cells = np.unique(np.concatenate(cells), axis=0)
    x, y = cells[:,0] * spacing_m, cells[:,1] * spacing_m
    lon, lat = inverse.transform(x, y)
    if bounds:
        west, south, east, north = bounds
        keep = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
        x, y, lon, lat = (a[keep] for a in (x,y,lon,lat))
    if receiver_mask is not None:
        keep = receiver_mask.contains(lon, lat)
        x, y, lon, lat = (a[keep] for a in (x, y, lon, lat))
    height = terrain.sample(lat,lon) if len(lat) else np.array([])
    import pandas as pd
    return pd.DataFrame({"point_id": np.arange(len(x)), "x":x, "y":y, "lat":lat, "lon":lon, "elev_m":height})


def refine_grid(points, coarse_spacing, fine_spacing, terrain, crs="EPSG:5070", *,
                bounds=None, receiver_mask=None):
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    radius = int(np.ceil(coarse_spacing / fine_spacing))
    dx, dy = np.meshgrid(np.arange(-radius,radius+1),np.arange(-radius,radius+1))
    offsets = np.column_stack((dx.ravel(),dy.ravel())) * fine_spacing
    coords = np.unique(np.concatenate([np.array([r.x,r.y])+offsets for r in points.itertuples()]),axis=0)
    lon,lat = inverse.transform(coords[:,0],coords[:,1])
    keep = np.ones(len(coords), dtype=bool)
    if bounds is not None:
        west, south, east, north = bounds
        keep &= (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    if receiver_mask is not None:
        keep &= receiver_mask.contains(lon, lat)
    coords, lon, lat = coords[keep], lon[keep], lat[keep]
    import pandas as pd
    return pd.DataFrame({"point_id":np.arange(len(coords)),"x":coords[:,0],"y":coords[:,1],
                         "lat":lat,"lon":lon,"elev_m":terrain.sample(lat,lon) if len(lat) else np.array([])})
