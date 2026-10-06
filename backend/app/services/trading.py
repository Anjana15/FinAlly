"""The ONE trade path, shared by POST /api/portfolio/trade and the LLM chat."""

from __future__ import annotations

import logging
import math

from app import db
from app.market import PriceUnavailable, normalize_ticker, price_for_trade

from .portfolio import record_snapshot_if_complete
from .watchlist import sync_tracking

log = logging.getLogger(__name__)

SIDES = ("buy", "sell")


def _failed(ticker, side, quantity, code: str, detail: str) -> dict:
    return {"status": "failed", "ticker": ticker, "side": side, "quantity": quantity,
            "error": code, "detail": detail}


def _check_quantity(quantity) -> float | None:
    if isinstance(quantity, bool):
        return None
    try:
        q = float(quantity)
    except (TypeError, ValueError):
        return None
    return q if math.isfinite(q) and q > 0 else None


async def execute_trade(app, ticker: str, side: str, quantity: float, user_id: str = "default") -> dict:
    """Market order at the cached price. Never raises for business errors; returns a TradeResult."""
    try:
        ticker = normalize_ticker(ticker)
    except (ValueError, AttributeError) as e:
        return _failed(ticker, side, quantity, "invalid_ticker", str(e))

    # Cheap checks first, so a bad request never starts tracking a new ticker.
    side_n = side.strip().lower() if isinstance(side, str) else side
    if side_n not in SIDES:
        return _failed(ticker, side, quantity, "invalid_side", f"side must be 'buy' or 'sell', got {side!r}")
    qty = _check_quantity(quantity)
    if qty is None:
        return _failed(ticker, side_n, quantity, "invalid_quantity",
                       f"quantity must be a positive number, got {quantity!r}")

    try:
        try:
            quote = await price_for_trade(app.state.prices, app.state.market, ticker)
        except PriceUnavailable as e:
            return _failed(ticker, side_n, qty, e.code, str(e))

        conn = db.get_conn()
        try:
            r = db.apply_trade(conn, ticker, side_n, qty, quote.price, user_id)
        except db.TradeError as e:
            return _failed(ticker, side_n, qty, e.code, e.detail)

        if side_n == "buy":
            db.add_watchlist(conn, ticker, user_id)  # PLAN §13 #7: bought tickers join the watchlist
        try:
            record_snapshot_if_complete(app, user_id)
        except Exception:  # the trade is committed; a missed snapshot must not turn it into a failure
            log.exception("post-trade snapshot failed")
        return {"status": "executed", "ticker": r["ticker"], "side": r["side"], "quantity": r["quantity"],
                "price": r["price"], "executed_at": r["executed_at"], "cash_balance": r["cash_balance"]}
    finally:
        # price_for_trade may have started tracking the ticker; drop it again unless watched or held.
        await sync_tracking(app, user_id)
