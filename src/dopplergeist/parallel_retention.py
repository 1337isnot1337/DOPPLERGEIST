"""Move a completed worker stage into the search's retention ledger."""
import json
from pathlib import Path
import sqlite3

from .data_access import DataUnavailable


def import_retention_stage(ledger, worker_path, stage, expected_checksum):
    """Atomically import one verified worker stage without changing its evidence.

    Workers use private ledgers; only the parent writes the destination ledger.
    The stage checksum, run identity, scores, discarded bounds and kept modes
    must all match before the parent can checkpoint that stage.
    """
    worker_path = Path(worker_path)
    if not worker_path.is_file() or worker_path.resolve() == ledger.path.resolve():
        raise DataUnavailable("Missing or invalid worker retention ledger")
    try:
        db = sqlite3.connect(ledger.path, timeout=30)
        try:
            db.execute("ATTACH DATABASE ? AS worker", (str(worker_path),))
            db.execute("BEGIN")
            identity = db.execute("SELECT identity, score_kind FROM worker.run").fetchall()
            if identity != [(ledger.run_hash, ledger.score_kind)]:
                raise DataUnavailable("Worker retention ledger identity mismatch")
            stage_row = db.execute(
                "SELECT checksum, kept, occurrences, duplicates FROM worker.stages WHERE name=?", (stage,)
            ).fetchone()
            if stage_row is None or stage_row[0] != expected_checksum:
                raise DataUnavailable("Worker retention stage is missing or has the wrong checksum")
            records = db.execute(
                "SELECT mode_id, score, groups_count, kind, seed FROM worker.records WHERE stage=? ORDER BY mode_id",
                (stage,),
            )
            bounds = db.execute(
                "SELECT bound_id, upper_score, groups_count, detail FROM worker.bounds WHERE stage=? ORDER BY bound_id",
                (stage,),
            )
            if ledger._checksum(records, json.loads(stage_row[1]), stage_row[2], stage_row[3], bounds) != expected_checksum:
                raise DataUnavailable("Worker retention stage failed its checksum")
            for table in ("records", "bounds"):
                db.execute(f"DELETE FROM {table} WHERE stage=?", (stage,))
                db.execute(f"INSERT INTO {table} SELECT * FROM worker.{table} WHERE stage=?", (stage,))
            db.execute("DELETE FROM stages WHERE name=?", (stage,))
            db.execute("INSERT INTO stages SELECT * FROM worker.stages WHERE name=?", (stage,))
            db.commit()
        finally:
            db.close()
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as error:
        raise DataUnavailable("Cannot import worker retention stage") from error
    if not ledger.stage_valid(stage, expected_checksum):
        raise DataUnavailable("Imported retention stage failed verification")
