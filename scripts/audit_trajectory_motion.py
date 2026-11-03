#!/usr/bin/env python3
"""Audit frozen indexed motion against freshly normalized raw ADS-B observations.

This diagnostic never changes trajectories, acoustic scores or coverage status.
Select aircraft identified by a prior data-quality audit, not recording truth.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import resource
import sqlite3
import tarfile
import time

import numpy as np
import pandas as pd

from dopplergeist import geometry, tracks
from dopplergeist.data_access import SplitReader, _frame_track


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def segment_peak(dt, p0, p1, v0, v1):
    """Enumerate endpoints and stationary points of squared Hermite speed.

    Use normalized time u in [0,1]. Velocity is A*u**2+B*u+C, so its squared
    norm is quartic and its stationary polynomial has degree at most three.
    Root solving uses double precision, not certified interval arithmetic.
    """
    vectors = np.asarray([p0, p1, v0, v1], dtype=float)
    if dt <= 0 or not np.isfinite(dt) or vectors.shape != (4, 3) or not np.isfinite(vectors).all():
        raise ValueError("Need positive finite duration and four finite 3D vectors")
    p0, p1, v0, v1 = vectors
    mean = (p1 - p0) / dt
    a, b, c = 3 * (-2 * mean + v0 + v1), 2 * (3 * mean - 2 * v0 - v1), v0
    derivative = [2 * np.dot(b, c), 2 * (np.dot(b, b) + 2 * np.dot(a, c)),
                  6 * np.dot(a, b), 4 * np.dot(a, a)]
    roots = np.polynomial.polynomial.polyroots(derivative)
    candidates = [0.0, 1.0] + [float(root.real) for root in roots
        if abs(root.imag) <= 1e-8 and 0 < root.real < 1]
    speeds = [float(np.linalg.norm((a * u + b) * u + c)) for u in candidates]
    best = int(np.argmax(speeds))
    return {"speed_mps": speeds[best], "fraction": candidates[best],
            "mean_displacement_speed_mps": float(np.linalg.norm(mean)),
            "endpoint_speeds_mps": [float(np.linalg.norm(v0)), float(np.linalg.norm(v1))]}


def audit_frame(frame, sound_speed, gap=30.0, interval_window=None):
    """Use production gap/dedup/velocity rules without modifying any input rows."""
    required = ["time_s", "lat", "lon", "alt_m"]
    valid = np.isfinite(frame[required].to_numpy(dtype=float)).all(axis=1)
    clean = frame.loc[valid].sort_values("time_s", kind="stable").drop_duplicates("time_s")
    report = {"rows": len(frame), "nonfinite_geometry_rows": int((~valid).sum()),
              "duplicate_times": int(frame.time_s.duplicated().sum()),
              "altitude_basis_counts": frame.altitude_basis.value_counts().to_dict(),
              "missing_velocity_components": {name: int(frame[name].isna().sum())
                  for name in ("east_mps", "north_mps", "up_mps")},
              "segments": [], "short_segments": []}
    groups = (clean.time_s.diff() > gap).cumsum()
    for number, (_, chunk) in enumerate(clean.groupby(groups)):
        if interval_window and not chunk.time_s.between(*interval_window).any():
            continue
        identity = str(chunk.flight_id.iloc[0]) + (f":{number}" if groups.max() else "")
        if len(chunk) < 3:
            report["short_segments"].append({"id": identity, "rows": len(chunk),
                                            "reason": "Production requires at least three knots"})
            continue
        track = _frame_track(identity, chunk)
        velocity = track.speed_vector(track.time)
        intervals = []
        for i, dt in enumerate(np.diff(track.time)):
            if interval_window and not (interval_window[0] <= track.time[i] < track.time[i+1] <= interval_window[1]):
                continue
            peak = segment_peak(dt, track.xyz[i], track.xyz[i+1], velocity[i], velocity[i+1])
            times = np.linspace(track.time[i], track.time[i+1], 65)
            sampled = float(np.linalg.norm(track.speed_vector(times), axis=1).max())
            intervals.append(dict(peak, start_s=float(track.time[i]), end_s=float(track.time[i+1]),
                                  peak_time_s=float(track.time[i] + peak["fraction"] * dt),
                                  sampled_max_mps=sampled, exceeds_subsonic_speed=peak["speed_mps"] >= sound_speed))
        if not intervals:
            continue
        report["segments"].append({"id": identity, "typecode": track.typecode,
            "velocity_inferred_components": track.velocity_inferred_components,
            "max_knot_speed_mps": max(max(p["endpoint_speeds_mps"]) for p in intervals),
            "max_continuous_speed_mps": max(p["speed_mps"] for p in intervals),
            "unsupported_intervals": sum(p["exceeds_subsonic_speed"] for p in intervals),
            "intervals": intervals})
    return report


def compare_observations(canonical, fresh):
    common = canonical.merge(fresh, on="time_s", suffixes=("_canonical", "_fresh"), how="outer", indicator=True)
    paired = common[common._merge == "both"]
    xyz = [geometry.ecef(paired[f"lat_{tag}"], paired[f"lon_{tag}"], paired[f"alt_m_{tag}"])
           for tag in ("canonical", "fresh")]
    return {"canonical_only_times": int((common._merge == "left_only").sum()),
            "fresh_only_times": int((common._merge == "right_only").sum()), "paired_times": len(paired),
            "max_ecef_observation_difference_m": float(np.linalg.norm(xyz[0] - xyz[1], axis=1).max()) if len(paired) else None,
            "height_delta_fresh_minus_canonical_m": [float((paired.alt_m_fresh-paired.alt_m_canonical).min()),
                                                      float((paired.alt_m_fresh-paired.alt_m_canonical).max())] if len(paired) else None,
            "altitude_basis_pairs": paired.groupby(["altitude_basis_canonical", "altitude_basis_fresh"]).size().rename_axis(["canonical", "fresh"]).reset_index(name="rows").to_dict("records"),
            "velocity_components": {col: {
                "canonical_zero_fresh_missing": int(((paired[col+"_canonical"] == 0) & paired[col+"_fresh"].isna()).sum()),
                "canonical_nonzero_fresh_missing": int((paired[col+"_canonical"].notna() & (paired[col+"_canonical"] != 0) & paired[col+"_fresh"].isna()).sum()),
                "both_finite_differing": int((paired[col+"_canonical"].notna() & paired[col+"_fresh"].notna() &
                                             (abs(paired[col+"_canonical"] - paired[col+"_fresh"]) > 1e-9)).sum())}
                for col in ("east_mps", "north_mps", "up_mps")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--parts", type=Path, nargs="+", required=True)
    parser.add_argument("--ids", nargs="+", required=True)
    parser.add_argument("--window", type=float, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(re.fullmatch("[0-9a-f]{6}", identity) for identity in args.ids) or args.window[0] >= args.window[1]:
        parser.error("Need lowercase six-hex aircraft IDs and increasing time bounds")
    args.output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    sources = [{"path": str(p.resolve()), "bytes": p.stat().st_size, "sha256": digest(p)}
               for p in [args.canonical, args.index, *args.parts]]
    declaration = {"ids": args.ids, "window_s": args.window, "gap_s": 30.0, "sound_speed_mps": 343.0,
        "scope": "Targeted data-quality audit, not an acoustic localization benchmark",
        "sources": sources, "code": {str(p): digest(p) for p in [Path(__file__), Path(tracks.__file__), Path(geometry.__file__)]}}
    write(args.output / "declaration.json", declaration)
    canonical = pd.read_parquet(args.canonical, filters=[("flight_id", "in", args.ids)])
    canonical.to_json(args.output / "canonical-observations.json", orient="records", double_precision=15)
    fresh, fresh_full, raw_members, order_comparisons, scanned = {}, {}, [], {}, 0
    with io.BufferedReader(SplitReader(args.parts), buffer_size=1024*1024) as stream, tarfile.open(fileobj=stream, mode="r|*") as archive:
        while (member := archive.next()) is not None:
            archive.members.clear()
            scanned += 1
            match = re.search(r"trace_full_([0-9a-f]{6})\.json$", member.name)
            if not member.isfile() or not match or match[1] not in args.ids:
                continue
            if member.size > 64*1024*1024:
                raise ValueError(f"Trace too large: {member.name}")
            raw = archive.extractfile(member).read()
            if raw[:2] == b"\x1f\x8b":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                    decoded = compressed.read(64*1024*1024+1)
            else:
                decoded = raw
            if len(decoded) > 64*1024*1024:
                raise ValueError(f"Expanded trace too large: {member.name}")
            document = json.loads(decoded)
            identity = document["icao"]
            if identity != match[1] or identity in fresh:
                raise ValueError(f"Unexpected or duplicate identity: {member.name}")
            frame = tracks.adsblol_frame(document)  # Normalize full trace before restricting time.
            fresh_full[identity] = frame
            fresh[identity] = frame[frame.time_s.between(*args.window)].copy()
            clipped = dict(document, trace=[p for p in document["trace"]
                if args.window[0] <= document["timestamp"]+p[0] <= args.window[1]])
            order_comparisons[identity] = compare_observations(tracks.adsblol_frame(clipped), fresh[identity])
            raw_members.append({"member": member.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                                "raw_observations": len(document["trace"]), "normalized_full_rows": len(frame)})
            print(json.dumps({"found": identity, "window_rows": len(fresh[identity])}), flush=True)
    failures, audits = [], []
    with sqlite3.connect(f"file:{args.index.resolve()}?mode=ro", uri=True) as db:
        metadata = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        for identity in args.ids:
            try:
                old = canonical[canonical.flight_id == identity]
                current = fresh[identity]
                if old.empty or current.empty:
                    raise ValueError("No observations in declared window")
                current.to_json(args.output / f"fresh-{identity}.json", orient="records", double_precision=15)
                indexed = []
                for name, payload, expected in db.execute("SELECT name,payload,payload_hash FROM segments WHERE name=? OR name LIKE ?", (identity, identity+":%")):
                    if hashlib.sha256(payload).hexdigest() != expected:
                        raise ValueError(f"Index payload hash mismatch: {name}")
                    frame = pd.DataFrame(json.loads(gzip.decompress(payload)))
                    indexed.append({"id": name, "audit": audit_frame(frame, 343.0)})
                audits.append({"identity": identity, "observation_comparison": compare_observations(old, current),
                    "normalization_order_comparison": order_comparisons[identity],
                    "canonical": audit_frame(old, 343.0), "fresh": audit_frame(current, 343.0),
                    "fresh_full_support": audit_frame(fresh_full[identity], 343.0, interval_window=args.window),
                    "indexed": indexed})
            except (KeyError, ValueError) as exc:
                failures.append({"identity": identity, "reason": str(exc)})
    report = {"declaration": declaration, "index_input_hash": metadata["input_hash"], "raw_members": raw_members,
        "archive_members_scanned": scanned, "aircraft": audits, "failures": failures,
        "elapsed_s": time.monotonic()-began, "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limitations": ["No production trajectory, score, threshold or coverage decision changed.",
            "Source inconsistencies and speed >= sound speed do not establish real supersonic motion.",
            "Stationary-point roots use floating-point arithmetic, checked against dense segment samples."]}
    write(args.output / "report.json", report)
    print(json.dumps({"completed_aircraft": len(audits), "failures": failures, "elapsed_s": report["elapsed_s"]}), flush=True)


if __name__ == "__main__":
    main()
