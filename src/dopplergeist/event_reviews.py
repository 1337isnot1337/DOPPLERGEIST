"""Persistent local review labels for discovered acoustic proposals.

Labels are annotations. They do not alter an automatic job's scores, candidates,
status or location. A separate user-assisted analysis can exclude the event IDs
explicitly marked ``false_positive``.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading

REVIEW_FILE = "event-reviews.json"
REVIEW_LABELS = {"confirmed", "false_positive"}
_REVIEW_LOCK = threading.RLock()


class ReviewError(ValueError):
    """Invalid or unreadable review data."""


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def _validate_entry(event_id, entry):
    if not isinstance(event_id, str) or not event_id.strip():
        raise ReviewError("Review labels must use nonempty event IDs")
    if not isinstance(entry, dict) or entry.keys() - {"label", "note", "updated_utc"}:
        raise ReviewError(f"Invalid review entry for {event_id}")
    if entry.get("label") not in REVIEW_LABELS:
        raise ReviewError(f"Unknown review label for {event_id}")
    for name in ("note", "updated_utc"):
        if name in entry and not isinstance(entry[name], str):
            raise ReviewError(f"{name} must be text for {event_id}")
    if len(entry.get("note", "")) > 1000:
        raise ReviewError(f"Review note is too long for {event_id}")


def read_reviews(job_dir):
    path = Path(job_dir) / REVIEW_FILE
    if not path.is_file():
        return {"schema_version": 1, "labels": {}}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Saved review labels are unreadable: {exc}") from exc
    if (not isinstance(value, dict) or value.keys() - {"schema_version", "labels", "updated_utc"}
            or value.get("schema_version") != 1 or not isinstance(value.get("labels"), dict)):
        raise ReviewError("Saved review labels have an unsupported shape")
    if "updated_utc" in value and not isinstance(value["updated_utc"], str):
        raise ReviewError("updated_utc must be text")
    for event_id, entry in value["labels"].items():
        _validate_entry(event_id, entry)
    return value


def write_reviews(job_dir, labels):
    with _REVIEW_LOCK:
        value = {"schema_version": 1, "labels": {key: labels[key] for key in sorted(labels)}}
        if value["labels"]:
            value["updated_utc"] = _now()
        _atomic_write(Path(job_dir) / REVIEW_FILE, value)
        return value


def apply_review(job_dir, known_event_ids, label, event_ids, note=None):
    if label not in REVIEW_LABELS and label != "unreviewed":
        raise ReviewError("Review label must be confirmed, false_positive or unreviewed")
    if not isinstance(event_ids, list) or not event_ids:
        raise ReviewError("Choose at least one event to review")
    if len(set(event_ids)) != len(event_ids):
        raise ReviewError("Review event IDs must not repeat")
    known = set(known_event_ids)
    unknown = sorted(set(event_ids) - known)
    if unknown:
        raise ReviewError(f"Unknown event IDs: {', '.join(unknown)}")
    if note is not None and not isinstance(note, str):
        raise ReviewError("Review note must be text")
    note = (note or "").strip()
    if len(note) > 1000:
        raise ReviewError("Review note must be at most 1000 characters")
    with _REVIEW_LOCK:
        reviews = read_reviews(job_dir)
        labels = dict(reviews["labels"])
        updated = _now()
        for event_id in event_ids:
            if label == "unreviewed":
                labels.pop(event_id, None)
            else:
                entry = {"label": label, "updated_utc": updated}
                if note:
                    entry["note"] = note
                labels[event_id] = entry
        return write_reviews(job_dir, labels)


def false_positive_ids(job_dir):
    reviews = read_reviews(job_dir)
    return sorted(event_id for event_id, entry in reviews["labels"].items()
                  if entry["label"] == "false_positive")
