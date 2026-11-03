"""Inventory published HDF5 metadata without loading pressure signals or following links."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "reader-deps"))
import h5py
import numpy as np


def plain(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


receipt = json.loads((ROOT / "download-receipt.json").read_text())
assert receipt["publisher_integrity_pass"]
records = []


def inspect(obj):
    row = {"path": obj.name, "kind": type(obj).__name__,
           "attributes": {str(k): plain(v) for k, v in obj.attrs.items()}}
    if isinstance(obj, h5py.Dataset):
        row.update(shape=list(obj.shape), dtype=str(obj.dtype), size=int(obj.size))
        if obj.size * obj.dtype.itemsize <= 100_000:
            row["value"] = plain(obj[()])
    records.append(row)
    if isinstance(obj, h5py.Group):
        for name in obj:
            link = obj.get(name, getlink=True)
            if isinstance(link, h5py.HardLink):
                inspect(obj[name])
            else:
                records.append({"path": obj.name.rstrip("/") + "/" + name,
                                "kind": type(link).__name__, "followed": False})


with h5py.File(ROOT / "REC139.h5", "r") as source:
    inspect(source)
report = {"source": receipt, "reader_version": h5py.__version__,
          "hdf5_version": h5py.version.hdf5_version, "numpy_version": np.__version__,
          "reader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "purpose": "Eligibility inspection; no localization or independent field-corpus claim.",
          "objects": records}
(ROOT / "hdf5-metadata.json").write_text(json.dumps(report, indent=2) + "\n")
for row in records:
    display = dict(row)
    value = display.pop("value", None)
    if value is not None:
        text = json.dumps(value)
        display["value_preview"] = text[:700] + ("..." if len(text) > 700 else "")
    print(json.dumps(display))
