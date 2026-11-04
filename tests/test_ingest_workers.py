"""Software check: the parallel ingest writes the same table and report as the serial one."""
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pyarrow.parquet as pq


def _member(index):
    lat = 40.05 if index % 3 else 45.0
    trace = {"icao": f"f{index:04d}", "timestamp": 1790000000 + index, "t": "B738" if index % 7 == 0 else "PC12",
             "trace": [[t, lat + t * 1e-4, -100, 5000, 100, 90, 0, 0, {}, 0, 5450, None] for t in (0, 10, 20)]}
    raw = json.dumps(trace).encode()
    return gzip.compress(raw) if index % 2 else raw


def test_worker_count_does_not_change_output(tmp_path):
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "isolated-project"
    (project / "scripts").mkdir(parents=True)
    script = project / "scripts/ingest_adsblol_day.py"
    shutil.copyfile(root / "scripts/ingest_adsblol_day.py", script)
    (project / "data/source").mkdir(parents=True)
    (project / "data/source/icao_aircraft_types.json").write_text('{"B738": {"desc": "L2J"}, "PC12": {"desc": "L1T"}}')
    day = project / "data/adsb/2026-09-22"
    day.mkdir(parents=True)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as output:
        output.addfile(tarfile.TarInfo("traces/readme.txt"), io.BytesIO(b""))
        # More members than one task batch x in-flight window, so ordering across batches is exercised.
        for index in range(700):
            member = _member(index)
            info = tarfile.TarInfo(f"traces/trace_full_f{index:04d}.json")
            info.size = len(member)
            output.addfile(info, io.BytesIO(member))
    raw = archive.getvalue()
    (day / "archive.tar.aa").write_bytes(raw[:len(raw) // 2])
    (day / "archive.tar.ab").write_bytes(raw[len(raw) // 2:])
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    outputs = {}
    for workers in (1, 3):
        name = f"w{workers}.parquet"
        result = subprocess.run([sys.executable, str(script), "2026-09-22", "--output", name, "--workers", str(workers),
                                 "--bounds", "-101", "40", "-99", "41"], cwd=project, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        outputs[workers] = (pq.read_table(day / name), json.loads((day / f"w{workers}-ingestion-report.json").read_text()))
    (serial, serial_report), (parallel, parallel_report) = outputs[1], outputs[3]
    assert serial_report == parallel_report
    assert serial_report["trace_files"] == 700 and serial_report["known_jets_removed"] == 100
    assert serial_report["retained_aircraft"] > 0 and serial_report["no_conus_points"] > 0
    assert parallel.schema.equals(serial.schema, check_metadata=True)
    assert parallel.equals(serial)
