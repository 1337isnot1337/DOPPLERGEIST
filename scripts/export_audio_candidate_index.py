"""Export reviewed real-audio candidates with site coordinates kept separate."""
import argparse
import csv
import html
import json
import re
from pathlib import Path


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def coordinates(site, record_id, truth_root):
    files = sorted(truth_root.glob(f"*/truth/{site}.json"))
    for path in files:
        record = json.loads(path.read_text())
        if str(record.get("id")) != str(record_id):
            continue
        description = html.unescape(re.sub(
            r"<[^>]+>", " ", record["metadata"]["description"]
        ))
        latitude = re.search(r"Latitude\s*:\s*(-?\d+(?:\.\d+)?)", description, re.I)
        longitude = re.search(r"Longitude\s*:\s*(-?\d+(?:\.\d+)?)", description, re.I)
        if latitude and longitude:
            return latitude.group(1), longitude.group(1)
    raise ValueError(f"No matching publisher coordinate metadata for ESID {site}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth-root", type=Path, required=True,
                        help="Local Eclipse collection root containing batch*/truth/*.json")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    args = parser.parse_args()

    candidate_fields = [
        "candidate_id", "source_type", "source_parent_id", "source_url", "title",
        "search_category", "clip_duration_s", "scanner_result", "proposal_count",
        "visual_review", "recording_location_class", "coarse_location_hint",
        "reference_coordinate_key", "recording_clock_status", "aircraft_identity",
        "location_evaluation_eligible",
    ]
    truth_fields = [
        "candidate_id", "source_parent_id", "zenodo_record_id", "record_url",
        "publisher_metadata_url", "site_latitude", "site_longitude",
        "coordinate_basis", "microphone_coordinate_accuracy", "clock_setting",
        "filename_start_utc_claim",
    ]

    site_candidates = []
    for name in ("eclipse-field-screen-20261103.json",
                 "eclipse-field-screen-batch2-20261103.json"):
        report = json.loads((Path("benchmarks") / name).read_text())
        for result in report["results"]:
            note = result.get("visual_review") or ""
            if (result.get("status") != "scanned"
                    or int(result.get("proposal_groups") or 0) == 0
                    or "not visually convincing" in note):
                continue
            site_candidates.append((name, result))

    videos = {
        row["id"]: row for row in read_csv(Path("benchmarks/youtube-expanded-scan-20261103.csv"))
    }
    unknown_candidates = [
        row for row in videos.values()
        if "candidate_doppler_like" in row["visual_reviews"].split("|")
    ]
    if len(site_candidates) != 20 or len(unknown_candidates) != 5:
        raise ValueError(f"Expected 20 site-pattern and 5 unresolved-coordinate video candidates; "
                         f"found {len(site_candidates)} and {len(unknown_candidates)}")

    index_rows = []
    truth_rows = []
    for batch, result in site_candidates:
        site = result["site"]
        record_id = result["record_url"].rstrip("/").split("/")[-1]
        candidate_id = f"esid-{site}"
        pattern = "descending_band_visible"
        if any(word in (result.get("visual_review") or "").lower()
               for word in ("weak", "fragmented", "interruption")):
            pattern = "descending_band_visible_weak_or_interrupted"
        index_rows.append({
            "candidate_id": candidate_id,
            "source_type": "Eclipse Soundscapes field recording",
            "source_parent_id": site,
            "source_url": result["record_url"],
            "title": f"2024-04-08 Eclipse Soundscapes ESID {site}",
            "search_category": "publisher field site",
            "clip_duration_s": result.get("clip_duration_s", ""),
            "scanner_result": f"{result.get('proposal_groups', 0)} moving-tone proposal groups",
            "proposal_count": result.get("proposal_groups", 0),
            "visual_review": f"{pattern}: {result.get('visual_review', '')}",
            "recording_location_class": "publisher_site_coordinate; microphone accuracy unknown",
            "coarse_location_hint": f"Eclipse Soundscapes site {site}",
            "reference_coordinate_key": candidate_id,
            "recording_clock_status": (
                "filename timestamp unverified; " +
                str(result.get("publisher_clock_setting", "publisher clock setting unreported"))
            ),
            "aircraft_identity": "unconfirmed",
            "location_evaluation_eligible": "no",
        })
        latitude, longitude = coordinates(site, record_id, args.truth_root)
        truth_rows.append({
            "candidate_id": candidate_id,
            "source_parent_id": site,
            "zenodo_record_id": record_id,
            "record_url": result["record_url"],
            "publisher_metadata_url": result.get("publisher_site_metadata_url", ""),
            "site_latitude": latitude,
            "site_longitude": longitude,
            "coordinate_basis": "Publisher-reported deployment site coordinates",
            "microphone_coordinate_accuracy": "Unknown; not an independently surveyed microphone position",
            "clock_setting": result.get("publisher_clock_setting", ""),
            "filename_start_utc_claim": result.get("filename_timestamp_utc_unverified", ""),
        })

    for row in sorted(unknown_candidates, key=lambda item: item["id"]):
        durations = [float(v) for v in row["durations_s"].split("|") if v]
        index_rows.append({
            "candidate_id": f"yt-{row['id']}",
            "source_type": "YouTube audio excerpt",
            "source_parent_id": row["id"],
            "source_url": row["url"],
            "title": row["title"],
            "search_category": row["category"],
            "clip_duration_s": max(durations, default=""),
            "scanner_result": row["scanner_result"],
            "proposal_count": row["proposal_counts"],
            "visual_review": row["visual_reviews"],
            "recording_location_class": "exact receiver coordinates unresolved",
            "coarse_location_hint": "Title may name a broad area or site; recorder position is not independently established",
            "reference_coordinate_key": "",
            "recording_clock_status": "recording UTC not established",
            "aircraft_identity": "unconfirmed",
            "location_evaluation_eligible": "no",
        })

    write_csv(args.index, candidate_fields, index_rows)
    write_csv(args.truth, truth_fields, truth_rows)
    print(f"candidate_index={len(index_rows)} site_coordinates={len(truth_rows)} "
          f"unresolved_receiver_coordinate_videos={len(unknown_candidates)}")


if __name__ == "__main__":
    main()
