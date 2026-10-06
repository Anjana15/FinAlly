"""Reads and simple writes. All synchronous; every write commits."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .util import new_id, utc_now_iso

# ---- reads ----


def get_cash(conn: sqlite3.Connection, user_id: str = "default") -> float:
    row = conn.execute("SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)).fetchone()
    return float(row[0]) if row is not None else 0.0


def get_watchlist(conn: sqlite3.Connection, user_id: str = "default") -> list[str]:
    """Tickers ordered by added_at (insertion order breaks ties, e.g. the seed)."""
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid", (user_id,)
    ).fetchall()
    return [r[0] for r in rows]


def _position_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {"ticker": row["ticker"], "quantity": float(row["quantity"]), "avg_cost": float(row["avg_cost"])}


def get_positions(conn: sqlite3.Connection, user_id: str = "default") -> list[dict]:
    rows = conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? AND quantity > 0 ORDER BY ticker",
        (user_id,),
    ).fetchall()
    return [_position_dict(r) for r in rows]


def get_position(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> dict | None:
    row = conn.execute(
        "SELECT ticker, quantity, avg_cost FROM positions WHERE user_id = ? AND ticker = ?",
        (user_id, ticker),
    ).fetchone()
    return _position_dict(row) if row is not None else None


def tracked_tickers(conn: sqlite3.Connection, user_id: str = "default") -> set[str]:
    """Watchlist ∪ tickers with an open position: what the market source must price."""
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? "
        "UNION SELECT ticker FROM positions WHERE user_id = ? AND quantity > 0",
        (user_id, user_id),
    ).fetchall()
    return {r[0] for r in rows}


def get_snapshots(conn: sqlite3.Connection, user_id: str = "default", limit: int = 500) -> list[dict]:
    """The last `limit` snapshots, oldest → newest."""
    rows = conn.execute(
        "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? "
        "ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
        (user_id, int(limit)),
    ).fetchall()
    return [{"total_value": float(r["total_value"]), "recorded_at": r["recorded_at"]} for r in reversed(rows)]


def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
    actions = row["actions"]
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "actions": json.loads(actions) if actions is not None else None,
        "created_at": row["created_at"],
    }


def get_recent_messages(conn: sqlite3.Connection, user_id: str = "default", limit: int = 20) -> list[dict]:
    """The last `limit` chat messages, oldest → newest, with `actions` parsed from JSON."""
    rows = conn.execute(
        "SELECT id, role, content, actions, created_at FROM chat_messages WHERE user_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (user_id, int(limit)),
    ).fetchall()
    return [_message_dict(r) for r in reversed(rows)]


def get_trades(conn: sqlite3.Connection, user_id: str = "default", limit: int = 100) -> list[dict]:
    """Newest first."""
    rows = conn.execute(
        "SELECT id, ticker, side, quantity, price, executed_at FROM trades WHERE user_id = ? "
        "ORDER BY executed_at DESC, rowid DESC LIMIT ?",
        (user_id, int(limit)),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "ticker": r["ticker"],
            "side": r["side"],
            "quantity": float(r["quantity"]),
            "price": float(r["price"]),
            "executed_at": r["executed_at"],
        }
        for r in rows
    ]


# ---- writes ----


def add_watchlist(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> bool:
    """True if inserted, False if the ticker was already on the watchlist."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        (new_id(), user_id, ticker, utc_now_iso()),
    )
    conn.commit()
    return cur.rowcount == 1


def remove_watchlist(conn: sqlite3.Connection, ticker: str, user_id: str = "default") -> bool:
    """True if a row was deleted."""
    cur = conn.execute("DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker))
    conn.commit()
    return cur.rowcount > 0


def record_snapshot(conn: sqlite3.Connection, total_value: float, user_id: str = "default") -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
        (new_id(), user_id, round(float(total_value), 2), utc_now_iso()),
    )
    conn.commit()


def add_message(
    conn: sqlite3.Connection,
    role: str,
    content: str,
    actions: dict | None = None,
    user_id: str = "default",
) -> dict:
    """Store a chat message (`actions` as JSON text) and return it in get_recent_messages shape."""
    msg_id = new_id()
    created_at = utc_now_iso()
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (msg_id, user_id, role, content, json.dumps(actions) if actions is not None else None, created_at),
    )
    conn.commit()
    return {
        "id": msg_id,
        "role": role,
        "content": content,
        "actions": json.loads(json.dumps(actions)) if actions is not None else None,
        "created_at": created_at,
    }
