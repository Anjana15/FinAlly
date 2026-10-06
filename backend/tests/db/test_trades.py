from __future__ import annotations

import math

import pytest

from app import db
from app.db import TradeError


def _state(conn):
    return (
        db.get_cash(conn),
        db.get_positions(conn),
        conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
    )


def test_buy_creates_position_and_debits_cash(conn):
    r = db.apply_trade(conn, "AAPL", "buy", 10, 190.0)
    assert r["cash_balance"] == 8100.0
    assert r["position"] == {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 190.0}
    assert set(r) == {"id", "ticker", "side", "quantity", "price", "executed_at", "cash_balance", "position"}
    assert (r["ticker"], r["side"], r["quantity"], r["price"]) == ("AAPL", "buy", 10.0, 190.0)
    assert db.get_cash(conn) == 8100.0
    assert db.get_position(conn, "AAPL") == {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 190.0}
    assert db.get_trades(conn)[0]["id"] == r["id"]


def test_second_buy_weighted_avg_cost(conn):
    db.apply_trade(conn, "AAPL", "buy", 10, 100.0)
    r = db.apply_trade(conn, "AAPL", "buy", 30, 200.0)
    assert r["position"]["quantity"] == 40.0
    assert r["position"]["avg_cost"] == pytest.approx(175.0)
    assert db.get_position(conn, "AAPL")["avg_cost"] == pytest.approx(175.0)
    assert db.get_cash(conn) == 10000.0 - 1000.0 - 6000.0


def test_sell_keeps_avg_cost_and_credits_cash(conn):
    db.apply_trade(conn, "AAPL", "buy", 10, 100.0)
    r = db.apply_trade(conn, "AAPL", "sell", 4, 150.0)
    assert r["position"] == {"ticker": "AAPL", "quantity": 6.0, "avg_cost": 100.0}
    assert r["cash_balance"] == 10000.0 - 1000.0 + 600.0


def test_full_sell_deletes_row(conn):
    db.apply_trade(conn, "AAPL", "buy", 2.5, 100.0)
    r = db.apply_trade(conn, "AAPL", "sell", 2.5, 120.0)
    assert r["position"] is None
    assert db.get_position(conn, "AAPL") is None
    assert db.get_positions(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    assert db.get_cash(conn) == 10050.0


def test_insufficient_cash_writes_nothing(conn):
    db.apply_trade(conn, "AAPL", "buy", 1, 100.0)
    before = _state(conn)
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "MSFT", "buy", 1000, 100.0)
    assert ei.value.code == "insufficient_cash"
    assert ei.value.detail
    assert _state(conn) == before


def test_buy_exact_cash_allowed(conn):
    r = db.apply_trade(conn, "AAPL", "buy", 100, 100.0)
    assert r["cash_balance"] == 0.0


def test_insufficient_shares_writes_nothing(conn):
    db.apply_trade(conn, "AAPL", "buy", 2, 100.0)
    before = _state(conn)
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "AAPL", "sell", 3, 100.0)
    assert ei.value.code == "insufficient_shares"
    assert _state(conn) == before
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "MSFT", "sell", 1, 100.0)
    assert ei.value.code == "insufficient_shares"
    assert _state(conn) == before


@pytest.mark.parametrize("qty", [0, -1, -0.5, math.nan, math.inf, -math.inf, 0.00004, "abc", None, True])
def test_invalid_quantity(conn, qty):
    before = _state(conn)
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "AAPL", "buy", qty, 100.0)
    assert ei.value.code == "invalid_quantity"
    assert _state(conn) == before


@pytest.mark.parametrize("side", ["hold", "", None, "BUYY"])
def test_invalid_side(conn, side):
    before = _state(conn)
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "AAPL", side, 1, 100.0)
    assert ei.value.code == "invalid_side"
    assert _state(conn) == before


def test_side_is_case_insensitive(conn):
    assert db.apply_trade(conn, "AAPL", "BUY", 1, 10.0)["side"] == "buy"


def test_fractional_rounding(conn):
    r = db.apply_trade(conn, "AAPL", "buy", 0.123456, 100.0)
    assert r["quantity"] == 0.1235
    assert r["position"]["quantity"] == 0.1235
    assert r["cash_balance"] == round(10000.0 - round(0.1235 * 100.0, 2), 2) == 9987.65
    # sells of the full fractional holding leave no residue row
    db.apply_trade(conn, "AAPL", "buy", 0.1, 33.33)
    held = db.get_position(conn, "AAPL")["quantity"]
    assert held == 0.2235
    db.apply_trade(conn, "AAPL", "sell", held, 50.0)
    assert db.get_position(conn, "AAPL") is None


def test_cash_stored_at_two_dp(conn):
    db.apply_trade(conn, "AAPL", "buy", 3, 33.333)
    cash = db.get_cash(conn)
    assert cash == round(cash, 2) == 9900.0


def test_trade_does_not_swallow_failure_into_later_trade(conn):
    with pytest.raises(TradeError):
        db.apply_trade(conn, "AAPL", "sell", 1, 100.0)
    r = db.apply_trade(conn, "AAPL", "buy", 1, 100.0)
    assert r["cash_balance"] == 9900.0
    assert len(db.get_trades(conn)) == 1


def test_invalid_price_is_programming_error(conn):
    with pytest.raises(ValueError):
        db.apply_trade(conn, "AAPL", "buy", 1, 0.0)


@pytest.mark.parametrize(
    ("qty", "text"),
    [(1000000, "1000000"), (1.5, "1.5"), (0.0001, "0.0001"), (2.0, "2"), (0.12345, "0.1235"), (0, "0")],
)
def test_fmt_qty_plain_notation(qty, text):
    from app.db.trades import _fmt_qty

    assert _fmt_qty(qty) == text


def test_error_detail_has_no_scientific_notation(conn):
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "AAPL", "buy", 1000000, 100.0)
    assert "1000000 AAPL" in ei.value.detail and "e+" not in ei.value.detail
    with pytest.raises(TradeError) as ei:
        db.apply_trade(conn, "AAPL", "sell", 1000000, 100.0)
    assert "1000000" in ei.value.detail and "e+" not in ei.value.detail
