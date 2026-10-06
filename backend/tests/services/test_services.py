from __future__ import annotations

import pytest

from app import db
from app.market import PriceCache
from app.services.portfolio import mark_to_market, portfolio_snapshot_loop, portfolio_view
from app.services.trading import execute_trade
from app.services.watchlist import add_ticker, remove_ticker


def conn():
    return db.get_conn()


# ---- mark_to_market ----

def test_mark_to_market_math():
    cache = PriceCache()
    cache.update("AAPL", 110.0, source="t")
    v = mark_to_market(cache, 1000.0, [{"ticker": "AAPL", "quantity": 10, "avg_cost": 100.0}])
    assert v["valuation_complete"] is True
    assert v["total_value"] == 2100.0
    row = v["positions"][0]
    assert row["price"] == 110.0
    assert row["market_value"] == 1100.0
    assert row["unrealized_pnl"] == 100.0
    assert row["pnl_percent"] == 10.0


def test_mark_to_market_unpriced_position_makes_total_none():
    cache = PriceCache()
    cache.update("AAPL", 110.0, source="t")
    v = mark_to_market(cache, 500.0, [{"ticker": "AAPL", "quantity": 1, "avg_cost": 100.0},
                                      {"ticker": "ZZZ", "quantity": 2, "avg_cost": 5.0}])
    assert v["valuation_complete"] is False
    assert v["total_value"] is None
    z = v["positions"][1]
    assert z["price"] is None and z["market_value"] is None and z["pnl_percent"] is None


def test_mark_to_market_cash_only():
    v = mark_to_market(PriceCache(), 10000.0, [])
    assert v == {"cash": 10000.0, "positions": [], "total_value": 10000.0, "valuation_complete": True}


# ---- execute_trade ----

async def test_buy_happy_path(app):
    r = await execute_trade(app, "aapl", "buy", 5)
    assert r["status"] == "executed"
    assert r["ticker"] == "AAPL" and r["side"] == "buy" and r["quantity"] == 5
    assert r["price"] == 100.0
    assert r["cash_balance"] == 9500.0
    assert r["executed_at"].endswith("Z")
    assert db.get_position(conn(), "AAPL")["quantity"] == 5
    snaps = db.get_snapshots(conn())
    assert snaps[-1]["total_value"] == 10000.0


async def test_buy_untracked_ticker_adds_to_watchlist_and_tracks(app):
    assert "PYPL" not in db.get_watchlist(conn())
    r = await execute_trade(app, "PYPL", "buy", 1)
    assert r["status"] == "executed"
    assert "PYPL" in db.get_watchlist(conn())
    assert "PYPL" in app.state.market.tickers()


async def test_failed_buy_of_untracked_ticker_stops_tracking_it(app):
    r = await execute_trade(app, "PYPL", "buy", 1_000_000)
    assert r["status"] == "failed" and r["error"] == "insufficient_cash"
    assert "PYPL" not in app.state.market.tickers()
    assert "PYPL" not in db.get_watchlist(conn())


async def test_sell_happy_path_and_full_close(app):
    await execute_trade(app, "AAPL", "buy", 2)
    r = await execute_trade(app, "AAPL", "sell", 2)
    assert r["status"] == "executed"
    assert r["cash_balance"] == 10000.0
    assert db.get_position(conn(), "AAPL") is None


async def test_insufficient_cash(app):
    r = await execute_trade(app, "AAPL", "buy", 101)  # 10100 > 10000
    assert r == {"status": "failed", "ticker": "AAPL", "side": "buy", "quantity": 101.0,
                 "error": "insufficient_cash", "detail": r["detail"]}
    assert db.get_cash(conn()) == 10000.0


async def test_insufficient_shares(app):
    r = await execute_trade(app, "AAPL", "sell", 1)
    assert r["status"] == "failed" and r["error"] == "insufficient_shares"


