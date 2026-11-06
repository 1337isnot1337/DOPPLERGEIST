from functools import lru_cache
from importlib.resources import files
import json
import math
from pathlib import Path
import shutil


class RegionPolicyUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _boundaries():
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    try:
        data = json.loads(
            files("dopplergeist").joinpath("data", "region_boundaries.json").read_text(encoding="utf-8")
        )
        regions = data["regions"]
        result = {}
        for name in ("ukraine", "occupied_ukraine", "israel", "gaza"):
            geometry = shape(regions[name])
            if geometry.is_empty:
                raise ValueError(name)
            if isinstance(geometry, MultiPolygon):
                geometry = unary_union(list(geometry.geoms))
            if not geometry.is_valid:
                geometry = make_valid(geometry)
            if isinstance(geometry, GeometryCollection):
                polygons = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon))]
                geometry = unary_union(polygons)
            if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty or not geometry.is_valid:
                raise ValueError(name)
            result[name] = geometry
        if data.get("occupation_date") != "2026-11-05":
            raise ValueError("occupation_date")
        return result
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RegionPolicyUnavailable("Regional boundary data are unavailable.") from exc


class ResultRegionPolicy:
    def __init__(self):
        self.boundaries = _boundaries()

    def restricted_region(self, lat, lon):
        from shapely.geometry import Point

        if (isinstance(lat, bool) or isinstance(lon, bool)
                or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float))
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError("Candidate must have finite geographic coordinates.")
        point = Point(lon, lat)
        if self.boundaries["occupied_ukraine"].covers(point):
            return None
        if self.boundaries["ukraine"].covers(point):
            return "ukraine"
        if self.boundaries["israel"].covers(point) or self.boundaries["gaza"].covers(point):
            return "israel_gaza"
        return None


def redact_location_outputs(output_dir):
    output = Path(output_dir)
    for name in ("search", "refined-candidates.json", "decision.json", "spectral-comparison.json", "ranked-grid.json", "ranked.json", "flight-combinations.json", "report.json", "location-scores.png", "model-support.json", "support"):
        path = output / name
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
