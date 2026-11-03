#!/usr/bin/env python3
"""Retrieve the original NASA MAT files pinned by the session-case manifest.

Download: python scripts/download_nasa_cases.py --output data/nasa-originals
Verify existing originals or file symlinks: add --verify-only to that command.
Downloads require a new directory. Verification writes nothing and uses no network.
"""
import argparse
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib


URL = "https://data.nasa.gov/docs/datasets/rfk401li/small_uav_acoustics.zip"
SOURCE_HOST = "data-nasa-bucket-production.s3.us-east-1.amazonaws.com"
SOURCE_PATH = "/datasets/rfk401li/small_uav_acoustics.zip"
MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/nasa-session-cases-20261103.json"
LIMIT = 64 * 1024**2
RETRIES = 3
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
TRANSIENT_ERRNO = {errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET,
                   errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH,
                   errno.ETIMEDOUT, errno.EPIPE}


def pinned_cases():
    manifest = json.loads(MANIFEST.read_text())
    if (not isinstance(manifest, dict)
            or manifest.get("schema") != "nasa_measured_case_selection_v1"
            or manifest.get("source_archive_url") != URL):
        raise ValueError("The pinned manifest must identify the official NASA archive")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("The pinned manifest contains no cases")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Invalid pinned NASA case")
        name = case.get("case_id")
        size, digest = case.get("size_bytes"), case.get("sha256")
        if (not isinstance(name, str) or not re.fullmatch(r"(?:cub|edge)_flyover_[0-9]{3}", name)
                or name in seen or case.get("archive_member") != f"data/{name}.mat"
                or type(size) is not int or not 0 < size <= LIMIT
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid, duplicate, or oversized pinned NASA member")
        seen.add(name)
    return cases


def transient(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT_HTTP
    if isinstance(error, urllib.error.URLError):
        return transient(error.reason)
    if isinstance(error, socket.gaierror):
        return error.errno == socket.EAI_AGAIN
    return (isinstance(error, (TimeoutError, http.client.IncompleteRead,
                              http.client.RemoteDisconnected, ssl.SSLEOFError))
            or isinstance(error, OSError) and error.errno in TRANSIENT_ERRNO)


class FixedSourceRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        try:
            target = urllib.parse.urlsplit(newurl)
            official_storage = (
                target.scheme == "https" and target.hostname == SOURCE_HOST
                and target.path == SOURCE_PATH and target.username is None
                and target.password is None and target.port in (None, 443)
                and not target.fragment
            )
        except ValueError:
            official_storage = False
        if newurl != URL and not official_storage:
            raise ValueError("NASA redirected outside the approved archive locations")
        # NASA signs this redirect. Keep its query only in the active request;
        # every range starts at URL, with no saved redirect URL or query logging.
        return super().redirect_request(request, response, code, message, headers, newurl)


class Archive:
    """Bounded ZIP reader adapted from PR #96, commit 5582002be34e0e1e9df6735e7a4227ca4c0fc899."""

    def __init__(self):
        self.opener = urllib.request.build_opener(FixedSourceRedirect())
        tail, start, self.size = self.fetch(suffix=131072)
        self.tail, self.tail_start = tail, start
        position = tail.rfind(b"PK\x05\x06")
        if position < 0 or position + 22 > len(tail):
            raise ValueError("Missing ZIP directory terminator")
        end = struct.unpack_from("<4s4H2LH", tail, position)
        if (end[1:3] != (0, 0) or end[3] != end[4] or end[4] == 65535
                or position + 22 + end[7] != len(tail)):
            raise ValueError("Unsupported split/ZIP64 archive or invalid ZIP length")
        self.directory_offset = end[6]
        cursor = end[6] - start
        if cursor < 0 or cursor + end[5] != position:
            raise ValueError("Central directory does not fit the bounded suffix")
        self.members = {}
        while cursor < position:
            if cursor + 46 > position:
                raise ValueError("Truncated central directory entry")
            header = struct.unpack_from("<4s6H3L5H2L", tail, cursor)
            n, extra, comment = header[10:13]
            next_cursor = cursor + 46 + n + extra + comment
            if (header[0] != b"PK\x01\x02" or header[13] != 0 or next_cursor > position
                    or any(header[i] == 0xffffffff for i in (8, 9, 16))):
                raise ValueError("Invalid or unsupported central directory entry")
            name = tail[cursor + 46:cursor + 46 + n].decode("utf-8")
            if name in self.members:
                raise ValueError("Duplicate ZIP member name")
            self.members[name] = dict(name=name, flags=header[3], method=header[4], crc32=header[7],
                compressed_bytes=header[8], bytes=header[9], local_header_offset=header[16])
            cursor = next_cursor
        if len(self.members) != end[4] or cursor != position:
            raise ValueError("Central directory count/length mismatch")

    def fetch(self, lo=None, hi=None, suffix=None):
        if suffix is not None:
            if type(suffix) is not int or not 0 < suffix <= LIMIT:
                raise ValueError("Invalid suffix budget")
            value = f"bytes=-{suffix}"
        else:
            if (type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi
                    or hi - lo + 1 > LIMIT or hasattr(self, "size") and hi >= self.size):
                raise ValueError("Invalid or oversized range")
            value = f"bytes={lo}-{hi}"
            if hasattr(self, "tail") and self.tail_start <= lo <= hi < self.size:
                return self.tail[lo - self.tail_start:hi - self.tail_start + 1], lo, self.size
        for attempt in range(RETRIES + 1):
            request = urllib.request.Request(URL, headers={"Range": value, "Accept-Encoding": "identity"})
            try:
                with self.opener.open(request, timeout=30) as response:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if (response.status != 206 or not match
                            or response.headers.get("Content-Encoding", "identity").lower() != "identity"):
                        raise ValueError("Server did not honor the exact unencoded range request")
                    start, stop, total = map(int, match.groups())
                    expected = stop - start + 1
                    if (not 0 <= start <= stop < total or expected > LIMIT
                            or suffix is not None and (start, stop) != (max(0, total - suffix), total - 1)
                            or suffix is None and (start, stop) != (lo, hi)
                            or hasattr(self, "size") and total != self.size):
                        raise ValueError("Unexpected range bounds or changed archive length")
                    length = response.headers.get("Content-Length")
                    if length is not None and (not length.isdecimal() or int(length) != expected):
                        raise ValueError("Range Content-Length mismatch")
                    data = response.read(expected + 1)
                    if len(data) != expected:
                        raise ValueError("Source range length mismatch")
                    return data, start, total
            except (urllib.error.URLError, OSError, http.client.IncompleteRead,
                    http.client.RemoteDisconnected) as error:
                retry = attempt < RETRIES and transient(error)
                if isinstance(error, urllib.error.HTTPError):
                    error.close()
                if not retry:
                    raise
                print(f"Transient NASA transfer failure; retry {attempt + 1}/{RETRIES}", file=sys.stderr)
                time.sleep(2**attempt)

    def member(self, entry):
        offset = entry["local_header_offset"]
        if (not 0 < entry["bytes"] <= LIMIT or not 0 < entry["compressed_bytes"] <= LIMIT
                or not 0 <= offset < self.directory_offset - 29):
            raise ValueError("Member exceeds the declared download budget")
        header, _, _ = self.fetch(offset, offset + 29)
        h = struct.unpack("<4s5H3L2H", header)
        if (h[0] != b"PK\x03\x04" or h[2] != entry["flags"] or h[2] & (1 | 64)
                or h[3] != entry["method"]):
            raise ValueError("Unsupported or inconsistent local ZIP header")
        if not h[2] & 8 and (h[6], h[7], h[8]) != (entry["crc32"], entry["compressed_bytes"], entry["bytes"]):
            raise ValueError("Local and central ZIP lengths/CRC differ")
        name = entry["name"].encode("utf-8")
        if h[9] != len(name):
            raise ValueError("Local and central ZIP filenames differ")
        local_name, _, _ = self.fetch(offset + 30, offset + 29 + h[9])
        if local_name != name:
            raise ValueError("Local and central ZIP filenames differ")
        start = offset + 30 + h[9] + h[10]
        stop = start + entry["compressed_bytes"] - 1
        if stop >= self.directory_offset:
            raise ValueError("Member overlaps the ZIP directory")
        raw, _, _ = self.fetch(start, stop)
        if entry["method"] == 8:
            decoder = zlib.decompressobj(-15)
            data = decoder.decompress(raw, entry["bytes"] + 1)
            if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                raise ValueError("Member decompression exceeded its declared length")
        elif entry["method"] == 0:
            data = raw
        else:
            raise ValueError("Unsupported member compression")
        if len(data) != entry["bytes"] or zlib.crc32(data) != entry["crc32"]:
            raise ValueError("Member length/CRC mismatch")
        return data


def verify_existing(path, case):
    if not path.is_file():
        raise ValueError(f"Original file is absent or not regular: {path}")
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != case["size_bytes"]:
            raise ValueError(f"Original file size/type mismatch: {path}")
        while chunk := stream.read(min(1024**2, case["size_bytes"] + 1 - size)):
            digest.update(chunk)
            size += len(chunk)
            if size > case["size_bytes"]:
                raise ValueError(f"Original file grew during verification: {path}")
    if size != case["size_bytes"] or digest.hexdigest() != case["sha256"]:
        raise ValueError(f"Original file SHA256/length mismatch: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="New download directory, or existing originals with --verify-only")
    parser.add_argument("--verify-only", action="store_true", help="Verify existing originals or file symlinks without network access or writes")
    args = parser.parse_args()
    cases = pinned_cases()
    if not args.verify_only and (args.output.exists() or args.output.is_symlink()):
        raise FileExistsError("Downloads require a new output directory")
    output = args.output.resolve()
    if args.verify_only:
        if not output.is_dir():
            raise ValueError("Verification requires an existing directory")
        for case in cases:
            path = output / f"{case['case_id']}.mat"
            verify_existing(path, case)
            print(f"Verified {path.name} ({case['size_bytes']} bytes)")
    else:
        output.mkdir(parents=True, exist_ok=False)
        archive = Archive()
        for case in cases:
            entry = archive.members.get(case["archive_member"])
            if entry is None or entry["bytes"] != case["size_bytes"]:
                raise ValueError(f"Pinned NASA member is missing or changed: {case['archive_member']}")
            data = archive.member(entry)
            if hashlib.sha256(data).hexdigest() != case["sha256"]:
                raise ValueError(f"Pinned NASA SHA256 mismatch: {case['archive_member']}")
            path = output / f"{case['case_id']}.mat"
            with path.open("xb") as stream:
                stream.write(data)
            print(f"Downloaded and verified {path.name} ({len(data)} bytes)")
    print(f"Verified {len(cases)} original NASA files in {output}")


if __name__ == "__main__":
    main()
