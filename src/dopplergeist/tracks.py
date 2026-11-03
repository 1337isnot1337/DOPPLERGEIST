"""Canonical CSV/Parquet and public ADS-B KML/trace importers."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from .geometry import Track, ecef, velocity_ecef


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
    offset_array = np.asarray(offsets) if offsets else None
    rows = []
    for p in valid:
        metadata = p[8] if len(p) > 8 and isinstance(p[8], dict) else {}
        geom=p[10] if len(p)>10 else None
        if p[6]&8:
            altitude,basis=p[3],"ellipsoidal"
        elif geom is not None:
            altitude,basis=geom,"ellipsoidal"
        elif offsets:
            altitude=p[3]+np.interp(p[0],offset_array[:,0],offset_array[:,1])
            basis="ellipsoidal_interpolated"
        else:
            altitude,basis=p[3],"barometric"
        # Null measurements are unavailable, not measured zero. Preserve them
        # until position-derived velocities can be inferred after gap splitting.
        speed=p[4]*0.514444 if p[4] is not None else np.nan
        heading=np.deg2rad(p[5]) if p[5] is not None else np.nan
        east,north=(0.0,0.0) if speed==0 else (speed*np.sin(heading),speed*np.cos(heading))
        rate=p[11] if len(p)>11 and p[11] is not None else p[7]
        rows.append({"flight_id": d["icao"],
                     "time_s": d["timestamp"] + p[0], "lat": p[1], "lon": p[2],
                     "alt_m": altitude*0.3048,"speed_mps":speed,"heading_deg":p[5],
                     "east_mps":east,"north_mps":north,
                     "up_mps":rate*0.00508 if rate is not None else np.nan,
                     "typecode":metadata.get("t",d.get("t","")),"altitude_basis":basis})
    return pd.DataFrame(rows)


def _segment_velocity(chunk):
    """Fill only missing ENU components using this gap-split segment's positions."""
    columns=("east_mps","north_mps","up_mps")
    enu=np.column_stack([chunk[name].to_numpy(dtype=float) if name in chunk else
                         np.full(len(chunk),np.nan) for name in columns])
    missing=~np.isfinite(enu)
    counts={name:int(missing[:,i].sum()) for i,name in enumerate(columns)}
    if missing.all():
        # Track's default derivative uses the same segment-local gradient.
        return None,counts
    lat,lon=chunk.lat.to_numpy(),chunk.lon.to_numpy()
    if missing.any():
        times=chunk.time_s.to_numpy()
        xyz=ecef(lat,lon,chunk.alt_m.to_numpy())
        vx,vy,vz=np.gradient(xyz,times-times[0],axis=0).T
        phi,lam=np.deg2rad(lat),np.deg2rad(lon)
        inferred=np.column_stack((
            -np.sin(lam)*vx+np.cos(lam)*vy,
            -np.sin(phi)*np.cos(lam)*vx-np.sin(phi)*np.sin(lam)*vy+np.cos(phi)*vz,
            np.cos(phi)*np.cos(lam)*vx+np.cos(phi)*np.sin(lam)*vy+np.sin(phi)*vz,
        ))
        enu=np.where(missing,inferred,enu)
    return velocity_ecef(lat,lon,*enu.T),counts


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
    inferred_components={name:0 for name in ("east_mps","north_mps","up_mps")}
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
            v,counts = _segment_velocity(chunk)
            for name,count in counts.items():
                inferred_components[name]+=count
            identifier = str(flight_id) + (f":{index}" if chunks.max() else "")
            tracks.append(Track(identifier, chunk.time_s.to_numpy(), chunk.lat.to_numpy(),
                                chunk.lon.to_numpy(), chunk.alt_m.to_numpy(), code, v))
    return tracks, {"rows": len(df), "segments": len(tracks), "known_jets_excluded": rejected,
                    "altitude_basis_counts":df.altitude_basis.value_counts().to_dict() if "altitude_basis" in df else {},
                    "velocity_inferred_components":inferred_components,
                    "velocity_inference_method":"position_gradient_within_gap_split_segment",
                    "unknown_types_retained": True}
