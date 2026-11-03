"""Collect public audio and run acoustic discovery only; never match flights.

Media and detailed results belong outside Git. The JSON search plan selects clips
before scanning; export retains download failures and zero-proposal recordings.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import asdict
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode

import requests


def text(value):
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def page(url):
    response = requests.get(url, timeout=40)
    response.raise_for_status()
    return response.text


def freesound_metadata(url):
    body = page(url)
    sound_id = re.search(r"/sounds/(\d+)/", url)[1]
    preview = re.search(r'data-static-file-url="([^"]+)"', body)
    if preview is None:
        preview = re.search(r'data-mp3="([^"]+)"', body)
    title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    license_url = re.search(r'href="(https?://creativecommons.org/[^"]+)"', body)
    location = re.search(r'title="Geotag: ([^"]+)"', body)
    # Preserve the publisher's descriptive text for equipment/context review.
    description = re.search(r'<div[^>]+id="sound-description"[^>]*>(.*?)</div>', body, re.S)
    if description is None:
        description = re.search(r'<div[^>]+class="[^"]*sound-description[^"]*"[^>]*>(.*?)</div>', body, re.S)
    if description is None:
        description = re.search(r'<meta name="twitter:description" content="([^"]*)"', body, re.S)
    result = {"id": "fs-" + sound_id, "source": "freesound", "url": url,
              "title": text(title[1]) if title else sound_id,
              "uploader": url.split("/people/")[1].split("/")[0],
              "media_url": html.unescape(preview[1]) if preview else None,
              "duration_s": float(re.search(r'data-duration="([^"]+)"', body)[1]),
              "license": license_url[1] if license_url else "unspecified",
              "description": text(description[1]) if description else "",
              "location_status": "unresolved", "location_label": "",
              "latitude": None, "longitude": None}
    geotag = re.search(r'data-modal-content-url="([^"]+/geotag/[^\"]*)"', body)
    if geotag:
        geo = page("https://freesound.org" + html.unescape(geotag[1]))
        lat = re.search(r'data-map-center-lat="([^"]+)"', geo)
        lon = re.search(r'data-map-center-lon="([^"]+)"', geo)
        if lat and lon:
            result.update(location_status="publisher_geotag", latitude=float(lat[1]),
                          longitude=float(lon[1]), location_label=html.unescape(location[1]) if location else "",
                          location_accuracy="Publisher map pin; microphone accuracy unverified")
    return result


def search(args):
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    catalog = root / "sources.jsonl"
    known = {row["id"] for row in read_catalog(root)}
    for query in json.loads(Path(args.plan).read_text()):
        print("SEARCH", query["source"], query["query"], flush=True)
        try:
            if query["source"] == "youtube":
                completed = subprocess.run(
                    [args.yt_dlp, "--flat-playlist", "--dump-single-json", "--socket-timeout", "20",
                     f"ytsearch{query.get('limit', 8)}:{query['query']}"],
                    capture_output=True, text=True, timeout=120, check=True)
                entries = json.loads(completed.stdout).get("entries", [])
                rows = [{"id": "yt-" + entry["id"], "source": "youtube",
                         "url": "https://www.youtube.com/watch?v=" + entry["id"],
                         "title": entry.get("title"), "uploader": entry.get("channel"),
                         "duration_s": entry.get("duration"), "description": entry.get("description", ""),
                         "location_status": "unresolved", "location_label": "",
                         "license": "YouTube source; redistribution permission not established"}
                        for entry in entries if entry.get("id")]
            else:
                urls = []
                for number in range(1, query.get("pages", 1) + 1):
                    body = page("https://freesound.org/search/?" + urlencode({"q": query["query"], "page": number}))
                    urls.extend("https://freesound.org" + match for match in
                                re.findall(r'href="(/people/[^/\"]+/sounds/\d+/)"', body))
                    time.sleep(0.3)
                urls = [url for url in dict.fromkeys(urls)
                        if "fs-" + re.search(r"/sounds/(\d+)/", url)[1] not in known]
                rows = []
                with ThreadPoolExecutor(max_workers=3) as pool:
                    pending = {pool.submit(freesound_metadata, url): url for url in urls}
                    for future in as_completed(pending):
                        try:
                            rows.append(future.result())
                        except Exception as exc:
                            print("METADATA FAILED", pending[future], str(exc)[:180], flush=True)
                rows.sort(key=lambda row: urls.index(row["url"]))
            for row in rows:
                if row["id"] in known:
                    continue
                known.add(row["id"])
                row.update(query=query["query"], category=query["category"],
                           recording_clock_status="not_established", review="pending")
                root.mkdir(parents=True, exist_ok=True)
                with catalog.open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
            print("CATALOG", len(known), flush=True)
        except Exception as exc:
            with (root / "search-errors.jsonl").open("a") as stream:
                stream.write(json.dumps({"query": query, "error": str(exc)[:500]}) + "\n")
            print("SEARCH FAILED", str(exc)[:180], flush=True)


def read_catalog(root):
    path = root / "sources.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def scan_one(args):
    from dopplergeist.discovery import DiscoverySettings, discover_events
    from dopplergeist.intake import intake_recording
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="decode-", dir=Path(args.output).parent) as temporary:
        recording = intake_recording(args.audio, temporary)
        events = discover_events(recording)
        groups = {event.get("harmonic_group_id", event["event_id"]) for event in events}
        save(Path(args.output), {"status": "scanned", "duration_s": recording.metadata["duration_s"],
                                "sample_rate_hz": recording.metadata["sample_rate_hz"],
                                "settings": asdict(DiscoverySettings()), "events": events,
                                "ridge_count": len(events), "proposal_count": len(groups),
                                "scanner_result": "proposals" if groups else "no_proposals",
                                "runtime_s": round(time.monotonic() - began, 3),
                                "interpretation": "Moving-tone proposals; aircraft identity and usability require review"})


def process(row, args):
    root = Path(args.root)
    result_path = root / "scans" / (row["id"] + ".json")
    if result_path.exists():
        result = json.loads(result_path.read_text())
        if result.get("status") == "scanned" or not args.retry:
            return row["id"], result.get("scanner_result", result.get("status"))
    result_path.parent.mkdir(parents=True, exist_ok=True)
    audio = root / "audio" / (row["id"] + ".mp3")
    audio.parent.mkdir(parents=True, exist_ok=True)
    log_path = root / "logs" / (row["id"] + ".txt")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stage = "download"
    try:
        if not audio.exists():
            with log_path.open("w") as log:
                with tempfile.TemporaryDirectory(prefix=row["id"] + "-", dir=audio.parent) as temporary:
                    target = Path(temporary) / "clip.mp3"
                    if row["source"] == "youtube":
                        command = [args.yt_dlp, "--no-playlist", "--no-progress", "--socket-timeout", "20",
                                   "--retries", "1", "--fragment-retries", "1", "--no-warnings", "--write-info-json",
                                   "--download-sections", f"*0-{args.seconds}", "-f", "bestaudio/best",
                                   "-x", "--audio-format", "mp3", "--audio-quality", "3",
                                   "-o", str(target.with_suffix(".%(ext)s")), row["url"]]
                        subprocess.run(command, stdout=log, stderr=log, timeout=args.download_timeout, check=True)
                        info = json.loads((target.parent / "clip.info.json").read_text())
                        save(root / "source-details" / (row["id"] + ".json"),
                             {key: info.get(key) for key in ("title", "description", "uploader", "license", "duration", "is_live")})
                    else:
                        response = requests.get(row["media_url"], timeout=60)
                        response.raise_for_status()
                        original = Path(temporary) / "original.mp3"
                        original.write_bytes(response.content)
                        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(original),
                                        "-t", str(args.seconds), "-vn", "-c:a", "libmp3lame", "-q:a", "3", str(target)],
                                       stdout=log, stderr=log, timeout=90, check=True)
                    target.replace(audio)
        stage = "scan"
        with log_path.open("a") as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "scan-one", str(audio),
                            "--output", str(result_path)], stdout=log, stderr=log, timeout=args.scan_timeout, check=True)
        return row["id"], json.loads(result_path.read_text())["scanner_result"]
    except Exception as exc:
        save(result_path, {"status": stage + "_failed", "error": str(exc)[:500]})
        return row["id"], stage + "_failed"


def run(args):
    rows = read_catalog(Path(args.root))
    if args.category:
        rows = [row for row in rows if row["category"] in args.category]
    if args.limit:
        rows = rows[:args.limit]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process, row, args) for row in rows]
        for index, future in enumerate(as_completed(futures), 1):
            print(index, len(rows), *future.result(), flush=True)
    export(args)


def export(args):
    root = Path(args.root)
    rows = read_catalog(root)
    reviews_path = root / "reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
    fields = ["id", "source", "url", "title", "uploader", "category", "query", "clip_start_s",
              "duration_s", "status", "scanner_result", "proposal_count", "ridge_count", "review",
              "location_status", "location_label", "latitude", "longitude", "location_accuracy",
              "recording_clock_status", "license", "notes", "error"]
    counts = {}
    with (root / "catalog.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            result_path = root / "scans" / (row["id"] + ".json")
            result = json.loads(result_path.read_text()) if result_path.exists() else {"status": "not_scanned"}
            record = {**row, **{k: v for k, v in result.items() if k != "events"},
                      "clip_start_s": 0, **reviews.get(row["id"], {})}
            writer.writerow(record)
            counts[record["status"]] = counts.get(record["status"], 0) + 1
    print("TOTAL", len(rows), counts, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    find = sub.add_parser("search")
    find.add_argument("--plan", required=True)
    scan = sub.add_parser("scan-one")
    scan.add_argument("audio")
    scan.add_argument("--output", required=True)
    batch = sub.add_parser("run")
    batch.add_argument("--workers", type=int, default=2)
    batch.add_argument("--seconds", type=int, default=180)
    batch.add_argument("--limit", type=int)
    batch.add_argument("--category", action="append")
    batch.add_argument("--download-timeout", type=int, default=240)
    batch.add_argument("--scan-timeout", type=int, default=180)
    batch.add_argument("--retry", action="store_true")
    report = sub.add_parser("export")
    for command in (find, batch, report):
        command.add_argument("--root", required=True)
    for command in (find, batch):
        command.add_argument("--yt-dlp", default="yt-dlp")
    args = parser.parse_args()
    {"search": search, "scan-one": scan_one, "run": run, "export": export}[args.command](args)


if __name__ == "__main__":
    main()
