"""Canonical CSV/Parquet and public ADS-B KML/trace importers."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from .geometry import Track, velocity_ecef


def unix_time(value):
    if isinstance(value, (float, int, np.number)):
        return float(value)
    return pd.Timestamp(value).timestamp()


def read_kml(path):
    ns = {"k": "http://www.opengis.net/kml/2.2", "gx": "http://www.google.com/kml/ext/2.2"}
    root = ET.parse(path).getroot()
    rows = []
    for placemark in root.findall(".//k:Placemark", ns):
        name = placemark.findtext("k:name", default=Path(path).stem, namespaces=ns)
        for trace in placemark.findall(".//gx:Track", ns):
            timestamps = trace.findall("k:when", ns)
            coords = trace.findall("gx:coord", ns)
            if len(timestamps) != len(coords):
                raise ValueError(f"{path}: KML timestamps and coordinates differ")
            for t, coord in zip(timestamps, coords):
                lon, lat, altitude = map(float, coord.text.split())
                rows.append({"flight_id": name, "time_s": unix_time(t.text),
                             "lat": lat, "lon": lon, "alt_m": altitude})
    return pd.DataFrame(rows)


def read_adsblol_trace(path):
    """tar1090 trace format; trace offsets are seconds, altitude feet, speed knots."""
    import gzip
    raw=Path(path).read_bytes()
    d=json.loads(gzip.decompress(raw) if raw[:2]==b"\x1f\x8b" else raw)
    return adsblol_frame(d)


def adsblol_frame(d):
    """Normalize readsb trace fields using the documented geometric-altitude slot.

    Missing geometric samples use an interpolated geometric-minus-baro offset
    only when this aircraft provides such measurements. A wholly barometric
    trace remains explicitly labelled; it is not silently called geometric.
    """
    valid=[p for p in d["trace"] if isinstance(p[3],(int,float))]
    offsets=[]
    for p in valid:
        geom=p[10] if len(p)>10 else None
        if geom is not None and not (p[6]&8):
            offsets.append((p[0],geom-p[3]))
    rows = []
    for p in valid:
        metadata = p[8] if len(p) > 8 and isinstance(p[8], dict) else {}
        geom=p[10] if len(p)>10 else None
        if p[6]&8:
            altitude,basis=p[3],"ellipsoidal"
        elif geom is not None:
            altitude,basis=geom,"ellipsoidal"
        elif offsets:
            altitude=p[3]+np.interp(p[0],*[np.array(offsets)[:,i] for i in [0,1]])
            basis="ellipsoidal_interpolated"
        else:
            altitude,basis=p[3],"barometric"
        speed=(p[4] or 0)*0.514444
        heading=np.deg2rad(p[5] or 0)
        rate=p[11] if len(p)>11 and p[11] is not None else p[7]
        rows.append({"flight_id": d["icao"],
                     "time_s": d["timestamp"] + p[0], "lat": p[1], "lon": p[2],
                     "alt_m": altitude*0.3048,"speed_mps":speed,"heading_deg":p[5],
                     "east_mps":speed*np.sin(heading),"north_mps":speed*np.cos(heading),
                     "up_mps":(rate or 0)*0.00508,
                     "typecode":metadata.get("t",d.get("t","")),"altitude_basis":basis})
    return pd.DataFrame(rows)


def load_tracks(path, max_gap_s=30.0, type_database=None, bounds=None, time_range=None):
    path = Path(path)
    if path.suffix.lower() == ".kml":
        df = read_kml(path)
    elif path.suffix.lower() in (".json", ".gz"):
        df = read_adsblol_trace(path)
    elif path.suffix.lower() == ".parquet":
        filters=[]
        if bounds:
            west,south,east,north=bounds
            filters += [("lon",">=",west),("lon","<=",east),("lat",">=",south),("lat","<=",north)]
        if time_range:
            filters += [("time_s",">=",time_range[0]),("time_s","<=",time_range[1])]
        df = pd.read_parquet(path,filters=filters or None)
    else:
        df = pd.read_csv(path)
    required = {"time_s", "lat", "lon", "alt_m"}
    if not required.issubset(df):
        raise ValueError(f"{path}: required columns {sorted(required)} (SI units)")
    if "flight_id" not in df:
        df["flight_id"] = path.stem
    df["time_s"] = df.time_s.map(unix_time)
    types = {}
    if type_database:
        # ICAO doc8643-style CSV: designator and engine_type (Jet/Turboprop/Piston).
        table = pd.read_csv(type_database).fillna("")
        types = dict(zip(table.designator, table.engine_type.str.lower()))
    tracks, rejected = [], []
    for flight_id, group in df.groupby("flight_id", sort=False):
        group = group.sort_values("time_s").drop_duplicates("time_s")
        group = group.dropna(subset=list(required))
        code = str(group.typecode.iloc[0]) if "typecode" in group else ""
        if types.get(code, "") in ("jet", "j", "turbofan", "turbojet"):
            rejected.append(str(flight_id))
            continue
        chunks = (group.time_s.diff() > max_gap_s).cumsum()
        for index, (_, chunk) in enumerate(group.groupby(chunks)):
            if len(chunk) < 3:
                continue
            v = None
            if {"east_mps", "north_mps", "up_mps"}.issubset(chunk):
                v = velocity_ecef(chunk.lat.to_numpy(), chunk.lon.to_numpy(),
                                  chunk.east_mps.to_numpy(), chunk.north_mps.to_numpy(), chunk.up_mps.to_numpy())
            identifier = str(flight_id) + (f":{index}" if chunks.max() else "")
            tracks.append(Track(identifier, chunk.time_s.to_numpy(), chunk.lat.to_numpy(),
                                chunk.lon.to_numpy(), chunk.alt_m.to_numpy(), code, v))
    return tracks, {"rows": len(df), "segments": len(tracks), "known_jets_excluded": rejected,
                    "altitude_basis_counts":df.altitude_basis.value_counts().to_dict() if "altitude_basis" in df else {},
                    "unknown_types_retained": True}
