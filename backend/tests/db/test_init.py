from __future__ import annotations

import re

from app import db

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_init_creates_file_and_parent_dir(tmp_path):
    path = tmp_path / "nested" / "dir" / "finally.db"
    db.init_db(str(path))
    assert path.exists()


def test_seed(conn):
    assert db.get_cash(conn) == 10000.0
    assert db.get_watchlist(conn) == list(db.DEFAULT_WATCHLIST)
    assert db.get_positions(conn) == []
    assert db.get_snapshots(conn) == []
    assert db.get_recent_messages(conn) == []
    assert db.get_trades(conn) == []


def test_init_idempotent_and_seeds_once(tmp_path):
    path = str(tmp_path / "f.db")
    db.init_db(path)
    conn = db.get_conn()
    db.remove_watchlist(conn, "AAPL")
    db.apply_trade(conn, "MSFT", "buy", 1, 100.0)
    db.init_db(path)
    db.init_db(path)
    conn = db.get_conn()
    assert db.get_cash(conn) == 9900.0
    assert "AAPL" not in db.get_watchlist(conn)
    assert len(db.get_watchlist(conn)) == 9
    assert conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0] == 1


def test_get_conn_follows_init_path(tmp_path):
    db.init_db(str(tmp_path / "a.db"))
    a = db.get_conn()
    db.add_watchlist(a, "PYPL")
    db.init_db(str(tmp_path / "b.db"))
    b = db.get_conn()
    assert "PYPL" not in db.get_watchlist(b)
    assert db.get_conn() is b


def test_connection_settings(conn):
    assert conn.row_factory is not None
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_user_id_columns_default(conn):
    for table in ("watchlist", "positions", "trades", "portfolio_snapshots", "chat_messages"):
        cols = {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})")}
        assert cols["user_id"]["dflt_value"] == "'default'", table


def test_timestamps_iso_utc_z(conn):
    db.record_snapshot(conn, 1.0)
    msg = db.add_message(conn, "user", "hi")
    t = db.apply_trade(conn, "AAPL", "buy", 1, 10.0)
    for ts in (db.get_snapshots(conn)[0]["recorded_at"], msg["created_at"], t["executed_at"]):
        assert ISO_Z.match(ts), ts
