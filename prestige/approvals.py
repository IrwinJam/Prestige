"""A person approves blocked calls from another terminal.

    python -m prestige serve --labels banking --muse --ask ...
    python -m prestige buddy watch --db runs/prestige.sqlite

When the guard would block a call, the gateway writes a question to the trace database and waits.
`buddy watch` shows it and writes the answer back. No answer before the timeout means no.

The question holds the value so the person can judge it. It's wiped as soon as the answer comes in,
so the database keeps only the tool, the answer and the times.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import time
from pathlib import Path

from prestige.guard import Finding

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    key TEXT NOT NULL,
    rule TEXT NOT NULL,
    tool TEXT NOT NULL,
    arg TEXT,
    source TEXT NOT NULL,
    value TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_at TEXT
);
"""
SHOWN = 80  # longest value shown to the person


def connect(db: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=10, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def shown(value: str | None) -> str:
    """Printable and short. The value may come from an attacker."""
    text = "".join(c if c.isprintable() else "?" for c in (value or ""))
    return text if len(text) <= SHOWN else text[: SHOWN - 3] + "..."


class AskInTerminal:
    """A session approver that waits for an answer from `buddy watch`."""

    def __init__(self, db: str | Path, timeout: float = 120.0, poll: float = 0.25):
        self.db, self.timeout, self.poll = str(db), timeout, poll
        connect(self.db).close()

    def __call__(self, key: str, finding: Finding) -> bool:
        conn = connect(self.db)
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO approvals (created_at, key, rule, tool, arg, source, value) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_now(), key, finding.rule, finding.tool, finding.arg, finding.source, shown(finding.value)),
                )
            row_id = cur.lastrowid
            deadline = time.monotonic() + self.timeout
            status = "pending"
            while status == "pending" and time.monotonic() < deadline:
                time.sleep(self.poll)
                status = conn.execute("SELECT status FROM approvals WHERE id = ?", (row_id,)).fetchone()[0]
            with conn:
                conn.execute(
                    "UPDATE approvals SET value = NULL, status = ?, decided_at = coalesce(decided_at, ?) WHERE id = ?",
                    ("timeout" if status == "pending" else status, _now(), row_id),
                )
            return status == "yes"
        finally:
            conn.close()


def pending(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT id, rule, tool, arg, source, value FROM approvals WHERE status = 'pending' ORDER BY id").fetchall()


def answer(conn: sqlite3.Connection, row_id: int, yes: bool) -> bool:
    """Records the answer. False when the question already timed out."""
    with conn:
        return conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ? AND status = 'pending'",
            ("yes" if yes else "no", _now(), row_id),
        ).rowcount == 1


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
