#!/usr/bin/env python3
"""Bounded, checksummed inspection of NASA's public 2016 flyover ZIP.

This inspects acquisition metadata only. It performs no localization or claim of
benchmark eligibility. Raw files stay in the new local output directory.
"""
import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import urllib.request
import zlib

URL = "https://data.nasa.gov/docs/datasets/rfk401li/small_uav_acoustics.zip"
LIMIT = 64 * 1024**2


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Archive:
    def __init__(self):
        self.requests = []
        tail, start, self.size = self.fetch(suffix=131072)
        self.tail, self.tail_start = tail, start
        position = tail.rfind(b"PK\x05\x06")
        if position < 0:
            raise ValueError("Missing ordinary ZIP directory terminator")
        end = struct.unpack_from("<4s4H2LH", tail, position)
        if end[1:3] != (0, 0) or end[3] != end[4] or end[4] == 65535:
            raise ValueError("Unsupported split/ZIP64 archive")
        self.directory_offset = end[6]
        cursor = end[6] - start
        if cursor < 0 or cursor + end[5] != position:
            raise ValueError("Central directory does not fit the bounded suffix")
        self.members = []
        while cursor < position:
            h = struct.unpack_from("<4s6H3L5H2L", tail, cursor)
            if h[0] != b"PK\x01\x02":
                raise ValueError("Invalid central directory entry")
            n, extra, comment = h[10:13]
            name = tail[cursor+46:cursor+46+n].decode("utf-8")
            self.members.append(dict(name=name, flags=h[3], method=h[4], crc32=h[7],
                compressed_bytes=h[8], bytes=h[9], local_header_offset=h[16]))
            cursor += 46+n+extra+comment
        if len(self.members) != end[4] or cursor != position:
            raise ValueError("Central directory count/length mismatch")

    def fetch(self, lo=None, hi=None, suffix=None):
        value = f"bytes=-{suffix}" if suffix else f"bytes={lo}-{hi}"
        if not suffix and hasattr(self, "tail") and self.tail_start <= lo <= hi < self.size:
            data = self.tail[lo-self.tail_start:hi-self.tail_start+1]
            self.requests.append(dict(range=value, source="verified_suffix", bytes=len(data), sha256=digest(data)))
            return data, lo, self.size
        request = urllib.request.Request(URL, headers={"Range": value})
        with urllib.request.urlopen(request, timeout=30) as response:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if response.status != 206 or not match:
                raise ValueError("Server did not honor the bounded range request")
            start, stop, total = map(int, match.groups())
            expected = stop-start+1
            if expected > LIMIT or (suffix and expected > suffix) or (not suffix and (start, stop) != (lo, hi)):
                raise ValueError("Unexpected/oversized source range")
            data = response.read(expected+1)
            if len(data) != expected:
                raise ValueError("Source range length mismatch")
            self.requests.append(dict(range=value, content_range=match.group(), bytes=len(data), sha256=digest(data)))
            return data, start, total

    def member(self, entry):
        offset = entry["local_header_offset"]
        header, _, _ = self.fetch(offset, offset+29)
        h = struct.unpack("<4s5H3L2H", header)
        if h[0] != b"PK\x03\x04" or h[2] & 1 or h[3] != entry["method"]:
            raise ValueError("Unsupported local ZIP member header")
        start = offset+30+h[9]+h[10]
        stop = start+entry["compressed_bytes"]-1
        if stop >= self.directory_offset or entry["bytes"] > LIMIT:
            raise ValueError("Member exceeds the declared inspection budget")
        raw, _, _ = self.fetch(start, stop)
        if entry["method"] == 8:
            decoder = zlib.decompressobj(-15)
            data = decoder.decompress(raw, entry["bytes"]+1)
            if not decoder.eof or decoder.unconsumed_tail:
                raise ValueError("Member decompression exceeded its declared length")
        elif entry["method"] == 0:
            data = raw
        else:
            raise ValueError("Unsupported member compression")
        if len(data) != entry["bytes"] or zlib.crc32(data) != entry["crc32"]:
            raise ValueError("Member length/CRC mismatch")
        return data


def summarize(value):
    import numpy as np
    def number(x):
        return float(x) if np.isfinite(x) else None
    if isinstance(value, dict):
        return {k: summarize(v) for k, v in value.items() if not k.startswith("__")}
    if isinstance(value, np.ndarray):
        result = dict(shape=list(value.shape), dtype=str(value.dtype))
        if value.dtype.kind in "fiu" and value.size:
            finite = np.isfinite(value)
            result.update(finite_count=int(finite.sum()), min=float(value[finite].min()) if finite.any() else None,
                          max=float(value[finite].max()) if finite.any() else None)
            if value.ndim == 1:
                result.update(first=number(value[0]), last=number(value[-1]))
                if value.size > 1:
                    steps = np.diff(value)
                    result.update(step_min=number(steps.min()), step_max=number(steps.max()),
                                  step_median=number(np.median(steps)))
        return result
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first-fixed-wing", action="store_true", help="Inspect first lexical Cub and Edge member; no acoustic selection")
    parser.add_argument("--source-cache", type=Path, help="Reuse local members only after public-directory length/CRC verification")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.output / "source"
    source.mkdir()
    archive = Archive()
    selected = [e for e in archive.members if not e["name"].startswith("data/")]
    if args.first_fixed_wing:
        for vehicle in ("cub", "edge"):
            selected.append(min((e for e in archive.members if e["name"].startswith(f"data/{vehicle}_")), key=lambda e: e["name"]))
    receipt = dict(source=URL, archive_bytes=archive.size, inventory=archive.members,
                   selection="All companions; optional first lexical member for each fixed-wing vehicle", files=[],
                   script_sha256=digest(Path(__file__).read_bytes()), localization_performed=False,
                   eligibility="unproven; metadata inspection only")
    for entry in selected:
        cached = args.source_cache / Path(entry["name"]).name if args.source_cache else None
        if cached and cached.is_file():
            data = cached.read_bytes()
            if len(data) != entry["bytes"] or zlib.crc32(data) != entry["crc32"]:
                raise ValueError("Cached member length/CRC mismatch")
        else:
            data = archive.member(entry)
        path = source / Path(entry["name"]).name
        path.write_bytes(data)
        item = dict(name=entry["name"], bytes=len(data), sha256=digest(data), crc32_verified=True,
                    acquisition="verified_existing_member" if cached and cached.is_file() else "public_range_download")
        if path.suffix == ".xlsx":
            import openpyxl
            book = openpyxl.load_workbook(path, read_only=True, data_only=True)
            item["sheets"] = {sheet.title: [[v.isoformat() if isinstance(v, (date, datetime)) else v for v in row]
                for row in sheet.iter_rows(values_only=True)] for sheet in book}
            book.close()
        if path.suffix == ".mat":
            from scipy.io import loadmat, whosmat
            item["mat_variables"] = whosmat(path)
            item["metadata"] = summarize(loadmat(path, simplify_cells=True))
        receipt["files"].append(item)
        receipt.update(requests=archive.requests, status="partial")
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n")
    receipt["requests"] = archive.requests
    receipt["status"] = "complete"
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"archive_bytes": archive.size, "members": len(archive.members),
                      "inspected": [f["name"] for f in receipt["files"]], "output": str(args.output)}))


if __name__ == "__main__":
    main()
