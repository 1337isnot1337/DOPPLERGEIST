#!/usr/bin/env python3
"""Regenerate world_profiles.py and its docs/COUNTRIES.md list from Natural Earth.

    python scripts/build_world_profiles.py ne_10m_admin_0_countries.geojson

Input: Natural Earth 1:10m Admin 0 - Countries, v5.1.2 (public domain),
https://github.com/nvkelso/natural-earth-vector/blob/v5.1.2/geojson/ne_10m_admin_0_countries.geojson

For every feature with an ISO 3166-1 alpha-2 code (``ISO_A2_EH``) that is not
already a hand-written profile:

* Envelope: start from the largest polygon and add polygons whose bounding box
  is within 500 km of the growing envelope, so remote overseas territories do
  not stretch the receiver rectangle across an ocean. The result is padded by
  0.05 degrees and rounded outward to 0.01 degrees. Polygons on the other side
  of the antimeridian are never joined (antimeridian crossing is unsupported).
* CRS: among non-deprecated EPSG projected CRSs (excluding the recent 10000-10999 range, which older
  PROJ databases lack) in metres whose EPSG area of use contains the
  envelope, plus the global EPSG:6933 used by Spain, choose the smallest
  maximum point-scale error over a 15 x 15 sample of the envelope. A candidate
  must round-trip exactly from WGS 84 and its datum must lie within 5 m of
  WGS 84, which rules out classical datums with inconsistent shifts. When no
  such EPSG CRS keeps the error within 2%, a WGS 84 Lambert azimuthal
  equal-area, Lambert conformal conic or transverse Mercator projection centred
  on the envelope is used instead if it does better. The error is recorded
  with the profile.
* Continent: Natural Earth ``CONTINENT``; open-ocean features use ``REGION_UN``.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import unicodedata

HAND_WRITTEN = {"US", "DE", "ES", "FR", "IT", "NO"}
EXCLUDED = {"AQ"}  # Antarctica: no national receiver region; polar envelope.
JOIN_KM = 500.0
EPSG_MAX_SCALE_ERROR = 0.02
PAD_DEG = 0.05
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "dopplergeist" / "world_profiles.py"
DOCS = Path(__file__).resolve().parents[1] / "docs" / "COUNTRIES.md"
DOCS_START, DOCS_END = "<!-- world-profiles:start -->", "<!-- world-profiles:end -->"
REGION_TO_CONTINENT = {"Africa": "Africa", "Asia": "Asia", "Americas": "South America",
                       "Europe": "Europe", "Oceania": "Oceania"}


def _gap_km(a, b):
    """Approximate distance between two lon/lat boxes (west, south, east, north)."""
    dlat = max(0.0, b[1] - a[3], a[1] - b[3])
    dlon = max(0.0, b[0] - a[2], a[0] - b[2])
    lat = math.radians(min(89.0, abs(a[1] + a[3] + b[1] + b[3]) / 4))
    return math.hypot(dlat * 111.2, dlon * 111.2 * math.cos(lat))


def envelope(geometry):
    from shapely.geometry import shape
    parts = sorted(getattr(shape(geometry), "geoms", [shape(geometry)]), key=lambda p: -p.area)
    box = list(parts[0].bounds)
    remaining = [p.bounds for p in parts[1:]]
    changed = True
    while changed:
        changed = False
        for bounds in list(remaining):
            if _gap_km(box, bounds) <= JOIN_KM:
                box = [min(box[0], bounds[0]), min(box[1], bounds[1]),
                       max(box[2], bounds[2]), max(box[3], bounds[3])]
                remaining.remove(bounds)
                changed = True
    w, s, e, n = box
    return (max(-180.0, math.floor((w - PAD_DEG) * 100) / 100),
            max(-89.0, math.floor((s - PAD_DEG) * 100) / 100),
            min(180.0, math.ceil((e + PAD_DEG) * 100) / 100),
            min(89.0, math.ceil((n + PAD_DEG) * 100) / 100))


def _max_scale_error(proj, bounds):
    import numpy as np
    w, s, e, n = bounds
    lon, lat = np.meshgrid(np.linspace(w, e, 15), np.linspace(s, n, 15))
    try:
        factors = proj.get_factors(lon.ravel(), lat.ravel())
    except Exception:
        return math.inf
    h, k = np.asarray(factors.meridional_scale), np.asarray(factors.parallel_scale)
    if not (np.isfinite(h).all() and np.isfinite(k).all()):
        return math.inf
    return float(max(np.abs(h - 1).max(), np.abs(k - 1).max()))


def _usable(crs, bounds):
    """Metric, exactly invertible from WGS 84, and datum within 5 m of WGS 84."""
    import numpy as np
    from pyproj import Transformer
    if {axis.unit_name for axis in crs.axis_info} != {"metre"} or crs.geodetic_crs is None:
        return False
    w, s, e, n = bounds
    lon, lat = (a.ravel() for a in np.meshgrid(np.linspace(w, e, 7), np.linspace(s, n, 7)))
    try:
        datum = Transformer.from_crs("EPSG:4326", crs.geodetic_crs, always_xy=True)
        dlon, dlat = datum.transform(lon, lat)
        shift_m = np.hypot((dlon - lon) * 111320 * np.cos(np.radians(lat)), (dlat - lat) * 110540)
        forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        x, y = forward.transform(lon, lat)
        x2, y2 = forward.transform(*inverse.transform(x, y))
    except Exception:
        return False
    return bool(np.isfinite(shift_m).all() and shift_m.max() <= 5.0
                and np.isfinite([x, y]).all() and np.abs(x2 - x).max() < 1e-4 and np.abs(y2 - y).max() < 1e-4)


def choose_crs(bounds):
    from pyproj import CRS, Proj
    from pyproj.aoi import AreaOfInterest
    from pyproj.database import query_crs_info
    w, s, e, n = bounds
    infos = query_crs_info(auth_name="EPSG", pj_types="PROJECTED_CRS", contains=True,
                           area_of_interest=AreaOfInterest(w, s, e, n))
    # Codes 10000-10999 are recent EPSG additions that older PROJ databases lack.
    codes = {info.code for info in infos if not info.deprecated and not 10000 <= int(info.code) < 11000} | {"6933"}
    best = None
    for code in sorted(codes, key=int):
        crs = CRS.from_epsg(int(code))
        area = crs.area_of_use
        if area is None or not (area.west <= w < e <= area.east and area.south <= s < n <= area.north):
            continue
        try:
            proj = Proj(crs)
        except Exception:  # Not expressible as a PROJ projection string.
            continue
        error = _max_scale_error(proj, bounds)
        if (best is None or error < best[0] - 1e-9) and _usable(crs, bounds):
            best = (error, f"EPSG:{code}")
    if best is not None and best[0] <= EPSG_MAX_SCALE_ERROR:
        return best[1], best[0]
    for crs in _local_candidates(bounds):
        error = _max_scale_error(Proj(CRS(crs)), bounds)
        if (best is None or error < best[0] - 1e-9) and _usable(CRS(crs), bounds):
            best = (error, crs)
    if best is None or not math.isfinite(best[0]):
        raise ValueError(f"No usable projected CRS for {bounds}")
    return best[1], best[0]


def _local_candidates(bounds):
    """WGS 84 projections centred on the envelope, for countries no EPSG CRS fits well."""
    from pyproj import CRS, Proj
    w, s, e, n = bounds
    lon0, lat0 = round((w + e) / 2, 2), round((s + n) / 2, 2)
    tail = "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs"
    yield f"+proj=laea +lat_0={lat0:g} +lon_0={lon0:g} {tail}"
    if s * n > 0:
        lat1, lat2 = round(s + (n - s) / 6, 2), round(n - (n - s) / 6, 2)
        yield f"+proj=lcc +lat_0={lat0:g} +lon_0={lon0:g} +lat_1={lat1:g} +lat_2={lat2:g} {tail}"
    # Transverse Mercator with the central scale chosen to split the error.
    unscaled = f"+proj=tmerc +lat_0=0 +lon_0={lon0:g} +k=1 {tail}"
    error = _max_scale_error(Proj(CRS(unscaled)), bounds)
    if math.isfinite(error):
        yield f"+proj=tmerc +lat_0=0 +lon_0={lon0:g} +k={round(1 - error / 2, 6):g} {tail}"


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("geojson", type=Path)
    args = parser.parse_args(argv)
    from shapely.geometry import shape
    features = json.loads(args.geojson.read_text(encoding="utf-8"))["features"]
    by_code = defaultdict(list)
    for feature in features:
        code = feature["properties"]["ISO_A2_EH"]
        if re.fullmatch(r"[A-Z]{2}", code or "") and code not in HAND_WRITTEN | EXCLUDED:
            by_code[code].append(feature)
    rows = []
    for code, group in sorted(by_code.items()):
        # A few codes have small extra features (e.g. Baikonur); keep the largest.
        feature = max(group, key=lambda f: shape(f["geometry"]).area)
        props = feature["properties"]
        continent = props["CONTINENT"]
        if continent.startswith("Seven seas"):
            continent = REGION_TO_CONTINENT[props["REGION_UN"]]
        bounds = envelope(feature["geometry"])
        crs, error = choose_crs(bounds)
        rows.append((continent, props["NAME_EN"], code, slug(props["NAME_EN"]), bounds, crs, error))
        print(f"{code} {props['NAME_EN']}: {bounds} {crs} max scale error {100 * error:.2f}%")
    coverages = [row[3] for row in rows]
    if len(set(coverages)) != len(coverages):
        raise SystemExit("Duplicate coverage names")
    rows.sort(key=lambda row: (row[0], row[1]))
    lines = [
        '"""Generated receiver envelopes for the remaining countries and territories.',
        "",
        "Do not edit by hand; regenerate with scripts/build_world_profiles.py, which",
        "documents the Natural Earth source, envelope rule and CRS selection rule.",
        "Each row: continent, name, ISO 3166-1 alpha-2, coverage, (west, south, east,",
        "north), search CRS, maximum point-scale error of that CRS over the envelope.",
        '"""',
        "",
        "WORLD_PROFILES = (",
    ]
    for continent, name, code, coverage, bounds, crs, error in rows:
        b = ", ".join(f"{value:g}" for value in bounds)
        lines.append(f"    ({continent!r}, {name!r}, {code!r}, {coverage!r}, ({b}), {crs!r}, {error:.4f}),")
    lines.append(")")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    block = [DOCS_START]
    for continent in sorted({row[0] for row in rows}):
        entries = ", ".join(f"`{row[2]}` {row[1]}" for row in rows if row[0] == continent)
        block += ["", f"**{continent}:** {entries}."]
    block += ["", DOCS_END]
    docs = DOCS.read_text(encoding="utf-8")
    start, end = docs.index(DOCS_START), docs.index(DOCS_END) + len(DOCS_END)
    DOCS.write_text(docs[:start] + "\n".join(block) + docs[end:], encoding="utf-8")
    print(f"Wrote {len(rows)} profiles to {OUTPUT} and {DOCS}")


if __name__ == "__main__":
    main()
