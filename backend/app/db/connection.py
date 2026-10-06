"""Database location, lazy init (schema + one-time seed) and the shared connection."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .schema import DEFAULT_CASH, DEFAULT_USER_ID, DEFAULT_WATCHLIST, SCHEMA_SQL
from .util import new_id, utc_now_iso

_REPO_ROOT = Path(__file__).resolve().parents[3]

DB_PATH: str = os.environ.get("FINALLY_DB_PATH") or str(_REPO_ROOT / "db" / "finally.db")

# The path in use (init_db may override DB_PATH, e.g. tests with tmp_path) and its connection.
_active_path: str = DB_PATH
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None


def _connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """The process-wide connection to the active DB path (DB_PATH, or the path given to init_db)."""
    global _conn, _conn_path
    if _conn is None or _conn_path != _active_path:
        if _conn is not None:
            _conn.close()
        _conn = _connect(_active_path)
        _conn_path = _active_path
    return _conn


def init_db(path: str | None = None) -> None:
    """Create the parent dir, tables (IF NOT EXISTS) and the seed (only if users_profile is empty).

    Idempotent. A `path` makes it the active path for every later get_conn().
    """
    global _active_path
    if path is not None:
        _active_path = str(path)
    conn = get_conn()
    conn.executescript(SCHEMA_SQL)
    _seed(conn)


def _seed(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM users_profile LIMIT 1").fetchone() is not None:
        return
    now = utc_now_iso()
    with conn:
        conn.execute(
            "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, DEFAULT_CASH, now),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            [(new_id(), DEFAULT_USER_ID, t, now) for t in DEFAULT_WATCHLIST],
        )
