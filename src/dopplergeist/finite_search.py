"""Exact finite-seed identity and disk-backed scored-retention accounting."""
import hashlib
import json
import math
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .data_access import DataUnavailable, content_hash


def mode_seed(row):
    def number(value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Finite mode seeds require finite coordinates and times")
        return 0.0 if value == 0 else value
    return {"event_indices": [int(i) for i in row.get("event_indices", range(len(row["flight_ids"])))],
            "flight_ids": list(row["flight_ids"]),
            "pass_emission_times_s": [number(t) for t in row.get("pass_emission_times_s", [])],
            "position": [number(row.get(k, 0)) for k in ("x", "y", "lat", "lon", "elev_m")],
            "recording_start_time_s": number(row["recording_start_time_s"])}


def identify_mode(row):
    seed = row.get("mode_seed") or mode_seed(row)
    identifier = "mode-" + content_hash(seed)
    if row.get("mode_id", identifier) != identifier:
        raise DataUnavailable("Mode ID does not match its original seed identity")
    row["mode_seed"], row["mode_id"] = seed, identifier
    return identifier


def classified_assessment(row):
    assessment = row.get("scoring_assessment")
    valid = (isinstance(assessment, dict) and assessment.get("complete") is True
            and all(type(assessment.get(k)) is int and assessment[k] >= 0
                    for k in ("evaluated_trials", "rejected_trials", "unknown_trials"))
            and assessment["unknown_trials"] == 0)
    if not valid:
        return False
    # No trials is unknown work. A finite best needs an evaluated trial; a
    # wholly rejected envelope cannot have discarded an evaluated finite best.
    score = row.get("score", math.nan)
    return (assessment["evaluated_trials"] > 0 if math.isfinite(score) else
            score == -math.inf and assessment["evaluated_trials"] == 0 and assessment["rejected_trials"] > 0)


class RetentionLedger:
    """One immutable-input run; bounded per-stage writes and streaming audits.

    Store every finite scored mode before top-k pruning. Stage rows are replaced
    on deterministic replay, so resumed work cannot inflate counts. Exact IDs
    appearing at several stages are aggregated by their maximum scored value.
    """
    def __init__(self, path, run_hash, score_kind):
        self.path, self.run_hash, self.score_kind = Path(path), run_hash, score_kind
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.connect() as db:
                db.executescript("""
                    PRAGMA cache_size=-8192; PRAGMA temp_store=FILE;
                    CREATE TABLE IF NOT EXISTS run(identity TEXT, score_kind TEXT);
                    CREATE TABLE IF NOT EXISTS stages(name TEXT PRIMARY KEY, checksum TEXT,
                        occurrences INTEGER, duplicates INTEGER, kept TEXT);
                    CREATE TABLE IF NOT EXISTS records(stage TEXT, mode_id TEXT, score REAL,
                        groups_count INTEGER, kind TEXT, seed TEXT, PRIMARY KEY(stage,mode_id));
                    CREATE INDEX IF NOT EXISTS mode_index ON records(mode_id);
                """)
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise DataUnavailable("Corrupt finite retention ledger")
                identity = db.execute("SELECT identity,score_kind FROM run").fetchone()
                if identity is None:
                    db.execute("INSERT INTO run VALUES(?,?)", (run_hash, score_kind))
                elif identity != (run_hash, score_kind):
                    raise DataUnavailable("Finite ledger input/score identity mismatch")
        except sqlite3.DatabaseError as error:
            raise DataUnavailable("Cannot read finite retention ledger") from error

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA cache_size=-8192")
        db.execute("PRAGMA temp_store=FILE")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _checksum(records, kept, occurrences, duplicates):
        digest = hashlib.sha256()
        for record in records:
            digest.update(json.dumps(record, separators=(",", ":"), allow_nan=False).encode())
            digest.update(b"\n")
        digest.update(json.dumps(sorted(kept), separators=(",", ":")).encode())
        digest.update(json.dumps([occurrences, duplicates]).encode())
        return digest.hexdigest()

    def record(self, stage, rows, kept, occurrences):
        records = []
        for row in rows:
            identifier = identify_mode(row)
            kind = row.get("score_kind", self.score_kind)
            if kind != self.score_kind:
                raise DataUnavailable("Finite retention mixed incompatible score units")
            records.append((identifier, float(row["score"]), len(row["mode_seed"]["event_indices"]), kind,
                            json.dumps(row["mode_seed"], sort_keys=True, separators=(",", ":"))))
        records.sort()
        kept_ids = [identify_mode(row) for row in kept]
        checksum = self._checksum(records, kept_ids, occurrences, occurrences-len(records))
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE stage=?", (stage,))
            db.executemany("INSERT INTO records VALUES(?,?,?,?,?,?)", [(stage, *r) for r in records])
            db.execute("INSERT OR REPLACE INTO stages VALUES(?,?,?,?,?)",
                       (stage, checksum, occurrences, occurrences-len(records), json.dumps(sorted(kept_ids))))
        return checksum

    def checksum(self, stage):
        with self.connect() as db:
            row = db.execute("SELECT checksum FROM stages WHERE name=?", (stage,)).fetchone()
            return row[0] if row else None

    def stage_valid(self, stage, expected):
        try:
            with self.connect() as db:
                record = db.execute("SELECT checksum,kept,occurrences,duplicates FROM stages WHERE name=?", (stage,)).fetchone()
                if record is None or record[0] != expected:
                    return False
                rows = db.execute("SELECT mode_id,score,groups_count,kind,seed FROM records WHERE stage=? ORDER BY mode_id", (stage,))
                return self._checksum(rows, json.loads(record[1]), record[2], record[3]) == expected
        except (sqlite3.DatabaseError, ValueError, TypeError) as error:
            raise DataUnavailable("Corrupt finite retention stage") from error

    def evidence(self, retained, *, complete, spacing_m, refine_spacing_m, max_event_groups, expected_stages=None):
        ids = [identify_mode(row) for row in retained]
        accounted = True
        totals = {}
        with self.connect() as db:
            stages = db.execute("SELECT name,checksum,occurrences,duplicates,kept FROM stages ORDER BY name")
            for name, checksum, occurrences, duplicates, kept in stages:
                if not self.stage_valid(name, checksum):
                    accounted = False
                phase = name.split(":", 1)[0]
                total = totals.setdefault(phase, {"stages": 0, "input_occurrences": 0, "exact_duplicates": 0,
                                                  "retained": 0, "discarded": 0})
                retained_count = len(json.loads(kept))
                for key, value in (("stages", 1), ("input_occurrences", occurrences), ("exact_duplicates", duplicates),
                                   ("retained", retained_count), ("discarded", occurrences-duplicates-retained_count)):
                    total[key] += value
            db.execute("CREATE TEMP TABLE retained_ids(id TEXT PRIMARY KEY)")
            db.executemany("INSERT INTO retained_ids VALUES(?)", [(i,) for i in ids])
            distinct = "SELECT mode_id,MAX(score) AS score FROM records GROUP BY mode_id"
            discarded, bound = db.execute(f"SELECT count(*),max(score) FROM ({distinct}) WHERE mode_id NOT IN (SELECT id FROM retained_ids)").fetchone()
            evaluated = db.execute(f"SELECT count(*) FROM ({distinct})").fetchone()[0]
            original = {mode_id: score for mode_id, score in db.execute(
                f"SELECT mode_id,score FROM ({distinct}) WHERE mode_id IN (SELECT id FROM retained_ids)")}
        if set(original) != set(ids):
            accounted = False
        if expected_stages is not None:
            actual = {phase: totals.get(phase, {}).get("stages", 0) for phase in expected_stages}
            if actual != expected_stages or set(totals)-set(expected_stages):
                accounted = False
        if not accounted:
            discarded, bound, evaluated, original = None, None, None, {}
        return {"schema_version": 1, "scope": "evaluated_finite_grid", "complete": bool(complete and accounted),
                "score_kind": self.score_kind, "spacing_m": float(spacing_m), "refine_spacing_m": float(refine_spacing_m),
                "max_event_groups": max_event_groups,
                "retained_modes": [{"mode_id": row["mode_id"], "score": original.get(row["mode_id"], row["score"]),
                                    "event_groups": len(row["mode_seed"]["event_indices"])} for row in retained],
                "discarded_count": discarded, "best_discarded_score": bound, "pruning_accounted_for": accounted,
                "evaluated_modes": evaluated,
                "stages": totals,
                "limitations": ["Evaluated grids and recorded refinements only; continuous-space uniqueness is not established.",
                                "Unvisited positions and unperformed refinements have no inferred score bound.",
                                "Proposal envelopes, CPA tolerances, grouping, clock bounds and physical model are declared assumptions."]}
