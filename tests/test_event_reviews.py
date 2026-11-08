"""Focused checks for local review-label persistence.

These use no audio or flight data; they only exercise the annotation contract.
"""
import json

import pytest

from dopplergeist.event_reviews import (
    ReviewError, apply_review, false_positive_ids, read_reviews, write_reviews,
)


def test_review_labels_roundtrip_and_clear(tmp_path):
    applied = apply_review(tmp_path, {"event-1", "event-2"}, "false_positive",
                           ["event-1"], "steady engine tone")
    assert applied["labels"]["event-1"]["label"] == "false_positive"
    assert applied["labels"]["event-1"]["note"] == "steady engine tone"
    assert false_positive_ids(tmp_path) == ["event-1"]
    assert read_reviews(tmp_path) == applied

    confirmed = apply_review(tmp_path, {"event-1", "event-2"}, "confirmed", ["event-2"])
    assert confirmed["labels"]["event-2"]["label"] == "confirmed"
    assert confirmed["labels"]["event-2"].get("note") is None
    assert false_positive_ids(tmp_path) == ["event-1"]

    cleared = apply_review(tmp_path, {"event-1", "event-2"}, "unreviewed", ["event-1"])
    assert "event-1" not in cleared["labels"]
    assert false_positive_ids(tmp_path) == []


@pytest.mark.parametrize("label", ["maybe", "", None])
def test_unknown_review_label_is_rejected(tmp_path, label):
    with pytest.raises(ReviewError):
        apply_review(tmp_path, {"event-1"}, label, ["event-1"])


def test_unknown_event_is_rejected(tmp_path):
    with pytest.raises(ReviewError, match="Unknown event"):
        apply_review(tmp_path, {"event-1"}, "false_positive", ["event-9"])


def test_review_note_is_bounded(tmp_path):
    with pytest.raises(ReviewError, match="1000"):
        apply_review(tmp_path, {"event-1"}, "false_positive", ["event-1"], "x" * 1001)


def test_corrupt_or_unknown_review_file_fails_closed(tmp_path):
    (tmp_path / "event-reviews.json").write_text("{")
    with pytest.raises(ReviewError, match="unreadable"):
        read_reviews(tmp_path)
    write_reviews(tmp_path, {})
    value = json.loads((tmp_path / "event-reviews.json").read_text())
    value["labels"]["event-1"] = {"label": "unsupported"}
    (tmp_path / "event-reviews.json").write_text(json.dumps(value))
    with pytest.raises(ReviewError, match="Unknown review label"):
        read_reviews(tmp_path)
