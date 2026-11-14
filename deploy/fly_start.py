"""Initialize Fly's persistent volume, then run the application as UID 10001."""
import os
from pathlib import Path
import sys

from dopplergeist.service import hosted_settings


def main():
    origin, _ = hosted_settings()
    if origin is None:
        raise ValueError("Fly startup requires hosted authentication settings")
    os.umask(0o077)
    for name in ("jobs", ".cache", ".cache/dopplergeist", ".config"):
        directory = Path("/data") / name
        if directory.is_symlink():
            raise ValueError("Fly data directories must not be symbolic links")
        directory.mkdir(exist_ok=True)
        os.chown(directory, 10001, 10001)
    os.chown("/data", 10001, 10001)
    # --online uses ~/.cache/dopplergeist, so put the whole cache on the volume.
    os.environ["HOME"] = "/data"
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
    os.execvp("dopplergeist", ["dopplergeist", *sys.argv[1:]])


if __name__ == "__main__":
    main()
