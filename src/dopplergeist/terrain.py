"""Terrain sampling and common projected grids."""
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
from pyproj import Transformer


@lru_cache(maxsize=32)
def _raster_transformer(crs):
    """Reuse a raster's unchanged coordinate operation across refinement calls."""
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True)


class Terrain:
    def __init__(self, paths=None, constant_m=None, geoid_path=None):
        import rasterio
        self.rasters = [rasterio.open(p) for p in (paths or [])]
        self.constant = constant_m
        self.geoid = Terrain([geoid_path]) if geoid_path else None
        # Each sampler, including the optional geoid, retains at most 4 MiB
        # of exact pixels and masks for scalar optimizer evaluations.
        self._scalar_blocks = OrderedDict()
        self._scalar_block_bytes = 0
        self._scalar_cache_limit = 4 * 1024 * 1024
        self._scalar_sources = {}
        if not self.rasters and constant_m is None:
            raise ValueError("Supply DEM raster paths or an explicit constant ground elevation")

    @staticmethod
    def _source_signature(paths):
        result = []
        for path in paths:
            stat = path.stat()
            result.append((stat.st_dev, stat.st_ino, stat.st_size,
                           stat.st_mtime_ns, stat.st_ctime_ns))
        return tuple(result)

    def _scalar_pixel(self, raster, row, col):
        """Return an unchanged pixel and mask, with bounded local-file reuse."""
        from rasterio.io import DatasetReader
        from rasterio.windows import Window

        # Custom readers, writable/closed datasets and virtual sources retain
        # their normal read behavior. A closed reader must not return old pixels.
        cacheable = (self._scalar_cache_limit > 0 and
                     type(raster) is DatasetReader and not raster.closed and
                     raster.mode == "r" and raster.driver == "GTiff")
        if cacheable and raster not in self._scalar_sources:
            paths = tuple(Path(path) for path in raster.files)
            try:
                signature = self._source_signature(paths) if paths else None
            except OSError:
                signature = None
            self._scalar_sources[raster] = ((paths, signature)
                                             if signature is not None else None)
        source = self._scalar_sources.get(raster) if cacheable else None
        if source is None:
            data = raster.read(1, window=Window(col, row, 1, 1), masked=True)
            return np.asarray(data)[0, 0], np.ma.getmaskarray(data)[0, 0]

        paths, signature = source
        try:
            unchanged = self._source_signature(paths) == signature
        except OSError:
            unchanged = False
        if not unchanged:
            raise ValueError(f"Terrain raster changed after caching: {raster.name}")

        # Keep windows inside the same underlying storage block as the requested
        # pixel, including striped TIFFs and blocks not divisible by 64.
        size = 64
        block_h, block_w = raster.block_shapes[0]
        block_r, block_c = row // block_h * block_h, col // block_w * block_w
        r0 = block_r + (row-block_r) // size * size
        c0 = block_c + (col-block_c) // size * size
        key = (raster, r0, c0)
        entry = self._scalar_blocks.get(key)
        if entry is None:
            height = min(size, block_r+block_h-r0, raster.height-r0)
            width = min(size, block_c+block_w-c0, raster.width-c0)
            data = raster.read(1, window=Window(c0, r0, width, height), masked=True)
            pixels, mask = np.asarray(data), np.ma.getmaskarray(data)
            try:
                unchanged = self._source_signature(paths) == signature
            except OSError:
                unchanged = False
            if not unchanged:
                raise ValueError(f"Terrain raster changed while reading: {raster.name}")
            byte_count = pixels.nbytes + mask.nbytes
            if byte_count <= self._scalar_cache_limit:
                while self._scalar_blocks and (
                        self._scalar_block_bytes + byte_count > self._scalar_cache_limit or
                        len(self._scalar_blocks) >= 256):
                    _, old = self._scalar_blocks.popitem(last=False)
                    self._scalar_block_bytes -= old[0].nbytes + old[1].nbytes
                pixels.flags.writeable = False
                mask.flags.writeable = False
                self._scalar_blocks[key] = (pixels, mask)
                self._scalar_block_bytes += byte_count
        else:
            self._scalar_blocks.move_to_end(key)
            pixels, mask = entry
        return pixels[row-r0, col-c0], mask[row-r0, col-c0]

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
                    value, masked = self._scalar_pixel(raster, r, c)
                    if not masked:
                        elevation.ravel()[0] = value
                continue
            inside=(col>=0)&(col<raster.width)&(row>=0)&(row<raster.height)
            values=np.ma.masked_all(len(col))
            if np.any(inside):
                rows,cols=row[inside],col[inside]
                r0,c0=int(rows.min()),int(cols.min())
                window=Window(c0,r0,int(cols.max())-c0+1,int(rows.max())-r0+1)
                data=raster.read(1,window=window,masked=True)
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
        degrees=np.column_stack((np.floor(lat).astype(int),np.floor(lon).astype(int)))
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


def corridor_grid(tracks, events, spacing_m, terrain, crs="EPSG:5070", bounds=None, time_origin=None):
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
            # EPSG:5070 grid scale is close to unity over CONUS; 10% padding
            # plus an anchor gap protects corridor coverage under distortion.
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
