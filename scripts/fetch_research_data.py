"""Fetch the paired audio/ADS-B research dataset, verifying its checksums."""
import hashlib
import json
import zipfile
from pathlib import Path

import requests

root = Path(__file__).resolve().parents[1] / "data/research/zenodo-23424278"
root.mkdir(parents=True, exist_ok=True)
s = requests.Session()
r = s.get("https://zenodo.org/api/records/23424278", timeout=60)
r.raise_for_status()
record = r.json()
(root / "record.json").write_text(json.dumps(record, indent=2))
for item in record["files"]:
    path = root / item["key"]
    if not path.exists():
        print("Downloading", item["key"], item["size"], flush=True)
        response = s.get(item["links"]["self"], stream=True, timeout=90)
        response.raise_for_status()
        temporary = path.with_suffix(path.suffix + ".part")
        with temporary.open("wb") as f:
            for chunk in response.iter_content(1024 * 1024):
                f.write(chunk)
        temporary.replace(path)
    algorithm, expected = item["checksum"].split(":")
    with path.open("rb") as f:
        actual = hashlib.file_digest(f, algorithm).hexdigest()
    if actual != expected:
        raise ValueError(f"Checksum mismatch: {path}")
    print("Verified", item["key"], flush=True)
    if path.suffix == ".zip":
        dest = root / "extracted"
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                target = (dest / member.filename).resolve()
                if not target.is_relative_to(dest.resolve()):
                    raise ValueError("Archive member escapes data directory")
            archive.extractall(dest)
