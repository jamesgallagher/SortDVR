"""SQLite state — idempotency across restarts + a decision log (tuning corpus).

Keyed by Dispatcharr recording id. Statuses: seen | classified | routed |
review | failed. `routed` is terminal for the happy path — a routed recording
is never reprocessed even if it still shows up in the API list.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id         INTEGER PRIMARY KEY,
    status     TEXT NOT NULL,     -- seen|classified|routed|review|failed
    decision   TEXT,              -- TV|MOVIE|SPORT|REVIEW
    confidence REAL,
    dest       TEXT,
    title      TEXT,
    updated_at TEXT NOT NULL
);
"""


class State:
    def __init__(self, path: str = "sortdvr.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def get(self, rec_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM recordings WHERE id=?", (rec_id,)
        ).fetchone()

    def status(self, rec_id: int) -> str:
        row = self.get(rec_id)
        return row["status"] if row else ""

    def is_routed(self, rec_id: int) -> bool:
        return self.status(rec_id) == "routed"

    def record(self, rec_id: int, status: str, *, decision: str | None = None,
               confidence: float | None = None, dest: str | None = None,
               title: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO recordings (id, status, decision, confidence, dest, title, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status=excluded.status, decision=excluded.decision,
                 confidence=excluded.confidence, dest=excluded.dest,
                 title=excluded.title, updated_at=excluded.updated_at""",
            (rec_id, status, decision, confidence, dest, title,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
