"""Bounded, source-informed regional input rebuild; not a location benchmark."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tarfile
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aircraft_geoloc import data_access, geometry, tracks


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
ORIGINAL = ROOT.with_name("DOPPLERGEIST")
MAX_MEMBER_BYTES = 64 * 1024 * 1024
ROW_GROUP_SIZE = 65536
VELOCITY = ("east_mps", "north_mps", "up_mps")
COLUMNS = ("flight_id", "time_s", "lat", "lon", "alt_m", "speed_mps",
           "heading_deg", "east_mps", "north_mps", "up_mps", "typecode", "altitude_basis")
SCHEMA = pa.schema([(name, pa.string() if name in
                   ("flight_id", "typecode", "altitude_basis") else pa.float64())
                   for name in COLUMNS])


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def observed_bounds(parquet):
    result = {}
    for col in ("time_s", "lat", "lon"):
        index = parquet.schema.names.index(col)
        stats = [parquet.metadata.row_group(g).column(index).statistics
                 for g in range(parquet.metadata.num_row_groups)]
        result[col] = {"min": min(s.min for s in stats if s and s.has_min_max),
                       "max": max(s.max for s in stats if s and s.has_min_max)}
    return result


def prepare():
    """Write the fixed selection declaration before opening any raw archive."""
    old_path = ORIGINAL / "data/adsb/2026-09-08/reference-region.parquet"
    old = pq.ParquetFile(old_path)
    report_path = old_path.with_name("reference-region-ingestion-report.json")
    log_path = ORIGINAL / "data/source/adsb-region-ingestion.log"
    old_info = {"path": str(old_path), "sha256": digest(old_path),
                "bytes": old_path.stat().st_size, "rows": old.metadata.num_rows,
                "row_groups": old.metadata.num_row_groups,
                "schema": str(old.schema_arrow),
                "schema_metadata": {k.decode(): v.decode() for k, v in
                                    (old.schema_arrow.metadata or {}).items()},
                "observed_extents": observed_bounds(old),
                "ingestion_report": json.loads(report_path.read_text()),
                "ingestion_report_sha256": digest(report_path),
                "ingestion_log_sha256": digest(log_path),
                "declared_ingestion_bounds_recovered": False,
                "reason": "Parquet metadata, ingestion report and log omit the old --bounds argument. Observed sample extrema do not prove the original requested bounds."}
    write_json(OUTPUT / "old-region-inspection.json", old_info)
    selection = {
        "declared_at_utc": now(), "scope": "source_informed_legacy_regional_regression_inputs",
        "bounds_order": "west,south,east,north", "bounds_wsen": [-76., 38., -71., 43.],
        "bounds_origin": "Fixed fallback specified in the verification assignment, declared before reading the raw archive; not derived from the recorder coordinate.",
        "guard": "More than one degree beyond every edge of the old Parquet observed extent.",
        "selection_rule": "Select a raw aircraft trace if any finite observed latitude/longitude sample falls inside the inclusive bounds, regardless of altitude, type, identity or time.",
        "retention_rule": "Pass each selected complete raw trace unmodified to tracks.adsblol_frame; retain every row emitted by that normalizer, including rows and times outside the selection box.",
        "normalizer_exclusion": "adsblol_frame omits raw samples whose altitude slot is not numeric; record these separately. No additional spatial, time, identity, type or quality filtering.",
        "time_filter": None, "identity_filter": None, "aircraft_type_filter": None,
        "source_date": "2026-09-08", "row_group_size": ROW_GROUP_SIZE,
        "max_member_bytes": MAX_MEMBER_BYTES,
        "limitations": ["Regional and source-informed; not national coverage or independent location acceptance.",
                        "Observed archive capture is not complete aircraft coverage.",
                        "Missing velocity components remain unavailable until segment-local inference during track loading.",
                        "Barometric altitude remains labelled; normalization does not prove datum consistency."]}
    west, south, east, north = selection["bounds_wsen"]
    bounds = old_info["observed_extents"]
    assert west <= bounds["lon"]["min"] - 1 and east >= bounds["lon"]["max"] + 1
    assert south <= bounds["lat"]["min"] - 1 and north >= bounds["lat"]["max"] + 1
    write_json(OUTPUT / "selection.json", selection)
    receipt_path = ORIGINAL / ".artifacts/physical-verification/raw-restoration.json"
    sources = json.loads(receipt_path.read_text())
    release = json.loads((ORIGINAL / "data/adsb/2026-09-08/release.json").read_text())
    urls = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    for source in sources:
        assert Path(source["path"]).stat().st_size == source["bytes"]
        source["url"] = urls[source["name"]]
    write_json(OUTPUT / "sources.json", {
        "provider": "adsb.lol readsb daily archive", "parts_in_order": sources,
        "checksum_evidence": {"path": str(receipt_path), "sha256": digest(receipt_path),
                              "status": "Parent task verified downloaded part SHA-256 values; this run checks sizes and records those receipts."},
        "source_release_metadata_sha256": digest(ORIGINAL / "data/adsb/2026-09-08/release.json")})
    code = {"git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "python": sys.version, "platform": platform.platform(),
            "versions": {"numpy": np.__version__, "pandas": pd.__version__, "pyarrow": pa.__version__},
            "files": {str(Path(mod.__file__).resolve()): digest(mod.__file__)
                      for mod in (tracks, data_access, geometry)},
            "runner_sha256": digest(__file__), "schema": str(SCHEMA),
            "normalizer": "aircraft_geoloc.tracks.adsblol_frame",
            "stream_reader": "aircraft_geoloc.data_access.SplitReader",
            "configuration_sha256": digest(OUTPUT / "selection.json")}
    write_json(OUTPUT / "code.json", code)
    print(json.dumps({"stage": "selection_declared", "selection": selection, "code_commit": code["git_commit"]}), flush=True)
    return selection, sources, code


def main():
    parquet_path = OUTPUT / "reference-region-alltypes-fulltraces.parquet"
    partial = parquet_path.with_suffix(".parquet.building")
    if parquet_path.exists() or partial.exists():
        raise FileExistsError("Preserve existing run outputs; use a new experiment directory.")
    selection, sources, code = prepare()
    west, south, east, north = selection["bounds_wsen"]
    started, last_progress = time.monotonic(), time.monotonic()
    counts = Counter()
    altitude, types, nulls, nonfinite = Counter(), Counter(), Counter(), Counter()
    extrema = {c: [math.inf, -math.inf] for c in ("time_s", "lat", "lon", "alt_m")}
    seen_ids, selected_ids = set(), set()
    selected_basis = Counter()

    def progress(stage):
        value = {"stage": stage, "updated_at_utc": now(), "elapsed_s": time.monotonic()-started,
                 "counts": dict(counts), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        write_json(OUTPUT / "progress.json", value)
        print(json.dumps(value), flush=True)

    try:
        with (OUTPUT / "trace-selection.jsonl").open("x") as audit, \
                pq.ParquetWriter(partial, SCHEMA, compression="zstd") as writer, \
                io.BufferedReader(data_access.SplitReader([s["path"] for s in sources]), buffer_size=1024*1024) as stream, \
                tarfile.open(fileobj=stream, mode="r|*") as archive:
            while (member := archive.next()) is not None:
                archive.members.clear()  # Do not accumulate metadata for the global archive.
                if not member.isfile() or "trace_full_" not in member.name:
                    counts["non_trace_members"] += 1
                    continue
                if member.size > MAX_MEMBER_BYTES:
                    raise ValueError(f"Oversized trace member: {member.name}")
                raw = archive.extractfile(member).read()
                raw_digest = hashlib.sha256(raw).hexdigest()
                if raw[:2] == b"\x1f\x8b":
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                        decoded = compressed.read(MAX_MEMBER_BYTES + 1)
                    if len(decoded) > MAX_MEMBER_BYTES:
                        raise ValueError(f"Oversized expanded trace: {member.name}")
                else:
                    decoded = raw
                d = json.loads(decoded)
                del raw, decoded
                identity, trace = d["icao"], d["trace"]
                if identity in seen_ids:
                    raise ValueError(f"Repeated aircraft trace identity requires an explicit whole-aircraft selection pass: {identity}")
                seen_ids.add(identity)
                counts["trace_files"] += 1
                counts["raw_samples_scanned"] += len(trace)
                hits = sum(isinstance(p[1], (int, float)) and isinstance(p[2], (int, float))
                           and south <= p[1] <= north and west <= p[2] <= east for p in trace)
                item = {"member": member.name, "icao": identity, "member_bytes": member.size,
                        "member_sha256": raw_digest, "raw_samples": len(trace),
                        "raw_samples_in_selection": hits, "selected": bool(hits)}
                if hits:
                    selected_ids.add(identity)
                    counts["selected_aircraft"] += 1
                    counts["selected_raw_samples"] += len(trace)
                    counts["selected_raw_samples_inside_box"] += hits
                    numeric_alt = sum(isinstance(p[3], (int, float)) for p in trace)
                    frame = tracks.adsblol_frame(d)
                    assert len(frame) == numeric_alt, "Unexpected normalizer row-count change"
                    counts["normalizer_excluded_nonnumeric_altitude"] += len(trace)-len(frame)
                    item["normalized_rows"] = len(frame)
                    item["normalizer_excluded_nonnumeric_altitude"] = len(trace)-len(frame)
                    if len(frame):
                        counts["selected_aircraft_with_normalized_rows"] += 1
                        table = pa.Table.from_pandas(frame, schema=SCHEMA, preserve_index=False, safe=True)
                        writer.write_table(table, row_group_size=ROW_GROUP_SIZE)
                        counts["normalized_rows"] += len(frame)
                        counts["expected_row_groups"] += math.ceil(len(frame)/ROW_GROUP_SIZE)
                        finite_geometry = np.isfinite(frame[["time_s", "lat", "lon", "alt_m"]].to_numpy(dtype=float)).all(axis=1)
                        counts["normalized_rows_nonfinite_required_geometry"] += int((~finite_geometry).sum())
                        inside = frame.lat.between(south, north) & frame.lon.between(west, east)
                        counts["normalized_rows_inside_box"] += int(inside.sum())
                        counts["normalized_rows_outside_box"] += int((~inside).sum())
                        counts["duplicate_times_within_trace"] += int(frame.time_s.duplicated().sum())
                        counts["nonincreasing_time_steps_within_trace"] += int((frame.time_s.diff() <= 0).sum())
                        missing_velocity = ~np.isfinite(frame[list(VELOCITY)].to_numpy(dtype=float))
                        counts["rows_any_missing_velocity_component"] += int(missing_velocity.any(axis=1).sum())
                        counts["rows_all_missing_velocity_components"] += int(missing_velocity.all(axis=1).sum())
                        counts["measured_zero_ground_speed_rows"] += int((frame.speed_mps == 0).sum())
                        counts["zero_horizontal_velocity_rows"] += int(((frame.east_mps == 0) & (frame.north_mps == 0)).sum())
                        counts["measured_zero_vertical_velocity_rows"] += int((frame.up_mps == 0).sum())
                        for i, col in enumerate(COLUMNS):
                            nulls[col] += table.column(i).null_count
                            if col not in ("flight_id", "typecode", "altitude_basis"):
                                nonfinite[col] += int((~np.isfinite(frame[col].to_numpy(dtype=float))).sum())
                        local_altitude = frame.altitude_basis.value_counts().to_dict()
                        altitude.update(local_altitude)
                        types.update(frame.typecode.fillna("<null>").value_counts().to_dict())
                        selected_basis["|".join(sorted(local_altitude))] += 1
                        item["altitude_basis_counts"] = local_altitude
                        item["missing_velocity_components"] = {col: int(missing_velocity[:, i].sum()) for i, col in enumerate(VELOCITY)}
                        for col in extrema:
                            values = frame[col].to_numpy(dtype=float)
                            values = values[np.isfinite(values)]
                            if len(values):
                                extrema[col][0] = min(extrema[col][0], float(values.min()))
                                extrema[col][1] = max(extrema[col][1], float(values.max()))
                        item["normalized_time_range_s"] = [float(frame.time_s.min()), float(frame.time_s.max())]
                        del table, missing_velocity, finite_geometry, inside
                    del frame
                audit.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
                del d, trace, item
                if time.monotonic()-last_progress >= 25:
                    progress("streaming_archive")
                    last_progress = time.monotonic()
        assert counts["selected_aircraft"] == len(selected_ids)
        assert counts["normalized_rows"] > 0
        assert counts["selected_raw_samples"] == counts["normalized_rows"] + counts["normalizer_excluded_nonnumeric_altitude"]
        parquet = pq.ParquetFile(partial)
        assert parquet.metadata.num_rows == counts["normalized_rows"]
        assert parquet.metadata.num_row_groups == counts["expected_row_groups"]
        assert parquet.schema_arrow.equals(SCHEMA, check_metadata=False)
        # Validate all written row groups in bounded batches, including null preservation.
        reread_rows, reread_nulls = 0, Counter()
        for batch in parquet.iter_batches(batch_size=ROW_GROUP_SIZE):
            reread_rows += batch.num_rows
            for i, col in enumerate(COLUMNS):
                reread_nulls[col] += batch.column(i).null_count
        assert reread_rows == counts["normalized_rows"] and reread_nulls == nulls
        del parquet
        partial.replace(parquet_path)
        result = {"status": "complete", "scope": selection["scope"], "finished_at_utc": now(),
                  "elapsed_s": time.monotonic()-started, "counts": dict(counts),
                  "unique_aircraft_scanned": len(seen_ids), "unique_aircraft_selected": len(selected_ids),
                  "output_extents": {k: {"min": v[0], "max": v[1]} for k, v in extrema.items()},
                  "altitude_basis_counts": dict(altitude), "aircraft_by_altitude_basis_set": dict(selected_basis),
                  "typecode_row_counts": dict(types), "null_counts": dict(nulls), "nonfinite_numeric_counts": dict(nonfinite),
                  "velocity_inference_performed": False,
                  "validation": {"full_stream_completed": True, "unique_raw_aircraft_trace_ids": True,
                                 "all_selected_trace_normalizer_rows_retained": True,
                                 "parquet_schema_and_row_groups_match": True,
                                 "bounded_batch_reread_rows_and_null_counts_match": True},
                  "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "git_commit_at_start": code["git_commit"],
                  "source_files_unchanged_during_run": all(digest(p) == h for p, h in code["files"].items()),
                  "output": {"path": str(parquet_path), "bytes": parquet_path.stat().st_size,
                             "sha256": digest(parquet_path)}}
        write_json(OUTPUT / "normalization-report.json", result)
        write_json(OUTPUT / "artifact-hashes.json", {
            p.name: {"sha256": digest(p), "bytes": p.stat().st_size}
            for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name not in ("artifact-hashes.json", "progress.json")})
        progress("complete")
        print(json.dumps({"status": "complete", "output": result["output"], "counts": result["counts"]}), flush=True)
    except Exception as exc:
        write_json(OUTPUT / "failure.json", {"status": "failed", "error": repr(exc),
                                           "counts": dict(counts), "updated_at_utc": now()})
        progress("failed")
        raise


if __name__ == "__main__":
    main()
