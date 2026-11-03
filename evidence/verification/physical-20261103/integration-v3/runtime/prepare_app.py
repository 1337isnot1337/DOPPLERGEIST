"""Extract a supplied wheel without installing or executing editable hooks."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


def prepare(wheel, output):
    wheel = Path(wheel).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Preserve existing app snapshots: {output}")
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        for item in entries:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"Unsafe wheel entry: {item.filename}")
            if path.parts[0] != "aircraft_geoloc" and not path.parts[0].endswith(".dist-info"):
                raise ValueError(f"Unexpected non-application wheel root: {path.parts[0]}")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError(f"Symlink wheel entry: {item.filename}")
        for required in ("aircraft_geoloc/cli.py", "aircraft_geoloc/jobs.py", "aircraft_geoloc/service.py"):
            if required not in archive.namelist():
                raise ValueError(f"Missing application module: {required}")
        output.mkdir(parents=True)
        archive.extractall(output)
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            files.append({"path": path.relative_to(output).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "bytes": path.stat().st_size})
    receipt = {"wheel": str(wheel), "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
               "app_directory": str(output), "file_count": len(files), "files": files}
    receipt_path = output.with_name(output.name + "-receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.wheel, args.output))
