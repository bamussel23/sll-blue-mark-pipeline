"""SQLite database model for the Sample Library catalog.

Provides storage and query methods for audio sample metadata including
BPM, musical key, duration, and spectral features. Mirrors the BlueMarkDB
pattern with WAL mode, context manager, and fluent .connect() interface.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "samples.db"

CREATE_SAMPLES_TABLE = """
CREATE TABLE IF NOT EXISTS samples (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path           TEXT NOT NULL UNIQUE,
    filename            TEXT NOT NULL,
    format              TEXT NOT NULL,
    duration_seconds    REAL,
    bpm                 REAL,
    musical_key         TEXT,
    is_loop             INTEGER DEFAULT 0,
    sample_type         TEXT DEFAULT 'one-shot',
    category            TEXT DEFAULT 'other',
    spectral_centroid   REAL,
    rms_energy          REAL,
    file_size_bytes     INTEGER,
    channels            INTEGER,
    sample_rate         INTEGER,
    date_scanned        TEXT NOT NULL,
    file_modified_at    TEXT
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_samples_filename ON samples(filename);",
    "CREATE INDEX IF NOT EXISTS idx_samples_format ON samples(format);",
    "CREATE INDEX IF NOT EXISTS idx_samples_category ON samples(category);",
    "CREATE INDEX IF NOT EXISTS idx_samples_sample_type ON samples(sample_type);",
    "CREATE INDEX IF NOT EXISTS idx_samples_bpm ON samples(bpm);",
    "CREATE INDEX IF NOT EXISTS idx_samples_musical_key ON samples(musical_key);",
    "CREATE INDEX IF NOT EXISTS idx_samples_duration ON samples(duration_seconds);",
]

SAMPLE_COLUMNS = [
    "file_path", "filename", "format", "duration_seconds", "bpm",
    "musical_key", "is_loop", "sample_type", "category",
    "spectral_centroid", "rms_energy", "file_size_bytes",
    "channels", "sample_rate", "date_scanned", "file_modified_at",
]


class SampleDB:
    """SQLite connection manager for the audio sample catalog."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> "SampleDB":
        """Open a connection and ensure tables exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self.create_tables()
        logger.info("Connected to Sample DB: %s", self.db_path)
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

    def __enter__(self) -> "SampleDB":
        return self.connect()

    def __exit__(self, *args: Any) -> None:
        self.close()

    def create_tables(self) -> None:
        """Create the samples table and indexes if they don't exist."""
        self.conn.execute(CREATE_SAMPLES_TABLE)
        for idx_sql in CREATE_INDEXES:
            self.conn.execute(idx_sql)
        self.conn.commit()

    def insert_sample(self, record: dict[str, Any]) -> int:
        """Insert a single sample record. Returns the row ID.

        Uses INSERT OR IGNORE for dedup by file_path.
        """
        values = [record.get(c) for c in SAMPLE_COLUMNS]
        placeholders = ", ".join(["?"] * len(SAMPLE_COLUMNS))
        col_names = ", ".join(SAMPLE_COLUMNS)
        cursor = self.conn.execute(
            f"INSERT OR IGNORE INTO samples ({col_names}) VALUES ({placeholders})",
            values,
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def bulk_insert(self, records: list[dict[str, Any]]) -> int:
        """Insert multiple sample records. Returns count of rows inserted."""
        if not records:
            return 0
        rows = [[record.get(c) for c in SAMPLE_COLUMNS] for record in records]
        placeholders = ", ".join(["?"] * len(SAMPLE_COLUMNS))
        col_names = ", ".join(SAMPLE_COLUMNS)
        before = self._count_samples()
        self.conn.executemany(
            f"INSERT OR IGNORE INTO samples ({col_names}) VALUES ({placeholders})",
            rows,
        )
        self.conn.commit()
        after = self._count_samples()
        inserted = after - before
        logger.info(
            "Bulk inserted %d records (%d skipped as duplicates)",
            inserted,
            len(records) - inserted,
        )
        return inserted

    def _count_samples(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM samples").fetchone()
        return row[0]

    def get_all(self) -> pd.DataFrame:
        """Return every sample as a DataFrame."""
        return pd.read_sql("SELECT * FROM samples ORDER BY filename", self.conn)

    def search_by_name(self, query: str) -> pd.DataFrame:
        """LIKE-based filename search. Returns matching samples as DataFrame."""
        return pd.read_sql(
            "SELECT * FROM samples WHERE filename LIKE ? ORDER BY filename",
            self.conn,
            params=(f"%{query}%",),
        )

    def filter_by_category(self, category: str) -> pd.DataFrame:
        """Return samples matching the given category."""
        return pd.read_sql(
            "SELECT * FROM samples WHERE category = ? ORDER BY filename",
            self.conn,
            params=(category,),
        )

    def filter_by_bpm_range(self, bpm_min: float, bpm_max: float) -> pd.DataFrame:
        """Return samples with BPM within the given range (inclusive)."""
        return pd.read_sql(
            "SELECT * FROM samples WHERE bpm >= ? AND bpm <= ? ORDER BY bpm",
            self.conn,
            params=(bpm_min, bpm_max),
        )

    def filter_by_key(self, musical_key: str) -> pd.DataFrame:
        """Return samples in the given musical key."""
        return pd.read_sql(
            "SELECT * FROM samples WHERE musical_key = ? ORDER BY filename",
            self.conn,
            params=(musical_key,),
        )

    def get_stats(self) -> dict[str, Any]:
        """High-level catalog statistics."""
        stats: dict[str, Any] = {}
        stats["total_count"] = self._count_samples()

        row = self.conn.execute(
            "SELECT AVG(bpm) FROM samples WHERE bpm IS NOT NULL"
        ).fetchone()
        stats["avg_bpm"] = round(row[0], 1) if row[0] else 0.0

        row = self.conn.execute(
            "SELECT SUM(duration_seconds) FROM samples WHERE duration_seconds IS NOT NULL"
        ).fetchone()
        stats["total_duration_seconds"] = round(row[0], 1) if row[0] else 0.0

        row = self.conn.execute(
            "SELECT SUM(file_size_bytes) FROM samples WHERE file_size_bytes IS NOT NULL"
        ).fetchone()
        stats["total_size_bytes"] = row[0] or 0

        rows = self.conn.execute(
            "SELECT format, COUNT(*) FROM samples GROUP BY format"
        ).fetchall()
        stats["by_format"] = {r[0]: r[1] for r in rows}

        rows = self.conn.execute(
            "SELECT category, COUNT(*) FROM samples GROUP BY category"
        ).fetchall()
        stats["by_category"] = {r[0]: r[1] for r in rows}

        return stats

    def delete_missing(self) -> int:
        """Remove entries whose file_path no longer exists on disk.

        Returns count of deleted rows.
        """
        rows = self.conn.execute("SELECT id, file_path FROM samples").fetchall()
        missing_ids = [row["id"] for row in rows if not Path(row["file_path"]).exists()]
        if not missing_ids:
            return 0
        placeholders = ",".join("?" * len(missing_ids))
        self.conn.execute(
            f"DELETE FROM samples WHERE id IN ({placeholders})",
            missing_ids,
        )
        self.conn.commit()
        logger.info("Deleted %d stale entries", len(missing_ids))
        return len(missing_ids)

    def get_scanned_paths(self) -> set[str]:
        """Return set of all file_path values currently in the database."""
        rows = self.conn.execute("SELECT file_path FROM samples").fetchall()
        return {row["file_path"] for row in rows}
