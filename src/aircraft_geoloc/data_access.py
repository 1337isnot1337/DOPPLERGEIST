"""Validated historical inputs and disk-backed whole-segment spatial/time queries.

These are internal data adapters, not a second pipeline request/result contract.
Coverage describes the *source query*, never receiver/network completeness.
"""
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tarfile

import numpy as np
import pandas as pd
import requests

from .geometry import Track, velocity_ecef
from .tracks import adsblol_frame

CONUS = (-125.0, 24.0, -66.0, 50.0)
INDEX_VERSION = 2


def _frame_track(name, frame):
    from . import tracks as normalizer
    velocity, inferred = None, {}
    if hasattr(normalizer, "_segment_velocity"):
        velocity, inferred = normalizer._segment_velocity(frame)
    else:
        cols = ["east_mps", "north_mps", "up_mps"]
        if set(cols).issubset(frame) and np.isfinite(frame[cols].to_numpy(dtype=float)).all():
            velocity = velocity_ecef(frame.lat.to_numpy(), frame.lon.to_numpy(), *[frame[c].to_numpy() for c in cols])
    track = Track(name, frame.time_s.to_numpy(), frame.lat.to_numpy(), frame.lon.to_numpy(), frame.alt_m.to_numpy(),
                  str(frame.typecode.iloc[0] or "") if "typecode" in frame else "", velocity)
    track.altitude_basis = frame.altitude_basis.tolist() if "altitude_basis" in frame else ["unspecified"] * len(frame)
    track.aircraft_class = frame.aircraft_class.iloc[0] if "aircraft_class" in frame else "unclassified"
    track.velocity_inferred_components = inferred
    return track


def _continuous_bounds(track):
    """Bound entire Hermite curves using their cubic Bezier control hulls.

    Each curve lies inside a ball enclosing its four ECEF control points.
    Longitude extrema of that ball are analytic; latitude uses a conservative
    5500 km lower bound on geodetic curvature radii outside the 6000 km sphere.
    Invalid/underground extreme curves fall back to a global box, never a miss.
    """
    from pyproj import Transformer
    p0, p1 = track.xyz[:-1], track.xyz[1:]
    dt = np.diff(track.time)[:, None]
    velocity = track.speed_vector(track.time)
    controls = np.stack((p0, p0 + velocity[:-1] * dt / 3, p1 - velocity[1:] * dt / 3, p1), axis=1)
    centers = (p0 + p1) / 2
    radius = np.linalg.norm(controls - centers[:, None, :], axis=2).max(axis=1)
    if np.any(np.linalg.norm(centers, axis=1) - radius < 6000000):
        return (-180., 180., -90., 90.)
    lon, lat, _ = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True).transform(*centers.T)
    latitude_pad = np.rad2deg(radius / 5500000)
    horizontal = np.linalg.norm(centers[:, :2], axis=1)
    if np.any(radius >= horizontal):
        return (-180., 180., max(-90., float(np.min(lat - latitude_pad))), min(90., float(np.max(lat + latitude_pad))))
    longitude_pad = np.rad2deg(np.arcsin(radius / horizontal))
    west, east = float(np.min(lon-longitude_pad)), float(np.max(lon+longitude_pad))
    if west < -180 or east > 180:
        west, east = -180., 180.
    return (west, east, max(-90., float(np.min(lat-latitude_pad))), min(90., float(np.max(lat+latitude_pad))))


class DataUnavailable(RuntimeError):
    """Missing/corrupt provider input; distinct from an acoustic non-detection."""


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


