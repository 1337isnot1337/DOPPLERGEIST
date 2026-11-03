"""Exercise the actual historical CLI with calibration outside selection bounds."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pandas as pd
import pyarrow.parquet as pq
import pytest


@pytest.mark.parametrize("selection", ["time", "space", "both"])
def test_native_altitude_support_is_normalized_before_row_selection(tmp_path, selection):
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "isolated-project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "ingest_adsblol_day.py"
    shutil.copyfile(root / "scripts/ingest_adsblol_day.py", script)
    source = project / "data/source"
    source.mkdir(parents=True)
    (source / "icao_aircraft_types.json").write_text('{}')
    day = project / "data/adsb/2026-09-22"
    day.mkdir(parents=True)
    trace = {"icao": "opaque-flight", "timestamp": 1790000000, "t": "PC12", "trace": [
        [t, lat, -100, 5000, 100, 90, 0, 0, {}, 0, geometric, None]
        for t, lat, geometric in [(0, 40.2, 5450), (10, 40.05, None),
                                   (20, 40.05, None), (30, 40.2, 5450)]]}
    member = gzip.compress(json.dumps(trace).encode())
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as output:
        info = tarfile.TarInfo("traces/trace_full_opaque-flight.json")
        info.size = len(member)
        output.addfile(info, io.BytesIO(member))
    raw = archive.getvalue()
    for name, part in [("archive.tar.aa", raw[:len(raw)//2]), ("archive.tar.ab", raw[len(raw)//2:])]:
        (day / name).write_bytes(part)
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in day.iterdir()}
    bounds = [-101, 40, -99, 40.1 if selection != "time" else 40.3]
    command = [sys.executable, str(script), "2026-09-22", "--output", "new.parquet",
               "--bounds", *map(str, bounds)]
    if selection != "space":
        command += ["--time-range", *[pd.Timestamp(t, unit="s", tz="UTC").isoformat()
                                      for t in (1790000010, 1790000020)]]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    rows = pd.read_parquet(day / "new.parquet")
    assert rows.time_s.tolist() == [1790000000, 1790000010, 1790000020, 1790000030]
    assert rows.alt_m.tolist() == pytest.approx([5450 * 0.3048] * 4)
    assert rows.altitude_basis.tolist() == ["ellipsoidal", "ellipsoidal_interpolated",
                                            "ellipsoidal_interpolated", "ellipsoidal"]
    report = json.loads((day / "new-ingestion-report.json").read_text())
    assert report["barometric_rows"] == 0
    assert report["normalization_scope"] == "full_native_trace_before_segment_selection"
    assert report["selection_max_gap_s"] == 30.0
    selection_meta = pq.read_schema(day / "new.parquet").metadata[b"dopplergeist.selection.v2"]
    assert json.loads(selection_meta)["max_gap_s"] == 30.0
    assert all(hashlib.sha256((day / n).read_bytes()).hexdigest() == h for n, h in original.items())
    # Repeating an old output name must preserve its historical bytes.
    artifact = (day / "new.parquet").read_bytes()
    repeated = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True)
    assert repeated.returncode != 0 and "FileExistsError" in repeated.stderr
    assert (day / "new.parquet").read_bytes() == artifact
