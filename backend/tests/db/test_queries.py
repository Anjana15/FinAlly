from __future__ import annotations

from app import db


def test_watchlist_add_remove_duplicate(conn):
    assert db.add_watchlist(conn, "PYPL") is True
    assert db.add_watchlist(conn, "PYPL") is False
    assert db.get_watchlist(conn)[-1] == "PYPL"
    assert db.get_watchlist(conn).count("PYPL") == 1
    assert db.remove_watchlist(conn, "PYPL") is True
    assert db.remove_watchlist(conn, "PYPL") is False
    assert "PYPL" not in db.get_watchlist(conn)


def test_watchlist_is_per_user(conn):
    db.add_watchlist(conn, "PYPL", user_id="other")
    assert db.get_watchlist(conn, user_id="other") == ["PYPL"]
    assert "PYPL" not in db.get_watchlist(conn)


def test_tracked_tickers_union(conn):
    db.remove_watchlist(conn, "AAPL")
    db.apply_trade(conn, "AAPL", "buy", 1, 100.0)
    db.apply_trade(conn, "ZZZZ", "buy", 1, 10.0)
    tracked = db.tracked_tickers(conn)
    assert tracked == set(db.DEFAULT_WATCHLIST) | {"ZZZZ"}
    db.apply_trade(conn, "ZZZZ", "sell", 1, 10.0)
    assert "ZZZZ" not in db.tracked_tickers(conn)


def test_snapshots_order_and_limit(conn):
    for v in range(1, 8):
        db.record_snapshot(conn, float(v))
    snaps = db.get_snapshots(conn)
    assert [s["total_value"] for s in snaps] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    last3 = db.get_snapshots(conn, limit=3)
    assert [s["total_value"] for s in last3] == [5.0, 6.0, 7.0]
    assert set(last3[0]) == {"total_value", "recorded_at"}


def test_messages_order_limit_and_actions_roundtrip(conn):
    actions = {
        "trades": [{"status": "executed", "ticker": "AAPL", "side": "buy", "quantity": 1.5, "price": 190.1}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "added"}],
        "error": None,
    }
    for i in range(5):
        db.add_message(conn, "user", f"q{i}")
        stored = db.add_message(conn, "assistant", f"a{i}", actions=actions)
    assert stored["actions"] == actions
    assert set(stored) == {"id", "role", "content", "actions", "created_at"}

    msgs = db.get_recent_messages(conn)
    assert [m["content"] for m in msgs] == [x for i in range(5) for x in (f"q{i}", f"a{i}")]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"] == actions
    assert msgs[-1] == stored

    last3 = db.get_recent_messages(conn, limit=3)
    assert [m["content"] for m in last3] == ["a3", "q4", "a4"]


def test_trades_newest_first_and_limit(conn):
    db.apply_trade(conn, "AAPL", "buy", 1, 10.0)
    db.apply_trade(conn, "MSFT", "buy", 1, 10.0)
    db.apply_trade(conn, "AAPL", "sell", 1, 11.0)
    trades = db.get_trades(conn)
    assert [(t["ticker"], t["side"]) for t in trades] == [("AAPL", "sell"), ("MSFT", "buy"), ("AAPL", "buy")]
    assert len(db.get_trades(conn, limit=2)) == 2
    assert set(trades[0]) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
