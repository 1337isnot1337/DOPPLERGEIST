"""Optional checks against native, unmodified real archive traces."""
from contextlib import closing
from itertools import islice
import os
from pathlib import Path
import sqlite3

import pytest

from dopplergeist.data_access import DataUnavailable, FlightIndex, archive_frames, archive_staging


@pytest.fixture
def archive():
    path = os.environ.get("DOPPLERGEIST_REAL_ARCHIVE")
    if not path or not Path(path).is_file():
        pytest.skip("Set DOPPLERGEIST_REAL_ARCHIVE to a native historical archive part")
    return [path]


def _contents(index):
    with sqlite3.connect(index.path) as db:
        segments = db.execute("SELECT name,start,end,payload_hash,payload FROM segments ORDER BY name").fetchall()
        boxes = db.execute("SELECT name,west,east,south,north FROM segments JOIN spatial ON segments.id=spatial.id ORDER BY name").fetchall()
    return segments, boxes


def test_parallel_real_archive_index_matches_serial(archive, tmp_path):
    coverage = {"bounds": [-180, -90, 180, 90], "time_range_s": [0, 2000000000],
                "all_aircraft": False, "source_note": "small real trace subset"}
    with closing(archive_frames(archive)) as frames:
        serial = FlightIndex.build(tmp_path / "serial.sqlite", islice(frames, 12), sources=[], coverage=coverage)
    with closing(archive_staging(archive, {}, workers=2)) as batches:
        parallel = FlightIndex.build(tmp_path / "parallel.sqlite", islice(batches, 12), sources=[], coverage=coverage, prepared=True)
    assert serial.report == parallel.report
    assert _contents(serial) == _contents(parallel)


def test_parallel_rejects_oversized_real_archive_member(archive):
    with pytest.raises(DataUnavailable, match="Oversized"):
        list(archive_staging(archive, {}, workers=2, max_member_bytes=1))
