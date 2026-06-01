"""SQLite database model for Blue Mark Report data.

Provides a unified schema that accommodates both legacy (2022-2025)
post-pour QA tracking and v2026 pre-pour production checklist formats.
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "blue_mark.db"

CREATE_PIECES_TABLE = """
CREATE TABLE IF NOT EXISTS pieces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date     TEXT NOT NULL,
    pour_date       TEXT,
    job_number      INTEGER NOT NULL,
    piece_number    TEXT NOT NULL,
    piece_type      TEXT,
    bed_type        TEXT,
    blue_marked         INTEGER DEFAULT 0,
    patching_cleaning   INTEGER DEFAULT 0,
    weld_on_required    INTEGER DEFAULT 0,
    ncr_response        INTEGER DEFAULT 0,
    ncr_repair          INTEGER DEFAULT 0,
    architectural_finish INTEGER DEFAULT 0,
    production_pre_pour     INTEGER DEFAULT 0,
    qa_pre_pour             INTEGER DEFAULT 0,
    production_wythe_check  INTEGER DEFAULT 0,
    qa_wythe_check          INTEGER DEFAULT 0,
    production_top_check    INTEGER DEFAULT 0,
    comments        TEXT,
    source_file     TEXT,
    schema_version  TEXT NOT NULL DEFAULT 'legacy',
    UNIQUE(report_date, job_number, piece_number, source_file)
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pieces_report_date ON pieces(report_date);",
    "CREATE INDEX IF NOT EXISTS idx_pieces_job_number ON pieces(job_number);",
    "CREATE INDEX IF NOT EXISTS idx_pieces_piece_number ON pieces(piece_number);",
    "CREATE INDEX IF NOT EXISTS idx_pieces_piece_type ON pieces(piece_type);",
    "CREATE INDEX IF NOT EXISTS idx_pieces_bed_type ON pieces(bed_type);",
    "CREATE INDEX IF NOT EXISTS idx_pieces_schema ON pieces(schema_version);",
]


class BlueMarkDB:
    """SQLite connection manager for Blue Mark Report data."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> "BlueMarkDB":
        """Open a connection and ensure tables exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self.create_tables()
        logger.info("Connected to Blue Mark DB: %s", self.db_path)
        return self

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "BlueMarkDB":
        return self.connect()

    def __exit__(self, *args: Any) -> None:
        self.close()

    def create_tables(self) -> None:
        """Create the pieces table and indexes if they don't exist."""
        self.conn.execute(CREATE_PIECES_TABLE)
        for idx_sql in CREATE_INDEXES:
            self.conn.execute(idx_sql)
        self.conn.commit()

    def insert_piece(self, record: dict[str, Any]) -> int:
        """Insert a single piece record. Returns the row ID."""
        cols = [
            "report_date", "pour_date", "job_number", "piece_number",
            "piece_type", "bed_type", "blue_marked", "patching_cleaning",
            "weld_on_required", "ncr_response", "ncr_repair",
            "architectural_finish", "production_pre_pour", "qa_pre_pour",
            "production_wythe_check", "qa_wythe_check", "production_top_check",
            "comments", "source_file", "schema_version",
        ]
        values = [record.get(c) for c in cols]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO pieces ({col_names}) VALUES ({placeholders})",
            values,
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def bulk_insert(self, records: list[dict[str, Any]]) -> int:
        """Insert multiple piece records. Returns count of rows inserted."""
        if not records:
            return 0
        cols = [
            "report_date", "pour_date", "job_number", "piece_number",
            "piece_type", "bed_type", "blue_marked", "patching_cleaning",
            "weld_on_required", "ncr_response", "ncr_repair",
            "architectural_finish", "production_pre_pour", "qa_pre_pour",
            "production_wythe_check", "qa_wythe_check", "production_top_check",
            "comments", "source_file", "schema_version",
        ]
        rows = [[record.get(c) for c in cols] for record in records]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        before = self._count_pieces()
        self.conn.executemany(
            f"INSERT OR IGNORE INTO pieces ({col_names}) VALUES ({placeholders})",
            rows,
        )
        self.conn.commit()
        after = self._count_pieces()
        inserted = after - before
        logger.info("Bulk inserted %d records (%d skipped as duplicates)", inserted, len(records) - inserted)
        return inserted

    def _count_pieces(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM pieces").fetchone()
        return row[0]

    def get_pieces_by_date(self, report_date: date) -> list[dict[str, Any]]:
        """Get all pieces for a given report date."""
        rows = self.conn.execute(
            "SELECT * FROM pieces WHERE report_date = ? ORDER BY job_number, piece_number",
            (report_date.isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_pieces_by_job(self, job_number: int) -> list[dict[str, Any]]:
        """Get all pieces for a given job number."""
        rows = self.conn.execute(
            "SELECT * FROM pieces WHERE job_number = ? ORDER BY report_date, piece_number",
            (job_number,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_pieces(self, schema_version: Optional[str] = None) -> list[dict[str, Any]]:
        """Get pieces that haven't been fully blue-marked yet.

        For legacy: blue_marked = 0
        For v2026: production_top_check = 0 (last checkpoint)
        """
        if schema_version == "v2026":
            sql = "SELECT * FROM pieces WHERE schema_version = 'v2026' AND production_top_check = 0"
        elif schema_version == "legacy":
            sql = "SELECT * FROM pieces WHERE schema_version = 'legacy' AND blue_marked = 0"
        else:
            sql = """
                SELECT * FROM pieces WHERE
                (schema_version = 'legacy' AND blue_marked = 0)
                OR (schema_version = 'v2026' AND production_top_check = 0)
            """
        rows = self.conn.execute(sql + " ORDER BY report_date DESC, job_number").fetchall()
        return [dict(r) for r in rows]

    def get_piece_history(self, piece_number: str) -> list[dict[str, Any]]:
        """Get the full lifecycle of a single piece across all reports."""
        rows = self.conn.execute(
            "SELECT * FROM pieces WHERE piece_number = ? ORDER BY report_date",
            (piece_number,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_summary_stats(self) -> dict[str, Any]:
        """Return high-level statistics about the database."""
        stats: dict[str, Any] = {}
        stats["total_records"] = self._count_pieces()
        row = self.conn.execute("SELECT COUNT(DISTINCT job_number) FROM pieces").fetchone()
        stats["unique_jobs"] = row[0]
        row = self.conn.execute("SELECT COUNT(DISTINCT piece_number) FROM pieces").fetchone()
        stats["unique_pieces"] = row[0]
        row = self.conn.execute("SELECT MIN(report_date), MAX(report_date) FROM pieces").fetchone()
        stats["date_range"] = (row[0], row[1])
        row = self.conn.execute(
            "SELECT schema_version, COUNT(*) FROM pieces GROUP BY schema_version"
        ).fetchall()
        stats["by_schema"] = {r[0]: r[1] for r in row}
        return stats
