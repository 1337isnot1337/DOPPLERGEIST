"""Reconcile existing scanner results by YouTube ID without discarding attempts."""

import argparse, collections, csv, hashlib, json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--state-root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
base = args.state_root


def sha(path):
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


names = [
    "dopplergeist-audio-corpus-20261103",
    "dopplergeist-youtube-retry-20261103",
    "dopplergeist-audio-corpus-retry-20261103",
    "dopplergeist-youtube-unified-retry-20261103",
    "dopplergeist-w4-w5-retry-20261103",
]
sources = {}
attempts = collections.defaultdict(list)
for name in names:
    root = base / name
    for line in (root / "sources.jsonl").read_text().splitlines():
        x = json.loads(line)
        if x.get("source") == "youtube":
            sources.setdefault(x["id"].removeprefix("yt-"), x)
    for path in sorted((root / "scans").glob("yt-*.json")):
        x = json.loads(path.read_text())
        id = path.stem.removeprefix("yt-")
        attempts[id].append(
            {
                "root": name,
                "status": x.get("status", "unknown"),
                "scanner_result": x.get("scanner_result", ""),
                "proposal_count": x.get("proposal_count", ""),
                "duration_s": x.get("duration_s", ""),
                "sha256": sha(root / "audio" / ("yt-" + id + ".mp3")),
            }
        )
w5 = base / "dopplergeist-w5-youtube-survey-20261103"
for line in (w5 / "known-results.jsonl").read_text().splitlines():
    x = json.loads(line)
    id = x["id"]
    sources.setdefault(
        id,
        {
            "id": "yt-" + id,
            "url": x["url"],
            "title": x["title"],
            "category": "site_named_aircraft",
        },
    )
    if x.get("scanner") == "completed":
        count = x.get("proposal_groups", 0)
        attempts[id].append(
            {
                "root": w5.name,
                "status": "scanned",
                "scanner_result": "proposals" if count else "no_proposals",
                "proposal_count": count,
                "duration_s": x.get("decoded_duration_s", ""),
                "sha256": sha(w5 / "known" / id / "input.mp3"),
            }
        )
    else:
        attempts[id].append(
            {
                "root": w5.name,
                "status": "download_failed",
                "scanner_result": "",
                "proposal_count": "",
            }
        )
reviews = collections.defaultdict(list)
for root in (
    base / "dopplergeist-youtube-retry-20261103/reviews",
    base / "dopplergeist-w4-w5-retry-20261103/reviews",
    base / "dopplergeist-youtube-unified-retry-20261103/reviews",
):
    for path in sorted(root.glob("*.json")):
        for x in json.loads(path.read_text()).get("cases", []):
            reviews[x["id"].removeprefix("yt-")].append(
                x.get("visual_assessment", x.get("assessment", ""))
            )
fields = [
    "id",
    "url",
    "title",
    "category",
    "overall_status",
    "scanner_result",
    "proposal_counts",
    "durations_s",
    "audio_sha256",
    "attempt_count",
    "attempt_roots",
    "attempt_statuses",
    "visual_reviews",
]
rows = []
for id, source in sorted(sources.items()):
    records = attempts.get(id, [])
    successes = [x for x in records if x["status"] == "scanned"]
    outcomes = {x["scanner_result"] for x in successes}
    result = (
        ("inconsistent" if len(outcomes) > 1 else next(iter(outcomes)))
        if outcomes
        else ""
    )
    rows.append(
        {
            "id": id,
            "url": source.get("url", ""),
            "title": source.get("title", ""),
            "category": source.get("category", ""),
            "overall_status": (
                "scanned"
                if successes
                else ("attempted_no_success" if records else "not_attempted")
            ),
            "scanner_result": result,
            "proposal_counts": "|".join(str(x["proposal_count"]) for x in successes),
            "durations_s": "|".join(str(x.get("duration_s", "")) for x in successes),
            "audio_sha256": "|".join(x.get("sha256", "") for x in successes),
            "attempt_count": len(records),
            "attempt_roots": "|".join(x["root"] for x in records),
            "attempt_statuses": "|".join(x["status"] for x in records),
            "visual_reviews": "|".join(reviews.get(id, [])),
        }
    )
tmp = args.output.with_suffix(args.output.suffix + ".tmp")
with tmp.open("w", newline="") as stream:
    w = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
tmp.replace(args.output)
counts = collections.Counter((r["overall_status"], r["scanner_result"]) for r in rows)
print("unique sources", len(rows), "outcomes", dict(counts))
for category in sorted({r["category"] for r in rows}):
    a = [
        r
        for r in rows
        if r["category"] == category and r["overall_status"] == "scanned"
    ]
    print(
        category,
        len(a),
        "proposals",
        sum(r["scanner_result"] == "proposals" for r in a),
    )
