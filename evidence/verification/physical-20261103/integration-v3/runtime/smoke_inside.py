"""Import, decoder and isolation checks only; no scientific job is submitted."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

started = time.monotonic()
modules = {}
for name in ("numpy", "scipy", "rasterio", "pyarrow", "pandas", "pyproj",
             "soundfile", "matplotlib", "aircraft_geoloc", "aircraft_geoloc.cli",
             "aircraft_geoloc.jobs", "aircraft_geoloc.service"):
    module = importlib.import_module(name)
    location = str(Path(module.__file__).resolve())
    expected = "/app/" if name.startswith("aircraft_geoloc") else "/deps/"
    assert location.startswith(expected), (name, location)
    modules[name] = {"path": location, "version": getattr(module, "__version__", None)}

assert not any(name.startswith("__editable__") for name in sys.modules)
assert not list(Path("/runtime/lib/python3.12/site-packages").iterdir())
assert not list(Path("/proc").iterdir()), "Host /proc must never be mounted"
assert Path.cwd() == Path("/work")
assert "HOME" not in os.environ
assert "CODEX_HOME" not in os.environ
forbidden = [
    "/workspace", "/home", "/root", "/opt", "/host",
    "/inputs/truth", "/inputs/truth.json", "/inputs/evaluation", "/inputs/renderer",
    "/inputs/generation.json", "/data/truth", "/data/truth.json",
    "/app/.git", "/app/scripts", "/app/tests",
]
for path in forbidden:
    assert not Path(path).exists(), f"Forbidden path exposed: {path}"
for root in (Path("/inputs"), Path("/data")):
    for path in root.rglob("*"):
        assert not any(word in path.name.lower() for word in ("truth", "renderer", "generator")), path

# Check real compiled extension entry points, not just package initialization.
import numpy as np
from scipy.linalg import solve
import pyarrow.parquet as pq
import rasterio
from pyproj import Transformer
assert np.allclose(solve(np.eye(2), np.array([2.0, 3.0])), [2, 3])
with rasterio.open("/inputs/terrain.tif") as raster:
    raster_info = {"shape": list(raster.shape), "crs": str(raster.crs),
                   "finite_first_cell": bool(np.isfinite(raster.read(1, window=((0, 1), (0, 1)))).all())}
assert raster_info["finite_first_cell"]
assert np.isfinite(Transformer.from_crs(4979, 4978, always_xy=True).transform(0, 0, 0)).all()
table = pq.ParquetFile("/inputs/tracks.parquet")
parquet_rows = table.metadata.num_rows
probe = subprocess.run(["/usr/bin/ffprobe", "-v", "error", "-show_streams", "-show_format",
                        "-of", "json", "/inputs/recording.mp3"],
                       check=True, capture_output=True, text=True, timeout=30)
media = json.loads(probe.stdout)
assert any(item.get("codec_type") == "audio" for item in media["streams"])
# Run the exact executable/module convention used by the job subprocess.
child = subprocess.run([sys.executable, "-c",
    "import json,sys,aircraft_geoloc.jobs; print(json.dumps({'python':sys.executable,'jobs':aircraft_geoloc.jobs.__file__}))"],
    check=True, capture_output=True, text=True, timeout=30)
child_info = json.loads(child.stdout)
assert child_info["jobs"].startswith("/app/")
cli = subprocess.run([sys.executable, "-m", "aircraft_geoloc.cli", "--help"],
                     check=True, capture_output=True, text=True, timeout=30)
assert "serve" in cli.stdout
audio = Path("/inputs/recording.mp3")
with audio.open("rb") as stream:
    audio_hash = hashlib.file_digest(stream, "sha256").hexdigest()
print(json.dumps({
    "smoke_passed": True, "python": sys.executable, "prefix": sys.prefix,
    "pid": os.getpid(), "cwd": str(Path.cwd()), "sys_path": sys.path,
    "environment_keys": sorted(os.environ), "modules": modules,
    "editable_hooks_loaded": False, "proc_empty": True,
    "forbidden_paths_absent": forbidden, "home_env_absent": True,
    "parquet_rows": parquet_rows, "raster": raster_info,
    "audio_sha256": audio_hash,
    "ffprobe": {"format": media["format"].get("format_name"),
                "duration": media["format"].get("duration"),
                "streams": [{"codec": item.get("codec_name"),
                             "sample_rate": item.get("sample_rate"),
                             "channels": item.get("channels")} for item in media["streams"]]},
    "child": child_info, "cli_help_passed": True,
    "scientific_jobs_submitted": 0, "elapsed_s": time.monotonic()-started
}, indent=2))
