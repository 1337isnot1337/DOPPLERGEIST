"""Launch the existing product in a minimal, label-isolated mount namespace.

This wrapper performs no detection, association, localization or evaluation.
Use scripts/verify_upload.py outside the namespace for the actual HTTP client.
"""
import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def directory(value):
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f"Not a directory: {path}")
    return path


def build_command(args):
    config = json.loads(args.config.read_text())
    python_prefix = directory(config["python_prefix"])
    dependencies = directory(config["dependency_site_packages"])
    app = directory(args.app or config["app_directory"])
    inputs = directory(args.inputs or config["fixture_inputs"])
    data = directory(args.data or config["prepared_inputs"])
    work = directory(args.work)
    if not (app / "aircraft_geoloc/cli.py").is_file():
        raise ValueError("App directory must be an extracted product wheel")
    if any((app / name).exists() for name in (".git", "scripts", "tests")):
        raise ValueError("Do not mount a source checkout as the application")
    if not (inputs / "recording.mp3").is_file() or not (data / "operator.json").is_file():
        raise ValueError("Expected label-free fixture and prepared operator inputs")
    # A broad ancestor mount could expose the benchmark's adjacent truth files.
    for path in (python_prefix, dependencies, app, inputs, data):
        if work == path or work in path.parents or path in work.parents:
            raise ValueError(f"Work directory must not overlap a read-only mount: {path}")
    if work == HERE or work in HERE.parents:
        raise ValueError("Use a dedicated output directory, not the runtime/artifact parent")
    version = config["python_version"]
    python = f"/runtime/bin/python{version}"
    command = [
        config["bwrap"], "--unshare-user", "--unshare-pid", "--die-with-parent",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--dir", "/etc",
        "--ro-bind", "/etc/alternatives", "/etc/alternatives",
        "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--dir", "/dev",
        "--ro-bind", "/dev/null", "/dev/null",
        "--ro-bind", "/dev/urandom", "/dev/urandom",
        "--dir", "/proc",
        "--tmpfs", "/tmp",
        "--ro-bind", str(python_prefix), "/runtime",
        # Only the interpreter/stdlib from the base prefix is visible to site.py.
        "--tmpfs", f"/runtime/lib/python{version}/site-packages",
        "--ro-bind", str(dependencies), "/deps",
        "--ro-bind", str(app), "/app",
        "--ro-bind", str(inputs), "/inputs",
        "--ro-bind", str(data), "/data",
        "--bind", str(work), "/work",
        "--chdir", "/work",
        "--setenv", "PATH", "/runtime/bin:/usr/bin",
        "--setenv", "PYTHONHOME", "/runtime",
        "--setenv", "PYTHONPATH", "/app:/deps",
        "--setenv", "PYTHONNOUSERSITE", "1",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "LC_ALL", "C.UTF-8",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "MPLCONFIGDIR", "/tmp/matplotlib",
        "--setenv", "XDG_CACHE_HOME", "/tmp/cache",
        "--setenv", "OPENBLAS_NUM_THREADS", "1",
        "--setenv", "OMP_NUM_THREADS", "1",
    ]
    if args.smoke:
        source = (HERE / "smoke_inside.py").read_text()
        command += [python, "-c", source]
    else:
        tail = list(args.command)
        if tail[:1] == ["--"]:
            tail.pop(0)
        if not tail:
            raise ValueError("Supply a command after --, or select --smoke")
        command += tail
    return command


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "runtime.json")
    parser.add_argument("--app", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    invocation = build_command(arguments)
    if arguments.describe:
        print(json.dumps(invocation, indent=2))
    else:
        os.execv(invocation[0], invocation)
