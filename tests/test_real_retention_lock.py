"""Exercise a real saved retention ledger under a temporary reader lock."""
import os
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from dopplergeist.finite_search import RetentionLedger


def test_real_ledger_writer_waits_for_transient_reader(tmp_path):
    source = os.environ.get("DOPPLERGEIST_REAL_RETENTION_LEDGER")
    if not source:
        pytest.skip("set a completed real retention ledger path")
    path = tmp_path / "retention.sqlite"
    with sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(path) as dst:
        src.backup(dst)
    with sqlite3.connect(path) as db:
        identity, kind = db.execute("SELECT identity,score_kind FROM run").fetchone()
        stage, checksum = db.execute("SELECT name,checksum FROM stages LIMIT 1").fetchone()
    ledger = RetentionLedger(path, identity, kind)
    ready, release = threading.Event(), threading.Event()

    def hold_reader():
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            db.execute("SELECT checksum FROM stages WHERE name=?", (stage,)).fetchone()
            ready.set()
            release.wait(20)

    reader = threading.Thread(target=hold_reader)
    reader.start()
    assert ready.wait(5)
    timer = threading.Timer(7, release.set)
    started = time.monotonic()
    timer.start()
    try:
        with ledger.connect() as db:
            db.execute("UPDATE stages SET checksum=checksum WHERE name=?", (stage,))
    finally:
        release.set()
        reader.join()
        timer.cancel()
    assert time.monotonic() - started >= 6
    assert ledger.stage_valid(stage, checksum)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
