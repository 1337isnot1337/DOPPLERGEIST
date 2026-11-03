"""Optional integration regression against a local, real ADS-B archive part."""
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dopplergeist.data_access import DataUnavailable, FlightIndex
from dopplergeist.flight_selection import intersects_index_query
from dopplergeist.tracks import adsblol_frame


def test_real_boundary_segments_survive_selection(tmp_path):
    source = os.environ.get("DOPPLERGEIST_REAL_ARCHIVE_PART")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_ARCHIVE_PART to a local readsb tar part")
    frames = []
    first_member = None
    with Path(source).open("rb") as stream, tarfile.open(fileobj=stream, mode="r|") as archive:
        for member in archive:
            if not member.isfile() or "trace_full_" not in member.name:
                continue
            raw = archive.extractfile(member).read()
            data = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
            frame = adsblol_frame(data)
            if len(frame) > 50:
                frames.append(frame)
                if first_member is None:
                    first_member = member.name, raw
            if len(frames) == 10:
                break
    assert len(frames) == 10
    bounds = (-180, -90, 180, 90)
    coverage = {"bounds": list(bounds), "time_range_s": [0, 4102444800],
                "all_aircraft": True, "release_tag": "real-regression"}
    full = FlightIndex.build(tmp_path / "full.sqlite", frames, sources=[], coverage=coverage)
    checked = old_filter_misses = 0
    for frame in frames:
        rows = frame.dropna(subset=["time_s", "lat", "lon", "alt_m"]).sort_values("time_s").drop_duplicates("time_s")
        gaps = np.diff(rows.time_s.to_numpy())
        choices = np.flatnonzero((gaps > 0.02) & (gaps <= 30))
        if not len(choices):
            continue
        i = int(choices[len(choices) // 2])
        a, b = float(rows.time_s.iloc[i]), float(rows.time_s.iloc[i + 1])
        interval = (a + (b - a) * 0.4, a + (b - a) * 0.6)
        selected_ids = {str(f.flight_id.iloc[0]) for f in frames
                        if intersects_index_query(f, bounds, interval)}
        matches = list(full.query(bounds, interval))
        assert all(track.id.split("@")[0] in selected_ids for track in matches)
        own_id = str(frame.flight_id.iloc[0])
        if any(track.id.split("@")[0] == own_id for track in matches):
            old_filter_misses += not frame.time_s.between(*interval).any()
        checked += 1
        if checked == 5:
            break
    assert checked == 5
    assert old_filter_misses > 0

    # Real rows with embedded source limits exercise index-side scope checks.
    selection = {"bounds": list(bounds), "time_range_s": [0, 4102444800],
                 "all_aircraft": False, "max_gap_s": 30.0}
    table = pa.Table.from_pandas(frames[0], preserve_index=False)
    table = table.replace_schema_metadata({b"dopplergeist.selection.v1": json.dumps(selection).encode()})
    source_parquet = tmp_path / "real-selected.parquet"
    pq.write_table(table, source_parquet)
    restricted = dict(coverage, all_aircraft=False)
    FlightIndex.from_parquet(tmp_path / "valid.sqlite", source_parquet, coverage=restricted)
    with pytest.raises(DataUnavailable, match="excluded aircraft"):
        FlightIndex.from_parquet(tmp_path / "types.sqlite", source_parquet, coverage=coverage)
    with pytest.raises(DataUnavailable, match="gap limit"):
        FlightIndex.from_parquet(tmp_path / "gap.sqlite", source_parquet, coverage=restricted, max_gap_s=60)
    with pytest.raises(DataUnavailable, match="selection bounds"):
        FlightIndex.from_parquet(tmp_path / "bounds.sqlite", source_parquet,
                                 coverage=dict(restricted, bounds=[-180, -90, 181, 90]))
    with pytest.raises(DataUnavailable, match="selection time"):
        FlightIndex.from_parquet(tmp_path / "time.sqlite", source_parquet,
                                 coverage=dict(restricted, time_range_s=[-1, 4102444800]))
    untagged = tmp_path / "real-untagged.parquet"
    pq.write_table(table.replace_schema_metadata(None), untagged)
    FlightIndex.from_parquet(tmp_path / "untagged.sqlite", untagged, coverage=coverage)

    # Exercise the actual ingest CLI with one unmodified September 8 trace.
    if "2026.09.08" in Path(source).name:
        project = tmp_path / "real-ingest"
        (project / "scripts").mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/ingest_adsblol_day.py",
                        project / "scripts/ingest_adsblol_day.py")
        (project / "data/source").mkdir(parents=True)
        (project / "data/source/icao_aircraft_types.json").write_text("{}")
        day = project / "data/adsb/2026-09-08"
        day.mkdir(parents=True)
        name, raw = first_member
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
        blob = archive_bytes.getvalue()
        (day / "real.tar.aa").write_bytes(blob[:len(blob) // 2])
        (day / "real.tar.ab").write_bytes(blob[len(blob) // 2:])
        for output, extra in (("whole", []), ("wide", ["--time-range", "2026-09-07T23:00:00Z", "2026-09-09T01:00:00Z"])):
            command = [sys.executable, str(project / "scripts/ingest_adsblol_day.py"),
                       "2026-09-08", "--keep-jets", "--bounds", "-180", "-90", "180", "90",
                       "--output", output + ".parquet", *extra]
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
            completed = subprocess.run(command, env=env, capture_output=True, text=True)
            assert completed.returncode == 0, completed.stderr
            meta = pq.read_schema(day / (output + ".parquet")).metadata[b"dopplergeist.selection.v1"]
            assert json.loads(meta)["time_range_s"] == [1788825600.0, 1788912000.0]
