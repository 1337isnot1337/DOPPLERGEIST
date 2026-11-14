#!/usr/bin/env python3
"""Frozen issue #62 native-source study; raw provider observations stay local."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile
import time

import numpy as np
from pyproj import Geod
import requests

DAY = "2024-04-01"
START = datetime(2024, 4, 1, 18, tzinfo=timezone.utc).timestamp()
END = START + 600
TYPES = {"C172", "C182", "PA28", "SR22", "C208", "PC12", "R22", "R44", "B06", "H500"}
SNAPSHOT = "https://samples.adsbexchange.com/readsb-hist/2024/04/01/180000Z.json.gz"
TAG = "v2024.04.01-planes-readsb-prod-0"
RELEASE = f"https://api.github.com/repos/adsblol/globe_history_2024/releases/tags/{TAG}"
GEOD = Geod(ellps="WGS84")


def read_json(path):
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def save_json(path, value):
    with Path(path).open("x") as output:
        output.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def get(session, url, path):
    if not path.exists():
        response = session.get(url, timeout=(15, 60))
        response.raise_for_status()
        # Validate before saving; HTTP content encoding may already be decoded.
        raw = response.content
        json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
        path.write_bytes(raw)
    return read_json(path)


class CountedStream:
    def __init__(self, source, expected):
        self.source, self.expected = source, expected
        self.size, self.digest = 0, hashlib.sha256()

    def read(self, size):
        chunk = self.source.read(size)
        self.size += len(chunk)
        if self.size > self.expected:
            raise ValueError("Archive exceeds its published asset size")
        self.digest.update(chunk)
        return chunk


def acquire(root):
    session = requests.Session()
    session.headers.update({"User-Agent": "DOPPLERGEIST-issue62-native-comparison", "Accept-Encoding": "identity"})
    snapshot = get(session, SNAPSHOT, root / "adsbx-180000Z.json.gz")
    if not START <= snapshot["now"] < START + 5:
        raise ValueError("Snapshot timestamp does not match the frozen selection window")
    rows = [r for r in snapshot["aircraft"] if r.get("t") in TYPES
            and re.fullmatch(r"[0-9a-f]{6}", r["hex"])
            and r.get("seen_pos", 1e9) <= 10
            and type(r.get("alt_baro")) in (int, float) and r["alt_baro"] > 0
            and -125 <= r.get("lon", 1e9) <= -66 and 24 <= r.get("lat", 1e9) <= 50]
    rows = sorted(rows, key=lambda row: row["hex"])[:24]
    expected = [{"icao": row["hex"], "type": row["t"]} for row in rows]
    cohort_path = root / "cohort.json"
    if not cohort_path.exists():
        save_json(cohort_path, {"source": "ADS-B Exchange public evaluation sample",
                               "snapshot_utc": snapshot["now"],
                               "window_utc": ["2024-04-01T18:00:00Z", "2024-04-01T18:10:00Z"],
                               "selection": "Frozen issue62 protocol; source-conditioned, not random",
                               "aircraft": expected})
    cohort = read_json(cohort_path)
    selected = {row["icao"] for row in cohort["aircraft"]}
    if (not selected or cohort["aircraft"] != expected or cohort["snapshot_utc"] != snapshot["now"]
            or any(not re.fullmatch(r"[0-9a-f]{6}", value) for value in selected)):
        raise ValueError("Cohort does not match the frozen source-selection protocol")
    index = get(session, "https://samples.adsbexchange.com/hires-traces/2024/04/01/index.json",
                root / "adsbx-trace-index.json")
    for provider in ("adsbx", "adsblol"):
        (root / provider).mkdir(exist_ok=True)
    for icao in sorted(selected):
        if icao not in index["traces"]:
            continue
        get(session, f"https://samples.adsbexchange.com/hires-traces/2024/04/01/{icao[-2:]}/trace_full_{icao}.json",
            root / "adsbx" / f"{icao}.json")
        time.sleep(0.5)
    if (root / "acquisition.json").exists():
        return
    release = get(session, RELEASE, root / "adsblol-release.json")
    assets = [asset for asset in release["assets"] if asset["name"] == TAG + ".tar"]
    if release["tag_name"] != TAG or len(assets) != 1:
        raise ValueError("Unexpected ADSB.lol release/asset layout")
    asset = assets[0]
    found = set()
    with session.get(asset["browser_download_url"], stream=True, timeout=(15, 60)) as response:
        response.raise_for_status()
        source = CountedStream(response.raw, asset["size"])
        with tarfile.open(fileobj=source, mode="r|") as archive:
            for member in archive:
                match = re.fullmatch(r"trace_full_([0-9a-f]{6})\.json(?:\.gz)?", Path(member.name).name)
                if not member.isfile() or not match or match[1] not in selected:
                    continue
                if member.size > 32 * 1024 * 1024:
                    raise ValueError("Selected native trace exceeds the declared 32 MiB member limit")
                raw = archive.extractfile(member).read()
                json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
                destination = root / "adsblol" / f"{match[1]}.json"
                if destination.exists() and destination.read_bytes() != raw:
                    raise ValueError("Conflicting native trace for the same source/ICAO")
                destination.write_bytes(raw)
                found.add(match[1])
        while source.read(1024 * 1024):
            pass
    if source.size != asset["size"]:
        raise ValueError("Archive size differs from release metadata")
    digest = "sha256:" + source.digest.hexdigest()
    if asset.get("digest") and asset["digest"] != digest:
        raise ValueError("Archive differs from the provider digest")
    save_json(root / "acquisition.json", {"release_tag": TAG, "bytes_read": source.size,
                                          "computed_digest": digest, "provider_digest": asset.get("digest"),
                                          "selected_aircraft": len(selected), "adsblol_traces": len(found)})


def points(path):
    data = read_json(path)
    rows = []
    for point in data["trace"]:
        stamp = data["timestamp"] + point[0]
        if START <= stamp <= END and type(point[3]) in (int, float):
            flags = point[6]
            metadata = point[8] if len(point) > 8 and isinstance(point[8], dict) else {}
            rows.append({"time": stamp, "lat": point[1], "lon": point[2], "flags": flags,
                         "barometric_m": None if flags & 8 else point[3] * 0.3048,
                         "geometric_m": point[3] * 0.3048 if flags & 8 else
                         point[10] * 0.3048 if len(point) > 10 and point[10] is not None else None,
                         "speed_mps": point[4] * 1852 / 3600 if point[4] is not None else None,
                         "heading_deg": point[5], "origin": point[9] if len(point) > 9 else None,
                         "type": metadata.get("t", data.get("t"))})
    rows.sort(key=lambda row: row["time"])
    return rows


def distribution(values):
    if not values:
        return {"count": 0}
    return dict(zip(("count", "min", "median", "p95", "max"),
                    [len(values), *np.quantile(values, [0, 0.5, 0.95, 1]).tolist()]))


def compare(root, output):
    cohort = read_json(root / "cohort.json")
    outcomes, all_differences = [], {key: [] for key in ("epoch_delta_s", "horizontal_m", "barometric_m", "geometric_m", "speed_mps", "heading_deg")}
    for selected in cohort["aircraft"]:
        icao = selected["icao"]
        paths = [root / provider / f"{icao}.json" for provider in ("adsbx", "adsblol")]
        if not all(path.exists() for path in paths):
            outcomes.append({"icao": icao, "status": "missing_native_source"})
            continue
        source_rows = [points(path) for path in paths]
        types = [{row["type"] for row in rows} for rows in source_rows]
        outcome = {"icao": icao, "type": selected["type"], "source_rows": [len(rows) for rows in source_rows],
                   "native_gap_s": [distribution(np.diff([row["time"] for row in rows]).tolist()) for rows in source_rows]}
        if not all(source_rows):
            outcomes.append({**outcome, "status": "no_native_points_in_window"})
            continue
        if any(values != {selected["type"]} for values in types):
            outcomes.append({**outcome, "status": "missing_or_conflicting_native_type"})
            continue
        clean = []
        for rows in source_rows:
            counts = Counter(row["time"] for row in rows)
            clean.append([row for row in rows if counts[row["time"]] == 1 and not row["flags"] & 1])
        outcome["unique_nonstale_rows"] = [len(rows) for rows in clean]
        outcome["excluded_duplicate_or_stale_rows"] = [len(rows) - len(eligible) for rows, eligible in zip(source_rows, clean)]
        matches, used, origins = 0, set(), Counter()
        btimes = np.array([row["time"] for row in clean[1]])
        differences = {key: [] for key in all_differences}
        for a in clean[0]:
            index = int(np.searchsorted(btimes, a["time"]))
            choices = [i for i in (index - 1, index) if 0 <= i < len(btimes) and i not in used]
            if not choices:
                continue
            index = min(choices, key=lambda i: abs(btimes[i] - a["time"]))
            b = clean[1][index]
            if abs(a["time"] - b["time"]) > 0.25:
                continue
            used.add(index)
            matches += 1
            origins[f"{a['origin']} / {b['origin']}"] += 1
            differences["epoch_delta_s"].append(a["time"] - b["time"])
            differences["horizontal_m"].append(GEOD.inv(a["lon"], a["lat"], b["lon"], b["lat"])[2])
            for key in ("barometric_m", "geometric_m", "speed_mps", "heading_deg"):
                if a[key] is not None and b[key] is not None:
                    value = a[key] - b[key]
                    differences[key].append((value + 180) % 360 - 180 if key == "heading_deg" else value)
        for key, values in differences.items():
            all_differences[key].extend(values)
        outcomes.append({**outcome, "status": "compared", "native_pairs": matches, "origins": dict(origins),
                         "differences": {key: distribution(values) for key, values in differences.items()},
                         "absolute_differences": {key: distribution(np.abs(values).tolist()) for key, values in differences.items()}})
    report = {"protocol": "issue62-native-v1", "date": DAY, "window_unix_s": [START, END],
              "native_match_tolerance_s": 0.25, "interpolation": "none", "aircraft": outcomes,
              "pairing": "ADS-B Exchange native order; nearest unused ADSB.lol sample within tolerance",
              "aggregate": {key: distribution(values) for key, values in all_differences.items()},
              "absolute_aggregate": {key: distribution(np.abs(values).tolist()) for key, values in all_differences.items()},
              "limits": ["Source-conditioned finite cohort; receiver/feed overlap is unresolved.",
                         "Native samples within 0.25 s remain different epochs; horizontal differences include motion.",
                         "Altitude datums are separate. Missing observations and types are not zero discrepancies.",
                         "No audio, source-swap localization, location accuracy or source equivalence is established."]}
    save_json(output, report)
    print(json.dumps({"statuses": dict(Counter(row["status"] for row in outcomes)), "aggregate": report["aggregate"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="New comparison file; defaults to ROOT/comparison.json")
    parser.add_argument("--acquire", action="store_true", help="Download only the frozen public-source cohort")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.acquire:
        acquire(args.root)
    compare(args.root, args.output or args.root / "comparison.json")
