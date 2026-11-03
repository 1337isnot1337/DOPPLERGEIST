"""Compare digest paths on disposable copies of a restored real flight index."""
import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import tempfile
import time

from dopplergeist.data_access import FlightIndex, cached_sha256, sha256, write_json


def timed(function, expected):
    wall, cpu = time.perf_counter(), time.process_time()
    digest = function()
    result = {"wall_s": time.perf_counter() - wall, "cpu_s": time.process_time() - cpu}
    if digest != expected:
        raise AssertionError("Digest differs from directly read source bytes")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--passes", type=int, default=9)
    args = parser.parse_args()
    if args.passes < 3:
        parser.error("Use at least three alternating passes")
    index = FlightIndex(args.index)
    expected = sha256(args.index)
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(dir=args.output) as temporary:
        root = Path(temporary)
        writable = root / "writable.sqlite"
        readonly_dir = root / "read-only"
        readonly_dir.mkdir()
        readonly = readonly_dir / "observed.sqlite"
        for path in (writable, readonly):
            shutil.copyfile(args.index, path)
        readonly.chmod(0o444)
        readonly_dir.chmod(0o555)
        try:
            if os.access(readonly_dir, os.W_OK):
                raise RuntimeError("Current account bypasses read-only directory permissions")
            cold = timed(lambda: cached_sha256(writable), expected)
            functions = {"direct": lambda: sha256(writable),
                         "warm_cached": lambda: cached_sha256(writable),
                         "read_only_fallback": lambda: cached_sha256(readonly)}
            trials = {name: [] for name in functions}
            for iteration in range(args.passes):
                names = list(functions)
                for name in names if iteration % 2 == 0 else reversed(names):
                    trials[name].append(timed(functions[name], expected))
            if list(readonly_dir.iterdir()) != [readonly]:
                raise AssertionError("Read-only fallback wrote cache metadata")
        finally:
            readonly_dir.chmod(0o755)
    medians = {name: {kind: statistics.median(trial[kind] for trial in values)
                     for kind in ("wall_s", "cpu_s")} for name, values in trials.items()}
    report = {"scope": "Repeated digest computation for one restored historical index; "
                       "excludes acquisition, trajectory decoding and search",
              "index_input_hash": index.report["input_hash"], "file_bytes": args.index.stat().st_size,
              "passes": args.passes, "initial_cached_call": cold, "trials": trials, "medians": medians,
              "warm_digest_wall_speedup": medians["direct"]["wall_s"] / medians["warm_cached"]["wall_s"],
              "all_digests_equal_direct_source_hash": True,
              "read_only_fallback_wrote_no_metadata": True}
    write_json(args.output / "summary.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "trials"}, indent=2))


if __name__ == "__main__":
    main()
