"""Move a completed worker stage into the search's retention ledger."""
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from .data_access import DataUnavailable
from .finite_search import RetentionLedger


@dataclass(frozen=True)
class EmptyRetentionStage:
    """An empty worker result that needs no intermediate SQLite database.

    The parent still records the stage in its durable ledger before writing a
    checkpoint. Identity fields prevent a descriptor from another run or stage
    from being accepted merely because all empty stages have the same checksum.
    """
    run_hash: str
    score_kind: str
    stage: str
    checksum: str

    @classmethod
    def for_stage(cls, run_hash, score_kind, stage):
        return cls(run_hash, score_kind, stage, RetentionLedger._checksum([], [], 0, 0))


def import_retention_stage(ledger, worker_path, stage, expected_checksum):
    """Atomically import one verified worker stage without changing its evidence.

    Scored workers use private ledgers; empty workers return an identity-bearing
    descriptor. Only the parent writes the destination ledger.
    The stage checksum, run identity, scores, discarded bounds and kept modes
    must all match before the parent can checkpoint that stage.
    """
    if isinstance(worker_path, EmptyRetentionStage):
        expected = EmptyRetentionStage.for_stage(ledger.run_hash, ledger.score_kind, stage)
        if worker_path != expected or expected_checksum != expected.checksum:
            raise DataUnavailable("Empty worker retention stage identity/checksum mismatch")
        try:
            checksum = ledger.record(stage, [], [], 0)
            if checksum != expected_checksum or not ledger.stage_valid(stage, expected_checksum):
                raise DataUnavailable("Imported empty retention stage failed verification")
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as error:
            raise DataUnavailable("Cannot import empty worker retention stage") from error
        return
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
            ).fetchall()
            bounds = db.execute(
                "SELECT bound_id, upper_score, groups_count, detail FROM worker.bounds WHERE stage=? ORDER BY bound_id",
                (stage,),
            ).fetchall()
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