@pytest.mark.parametrize("ticker,side,qty,code", [
    ("123", "buy", 1, "invalid_ticker"),
    ("", "buy", 1, "invalid_ticker"),
    (None, "buy", 1, "invalid_ticker"),
    ("AAPL", "hold", 1, "invalid_side"),
    ("AAPL", None, 1, "invalid_side"),
    ("AAPL", "buy", 0, "invalid_quantity"),
    ("AAPL", "buy", -1, "invalid_quantity"),
    ("AAPL", "buy", float("nan"), "invalid_quantity"),
    ("AAPL", "buy", float("inf"), "invalid_quantity"),
    ("AAPL", "buy", "abc", "invalid_quantity"),
    ("AAPL", "buy", 0.00001, "invalid_quantity"),  # rounds to 0 at 4 dp (db layer)
])
async def test_invalid_inputs(app, ticker, side, qty, code):
    r = await execute_trade(app, ticker, side, qty)
    assert r["status"] == "failed"
    assert r["error"] == code
    assert db.get_cash(conn()) == 10000.0


async def test_side_is_case_insensitive(app):
    r = await execute_trade(app, "AAPL", "BUY", 1)
    assert r["status"] == "executed" and r["side"] == "buy"


async def test_no_price(app):
    r = await execute_trade(app, "ZZZ", "buy", 1)  # FakeSource has no price for ZZZ
    assert r["status"] == "failed" and r["error"] == "no_price"
    assert "ZZZ" not in app.state.market.tickers()


async def test_stale_price(app):
    app.state.clock.t += 60  # quotes are now 60 s old; FakeSource max age is 10 s
    r = await execute_trade(app, "AAPL", "buy", 1)
    assert r["status"] == "failed" and r["error"] == "stale_price"


async def test_snapshot_skipped_when_incomplete(app):
    await execute_trade(app, "AAPL", "buy", 1)
    n = len(db.get_snapshots(conn()))
    app.state.prices.remove("AAPL")
    from app.services.portfolio import record_snapshot_if_complete
    assert record_snapshot_if_complete(app) is False
    assert len(db.get_snapshots(conn())) == n


# ---- watchlist ----

async def test_watchlist_add_exists_remove(app):
    assert (await add_ticker(app, "pypl")) == {"status": "added", "ticker": "PYPL"}
    assert "PYPL" in app.state.market.tickers()
    assert (await add_ticker(app, "PYPL"))["status"] == "exists"
    assert (await remove_ticker(app, "pypl")) == {"status": "removed", "ticker": "PYPL"}
    assert "PYPL" not in app.state.market.tickers()
    r = await remove_ticker(app, "PYPL")
    assert r["status"] == "not_found"


async def test_watchlist_invalid(app):
    r = await add_ticker(app, "bad ticker!")
    assert r["status"] == "failed" and r["error"] == "invalid_ticker"
    r = await remove_ticker(app, "1")
    assert r["status"] == "failed" and r["error"] == "invalid_ticker"


async def test_removing_held_ticker_keeps_it_tracked(app):
    await execute_trade(app, "AAPL", "buy", 1)
    assert (await remove_ticker(app, "AAPL"))["status"] == "removed"
    assert "AAPL" not in db.get_watchlist(conn())
    assert "AAPL" in app.state.market.tickers()
    assert app.state.prices.get("AAPL") is not None


# ---- portfolio view / loop ----

async def test_portfolio_view(app):
    await execute_trade(app, "MSFT", "buy", 3)
    app.state.prices.update("MSFT", 220.0, source="t")
    v = portfolio_view(app)
    assert v["cash"] == 9400.0
    assert v["total_value"] == 9400.0 + 660.0
    assert v["valuation_complete"] is True
    p = v["positions"][0]
    assert p["ticker"] == "MSFT" and p["unrealized_pnl"] == 60.0 and p["pnl_percent"] == 10.0


async def test_snapshot_loop_records_at_startup(app):
    import asyncio

    task = asyncio.create_task(portfolio_snapshot_loop(app, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(db.get_snapshots(conn())) >= 2
