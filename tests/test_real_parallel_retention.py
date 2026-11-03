"""Verify worker-ledger imports using an actual running search's evidence."""
import os
from pathlib import Path
import sqlite3

import pytest

from dopplergeist.finite_search import RetentionLedger
from dopplergeist.parallel_retention import import_retention_stage


def test_real_retention_stages_survive_worker_import(tmp_path):
    source = os.environ.get("DOPPLERGEIST_REAL_RETENTION_LEDGER")
    if not source:
        pytest.skip("set DOPPLERGEIST_REAL_RETENTION_LEDGER to a real search ledger")
    source = Path(source)
    snapshot = tmp_path / "worker.sqlite"
    with sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True) as current:
        with sqlite3.connect(snapshot) as worker:
            current.backup(worker)
    with sqlite3.connect(snapshot) as worker:
        run_hash, score_kind = worker.execute("SELECT identity, score_kind FROM run").fetchone()
        populated = worker.execute(
            "SELECT s.name, s.checksum FROM stages s JOIN bounds b ON b.stage=s.name "
            "WHERE s.name LIKE 'coarse:%' GROUP BY s.name ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        empty = worker.execute(
            "SELECT name, checksum FROM stages WHERE name LIKE 'coarse:%' AND occurrences=0 LIMIT 1"
        ).fetchone()
    assert populated is not None and empty is not None
    target = RetentionLedger(tmp_path / "parent.sqlite", run_hash, score_kind)
    for stage, checksum in (populated, empty, populated):
        import_retention_stage(target, snapshot, stage, checksum)
        assert target.stage_valid(stage, checksum)
    with sqlite3.connect(snapshot) as worker, sqlite3.connect(target.path) as parent:
        for stage, _ in (populated, empty):
            for table, column in (("stages", "name"), ("records", "stage"), ("bounds", "stage")):
                expected = worker.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY 1,2", (stage,)).fetchall()
                actual = parent.execute(f"SELECT * FROM {table} WHERE {column}=? ORDER BY 1,2", (stage,)).fetchall()
                assert actual == expected