@contextmanager
def cache_lock(path):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def download(url, path, *, size=None, digest=None, offline=False, session=None):
    """Resume only verified byte ranges; atomically publish validated files.

    A provider SHA-256 is preferred. Otherwise a locally computed hash receipt
    detects subsequent cache corruption, but does not authenticate the provider.
    """
    path = Path(path)
    receipt = path.with_name(path.name + ".sha256.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with cache_lock(path.with_name(path.name + ".lock")):
        if path.exists():
            actual = sha256(path)
            expected = digest or (json.loads(receipt.read_text())["sha256"] if receipt.exists() else None)
            if size is not None and path.stat().st_size != size:
                raise DataUnavailable(f"Truncated cache: {path}")
            if expected is None or actual != expected:
                raise DataUnavailable(f"Unvalidated or corrupt cache: {path}")
            return {"url": url, "path": str(path), "sha256": actual, "bytes": path.stat().st_size}
        if offline:
            raise DataUnavailable(f"Offline cache miss: {path}")
        temporary = path.with_name(path.name + ".part")
        offset = temporary.stat().st_size if temporary.exists() else 0
        headers = {"Range": f"bytes={offset}-", "Accept-Encoding": "identity"} if offset else {"Accept-Encoding": "identity"}
        try:
            with (session or requests).get(url, headers=headers, stream=True, timeout=(30, 120)) as response:
                response.raise_for_status()
                if offset and (response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-")):
                    raise DataUnavailable("Provider did not honor requested byte range; partial preserved")
                with temporary.open("ab" if offset else "wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        stream.write(chunk)
                expected_size = size
                if expected_size is None and response.headers.get("Content-Length"):
                    expected_size = offset + int(response.headers["Content-Length"])
            if expected_size is not None and temporary.stat().st_size != expected_size:
                raise DataUnavailable(f"Truncated download, rerun to resume: {temporary}")
            actual = sha256(temporary)
            if digest and actual != digest:
                raise DataUnavailable(f"Provider checksum mismatch: {temporary}")
            temporary.replace(path)
            result = {"url": url, "path": str(path), "sha256": actual, "bytes": path.stat().st_size}
            write_json(receipt, result)
            return result
        except requests.RequestException as error:
            raise DataUnavailable(f"Download failed: {url}: {error}") from error


class SplitReader(io.RawIOBase):
    """Read archive parts as one stream without copying/extracting the archive."""
    def __init__(self, paths):
        self.paths, self.current = iter(paths), None

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    return 0
                self.current = Path(path).open("rb")
            count = self.current.readinto(buffer)
            if count:
                return count
            self.current.close()
            self.current = None

    def close(self):
        if self.current:
            self.current.close()
        super().close()


def archive_frames(paths, max_member_bytes=64 * 1024 * 1024):
    """Preserve all types, full geometry and altitude labels before indexing."""
    try:
        with io.BufferedReader(SplitReader(paths)) as stream:
            with tarfile.open(fileobj=stream, mode="r|*") as archive:
                for member in archive:
                    if not member.isfile() or "trace_full_" not in member.name:
                        continue
                    if member.size > max_member_bytes:
                        raise DataUnavailable(f"Oversized trace member: {member.name}")
                    raw = archive.extractfile(member).read()
                    if raw[:2] == b"\x1f\x8b":
                        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                            raw = compressed.read(max_member_bytes + 1)
                        if len(raw) > max_member_bytes:
                            raise DataUnavailable(f"Oversized expanded trace: {member.name}")
                    frame = adsblol_frame(json.loads(raw))
                    if not frame.empty:
                        yield frame
    except (tarfile.TarError, EOFError, OSError, ValueError) as error:
        raise DataUnavailable(f"Invalid/truncated ADS-B archive: {error}") from error


class FlightIndex:
    """SQLite R-tree of complete, gap-split flight segments; lazy payload reads."""
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            raise DataUnavailable(f"Missing flight index: {path}")
        try:
            with self.connect() as db:
                self.report = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
            if self.report["index_version"] not in (1, INDEX_VERSION):
                raise DataUnavailable("Flight index version mismatch")
        except (sqlite3.DatabaseError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise DataUnavailable(f"Invalid flight index: {path}") from error

    def connect(self):
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)

    @classmethod
    def build(cls, path, frames, *, sources, coverage, max_gap_s=30.0, max_flight_samples=250000, class_map=None):
        """Disk staging permits arbitrary source order without whole-table RAM.

        Explicit source coverage is required: cropped or prop-only historical
        data must never become an apparently complete national all-type index.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        class_map = class_map or {}
        identity = {"index_version": INDEX_VERSION, "sources": sources, "coverage": coverage,
                    "normalizer_sha256": sha256(Path(__file__).with_name("tracks.py")),
                    "classification_map_hash": content_hash(class_map),
                    "max_gap_s": max_gap_s, "max_flight_samples": max_flight_samples}
        with cache_lock(path.with_suffix(".lock")):
            if path.exists():
                result = cls(path)
                if result.report["input_hash"] != content_hash(identity):
                    raise DataUnavailable("Existing flight index has different inputs/configuration")
                return result
            temporary = path.with_suffix(".building")
            temporary.unlink(missing_ok=True)
            db = sqlite3.connect(temporary)
            try:
                db.executescript("""
                    PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-16384;
                    PRAGMA temp_store=FILE;
                    CREATE TABLE samples(flight TEXT, time REAL, row TEXT);
                    CREATE TABLE segments(id INTEGER PRIMARY KEY, name TEXT UNIQUE, start REAL, end REAL,
                        payload BLOB, payload_hash TEXT);
                    CREATE VIRTUAL TABLE spatial USING rtree(id, west, east, south, north);
                    CREATE INDEX time_index ON segments(start,end);
                    CREATE TABLE metadata(value TEXT);
                """)
                rows, invalid, altitude = 0, 0, Counter()
                for frame in frames:
                    required = ["flight_id", "time_s", "lat", "lon", "alt_m"]
                    if not set(required).issubset(frame):
                        raise DataUnavailable(f"Missing canonical columns: {required}")
                    valid = np.isfinite(frame[["time_s", "lat", "lon", "alt_m"]].to_numpy(dtype=float)).all(axis=1)
                    valid &= frame.lat.between(-90, 90) & frame.lon.between(-180, 180) & frame.flight_id.notna()
                    invalid += int((~valid).sum())
                    clean = frame.loc[valid]
                    clean = clean.copy()
                    clean["aircraft_class"] = clean.typecode.map(class_map).fillna("unclassified") if "typecode" in clean else "unclassified"
                    altitude.update(clean.altitude_basis.value_counts().to_dict() if "altitude_basis" in clean else {"unspecified": len(clean)})
                    # pandas normalizes numpy scalars/NaNs to JSON numbers/null.
                    records = json.loads(clean.to_json(orient="records", double_precision=15))
                    db.executemany("INSERT INTO samples VALUES(?,?,?)", [(str(r["flight_id"]), r["time_s"], json.dumps(r)) for r in records])
                    rows += len(records)
                db.execute("CREATE INDEX flight_samples ON samples(flight,time)")
                db.commit()
                segments = 0
                for (flight,) in db.execute("SELECT DISTINCT flight FROM samples ORDER BY flight"):
                    count = db.execute("SELECT count(*) FROM samples WHERE flight=?", (flight,)).fetchone()[0]
                    if count > max_flight_samples:
                        raise DataUnavailable(f"Flight {flight} exceeds {max_flight_samples} sample memory limit")
                    records = [json.loads(r[0]) for r in db.execute("SELECT row FROM samples WHERE flight=? ORDER BY time,rowid", (flight,))]
                    frame = pd.DataFrame(records).drop_duplicates("time_s")
                    groups = (frame.time_s.diff() > max_gap_s).cumsum()
                    for index, (_, chunk) in enumerate(frame.groupby(groups)):
                        if len(chunk) < 3:
                            continue
                        namespace = coverage.get("release_tag", "")
                        name = flight + (f"@{namespace}" if namespace else "") + (f":{index}" if groups.max() else "")
                        track = _frame_track(name, chunk)
                        payload = gzip.compress(chunk.to_json(orient="records", double_precision=15).encode(), mtime=0)
                        cur = db.execute("INSERT INTO segments(name,start,end,payload,payload_hash) VALUES(?,?,?,?,?)",
                                         (name, float(chunk.time_s.iloc[0]), float(chunk.time_s.iloc[-1]), payload, hashlib.sha256(payload).hexdigest()))
                        db.execute("INSERT INTO spatial VALUES(?,?,?,?,?)", (cur.lastrowid, *_continuous_bounds(track)))
                        segments += 1
                db.execute("DROP TABLE samples")
                report = dict(identity, input_hash=content_hash(identity), rows=rows, invalid_rows=invalid,
                              segments=segments, altitude_basis_counts=dict(altitude), jets_excluded=False,
                              unknown_types_retained=True, geometry_clipped=False, continuous_geometry_bounds=True)
                db.execute("INSERT INTO metadata VALUES(?)", (json.dumps(report),))
                db.commit()
                db.execute("VACUUM")
                db.close()
                temporary.replace(path)
                return cls(path)
            except BaseException:
                db.close()
                temporary.unlink(missing_ok=True)
                raise

    @classmethod
    def from_parquet(cls, path, parquet, *, coverage, **kwargs):
        import pyarrow.parquet as pq
        parquet = Path(parquet)
        source = {"path": str(parquet.resolve()), "sha256": sha256(parquet), "bytes": parquet.stat().st_size}
        try:
            frames = (batch.to_pandas() for batch in pq.ParquetFile(parquet).iter_batches(batch_size=16384))
            return cls.build(path, frames, sources=[source], coverage=coverage, **kwargs)
        except (OSError, ValueError) as error:
            raise DataUnavailable(f"Invalid/truncated Parquet: {parquet}: {error}") from error

    def query(self, bounds, time_range):
        """Yield complete segments touching the query, retaining gaps and labels.

        Callers expand receiver bounds for acoustic range and event duration.
        An R-tree rectangle can return harmless extra tracks, never clipped ones.
        """
        west, south, east, north = bounds
        start, end = time_range
        with self.connect() as db:
            sql = """SELECT s.name,s.payload,s.payload_hash FROM segments s JOIN spatial r ON s.id=r.id
                WHERE r.west<=? AND r.east>=? AND r.south<=? AND r.north>=?
                AND s.start<=? AND s.end>=? ORDER BY s.name"""
            params = (east, west, north, south, end, start)
            if (not self.report.get("continuous_geometry_bounds") or
                    self.report.get("normalizer_sha256") != sha256(Path(__file__).with_name("tracks.py"))):
                # Old indexes used sample-only bounds or different derivatives.
                # Disable unsafe spatial pruning, preserving explicit budgets.
                sql = "SELECT name,payload,payload_hash FROM segments WHERE start<=? AND end>=? ORDER BY name"
                params = (end, start)
            for name, payload, expected in db.execute(sql, params):
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise DataUnavailable(f"Corrupt flight payload: {name}")
                frame = pd.DataFrame(json.loads(gzip.decompress(payload)))
                yield _frame_track(name, frame)

    def coverage_for(self, bounds, time_range):
        source = self.report["coverage"]
        box, times = source["bounds"], source["time_range_s"]
        complete = (box[0] <= bounds[0] <= bounds[2] <= box[2] and box[1] <= bounds[1] <= bounds[3] <= box[3]
                    and times[0] <= time_range[0] <= time_range[1] <= times[1] and source.get("all_aircraft", False))
        return {"requested_bounds": list(bounds), "requested_time_range_s": list(time_range),
                "source": source, "scope_complete": bool(complete), "receiver_completeness_known": False,
                "input_hash": self.report["input_hash"]}


class FlightCache:
    """Date-to-index acquisition; immutable index per source/version/scope."""
    def __init__(self, root, *, offline=False, session=None):
        self.root, self.offline = Path(root), offline
        self.session = session or requests.Session()

    def acquire_day(self, day, *, provider="staging-0"):
        from . import tracks as normalizer
        day = date.fromisoformat(day)
        tag = f"v{day:%Y.%m.%d}-planes-readsb-{provider}"
        directory = self.root / day.isoformat() / provider
        directory.mkdir(parents=True, exist_ok=True)
        normalizer_hash = sha256(normalizer.__file__)
        index = directory / f"all-types-v{INDEX_VERSION}-{normalizer_hash[:12]}.sqlite"
        if index.exists():
            return FlightIndex(index)
        release_path = directory / "release.json"
        if not release_path.exists():
            if self.offline:
                raise DataUnavailable(f"Offline release metadata missing: {day}")
            try:
                response = self.session.get(f"https://api.github.com/repos/adsblol/globe_history_{day.year}/releases/tags/{tag}", timeout=60)
                response.raise_for_status()
                write_json(release_path, response.json())
            except requests.RequestException as error:
                raise DataUnavailable(f"Historical release unavailable: {day}") from error
        release = json.loads(release_path.read_text())
        assets = sorted((a for a in release["assets"] if ".tar." in a["name"]), key=lambda a: a["name"])
        if not assets:
            raise DataUnavailable("Release has no split trace archive")
        sources = []
        for asset in assets:
            digest = asset.get("digest")
            if digest and not digest.startswith("sha256:"):
                raise DataUnavailable("Unsupported archive digest algorithm")
            sources.append(download(asset["browser_download_url"], directory / asset["name"], size=asset["size"],
                                    digest=digest.split(":", 1)[1] if digest else None, offline=self.offline, session=self.session))
        start = pd.Timestamp(day.isoformat(), tz="UTC").timestamp()
        coverage = {"bounds": [-180, -90, 180, 90], "time_range_s": [start, start + 86400],
                    "all_aircraft": True, "provider": "ADSB.lol", "release_tag": tag,
                    "release_sha256": sha256(release_path), "license": "ODbL", "missing_receiver_data_possible": True}
        coverage["normalizer_sha256"] = normalizer_hash
        types_path = self.root / "icao_aircraft_types.js"
        type_source = download("https://raw.githubusercontent.com/wiedehopf/tar1090-db/master/db/icao_aircraft_types.js",
                               types_path, offline=self.offline, session=self.session)
        raw = types_path.read_bytes()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        text = raw.decode()
        types = json.loads(text[text.index("{"):text.rindex("}") + 1])
        class_map = {}
        for code, value in types.items():
            description = value.get("desc", "") if isinstance(value, dict) else (value[2] if len(value) > 2 else "")
            class_map[code] = {"J": "jet", "T": "turboprop", "P": "piston"}.get(description[-1:], "unclassified")
        return FlightIndex.build(index, archive_frames([s["path"] for s in sources]), sources=sources + [type_source],
                                 coverage=coverage, class_map=class_map)


class CachedTerrain:
    """GLO-90 + EGM2008 with explicit offline operation and file provenance.

    Only catalogue-absent tiles are treated as ocean. Download errors and raster
    nodata remain missing coverage. Existing operator-supplied cache files can be
    adopted explicitly after format validation; receipts then detect corruption.
    """
    base = "https://copernicus-dem-90m.s3.amazonaws.com"

    def __init__(self, root, *, offline=False, geoid_path=None, adopt_existing=False):
        self.root, self.offline = Path(root), offline
        self.root.mkdir(parents=True, exist_ok=True)
        self.files, self.ocean_tiles, self.failures = {}, set(), []
        self.adopt_existing = adopt_existing
        catalog = self.root / "tileList.txt"
        self._file(self.base + "/tileList.txt", catalog, raster=False)
        self.catalog = {line.rstrip("/") for line in catalog.read_text().splitlines()}
        if not self.catalog or not all(s.startswith("Copernicus_DSM_COG_30_") for s in self.catalog):
            raise DataUnavailable("Invalid GLO-90 catalogue")
        self.geoid_path = Path(geoid_path) if geoid_path else self.root / "us_nga_egm08_25.tif"
        self._file("https://cdn.proj.org/us_nga_egm08_25.tif", self.geoid_path, raster=True)

    def _file(self, url, path, *, raster):
        if path.name in self.files:
            return path
        receipt = path.with_name(path.name + ".sha256.json")
        if path.exists() and not receipt.exists() and self.adopt_existing:
            if raster:
                import rasterio
                with rasterio.open(path) as dataset:
                    dataset.read(1, window=((0, 1), (0, 1)))
            write_json(receipt, {"sha256": sha256(path), "origin": "operator-supplied-cache", "url": url})
        result = download(url, path, offline=self.offline)
        if raster:
            import rasterio
            try:
                with rasterio.open(path) as dataset:
                    dataset.read(1, window=((0, 1), (0, 1)))
            except rasterio.errors.RasterioError as error:
                raise DataUnavailable(f"Invalid terrain raster: {path}") from error
        self.files[path.name] = result
        return path

    def sample(self, lat, lon):
        lat, lon = np.broadcast_arrays(lat, lon)
        shape = lat.shape
        lat, lon = lat.ravel(), lon.ravel()
        # Published COG tiles omit the original bottom/right overlap pixels.
        # Their outer edges are shifted north/west by half a GLO90 pixel.
        degrees = np.column_stack((np.floor(lat - 1 / 2400).astype(int), np.floor(lon + 1 / 2400).astype(int)))
        self.last_sample_files = {"tileList.txt", self.geoid_path.name}
        tiles, inverse = np.unique(degrees, axis=0, return_inverse=True)
        height = np.zeros(len(lat))
        try:
            for i, (north, east) in enumerate(tiles):
                tag = f"Copernicus_DSM_COG_30_{'N' if north >= 0 else 'S'}{abs(north):02d}_00_{'E' if east >= 0 else 'W'}{abs(east):03d}_00_DEM"
                if tag not in self.catalog:
                    self.ocean_tiles.add(tag)
                    continue
                path = self._file(f"{self.base}/{tag}/{tag}.tif", self.root / f"{tag}.tif", raster=True)
                self.last_sample_files.add(path.name)
                selected = inverse == i
                height[selected] = self._raster_sample(path, lat[selected], lon[selected])
            height += self._raster_sample(self.geoid_path, lat, lon)
        except (DataUnavailable, ValueError) as error:
            self.failures.append(str(error))
            raise DataUnavailable(f"Terrain coverage unavailable: {error}") from error
        return height.reshape(shape)

    @staticmethod
    def _raster_sample(path, lat, lon):
        """Read only the local pixel window, including for the global geoid."""
        import rasterio
        from rasterio.windows import Window
        from pyproj import Transformer
        if not len(lat):
            return np.array([])
        try:
            with rasterio.open(path) as raster:
                x, y = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True).transform(lon, lat)
                col, row = (~raster.transform) @ (np.asarray(x), np.asarray(y))
                col, row = np.floor(col).astype(int), np.floor(row).astype(int)
                if np.any((col < 0) | (col >= raster.width) | (row < 0) | (row >= raster.height)):
                    raise DataUnavailable(f"Raster extent missing candidate points: {path}")
                left, top, right, bottom = int(col.min()), int(row.min()), int(col.max()), int(row.max())
                data = raster.read(1, window=Window(left, top, right-left+1, bottom-top+1), masked=True)
                values = data[row-top, col-left]
                if np.ma.getmaskarray(values).any() or not np.isfinite(values).all():
                    raise DataUnavailable(f"Raster nodata at candidate points: {path}")
                return np.asarray(values, dtype=float)
        except rasterio.errors.RasterioError as error:
            raise DataUnavailable(f"Cannot sample terrain raster: {path}") from error

    def provenance(self):
        return {"provider": "Copernicus GLO-90", "vertical_datum": "EGM2008 converted to ellipsoidal",
                "files": list(self.files.values()), "catalogue_absent_ocean_tiles": sorted(self.ocean_tiles),
                "failures": list(self.failures), "offline": self.offline}


@dataclass
class AcquiredInputs:
    indexes: list
    terrain: object
    bounds: tuple
    time_range_s: tuple
    recording_start_window_s: tuple
    coverage: dict


def acquire_inputs(request, recording, *, cache_root, index_paths=None, offline=False,
                   terrain_options=None, max_sound_range_m=20000.0):
    """Contract adapter for orchestration; no hand-prepared Parquet is required.

    `index_paths` is an operator-owned explicit offline override, not a user
    search input. Its source scope remains visible. The default obtains complete
    daily all-type archives once and reuses their disk indexes on later jobs.
    """
    from .contracts import utc_timestamp, validate_request, validate_recording
    request, recording = validate_request(request), validate_recording(recording)
    window = request.get("time_window") or recording.get("time_window")
    if window is None:
        raise ValueError("A defensible recording-start time window is required")
    start, end = (utc_timestamp(window[k]).timestamp() for k in ("start_utc", "end_utc"))
    times = (start - max_sound_range_m / 300.0 - 30.0, end + recording["duration_s"] + 30.0)
    root = Path(cache_root)
    if index_paths:
        indexes = [FlightIndex(path) for path in index_paths]
    else:
        cache = FlightCache(root / "flights", offline=offline)
        first, last = (datetime.fromtimestamp(t, timezone.utc).date() for t in times)
        indexes = []
        day = first
        while day <= last:
            indexes.append(cache.acquire_day(day.isoformat()))
            day += timedelta(days=1)
    bounds = tuple(request["search"].get("bounds_wsen", CONUS))
    options = dict(terrain_options or {})
    terrain = CachedTerrain(root / "terrain", offline=offline, **options)
    coverage = {"requested_area": request["search"], "sources": [i.coverage_for(bounds, times) for i in indexes],
                "limitations": ["ADS-B receiver completeness is unknown; unobserved flights remain possible.",
                                "Copernicus is a surface model and cannot establish microphone height."]}
    return AcquiredInputs(indexes, terrain, bounds, times, (start, end), coverage)
