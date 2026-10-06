"""Portfolio valuation (mark-to-market) and the periodic snapshot task."""

from __future__ import annotations

import asyncio
import logging

from app import db
from app.market import PriceCache

log = logging.getLogger(__name__)

SNAPSHOT_INTERVAL = 30.0


def mark_to_market(cache: PriceCache, cash: float, positions: list[dict]) -> dict:
    """Value positions at cached prices. An unpriced position makes the total None, never 0."""
    rows, total, complete = [], cash, True
    for p in positions:  # p: {"ticker", "quantity", "avg_cost"}
        q = cache.get(p["ticker"])
        if q is None:
            complete = False
            rows.append({**p, "price": None, "market_value": None, "unrealized_pnl": None, "pnl_percent": None})
            continue
        mv = p["quantity"] * q.price
        cost = p["quantity"] * p["avg_cost"]
        total += mv
        rows.append({**p, "price": q.price, "market_value": round(mv, 2),
                     "unrealized_pnl": round(mv - cost, 2),
                     "pnl_percent": round((q.price - p["avg_cost"]) / p["avg_cost"] * 100, 2) if p["avg_cost"] else 0.0})
    return {"cash": round(cash, 2), "positions": rows,
            "total_value": round(total, 2) if complete else None, "valuation_complete": complete}


def current_valuation(app, user_id: str = "default") -> dict:
    conn = db.get_conn()
    return mark_to_market(app.state.prices, db.get_cash(conn, user_id), db.get_positions(conn, user_id))


def portfolio_view(app, user_id: str = "default") -> dict:
    """The GET /api/portfolio body."""
    v = current_valuation(app, user_id)
    return {"cash": v["cash"], "total_value": v["total_value"],
            "valuation_complete": v["valuation_complete"], "positions": v["positions"]}


def record_snapshot_if_complete(app, user_id: str = "default") -> bool:
    """Record a snapshot of the total value. Skipped (False) if any holding is unpriced."""
    v = current_valuation(app, user_id)
    if v["total_value"] is None:
        return False
    db.record_snapshot(db.get_conn(), v["total_value"], user_id)
    return True


async def portfolio_snapshot_loop(app, interval: float = SNAPSHOT_INTERVAL) -> None:
    """Record a snapshot now and then every `interval` seconds until cancelled."""
    while True:
        try:
            if not record_snapshot_if_complete(app):
                log.info("portfolio snapshot skipped: valuation incomplete")
        except Exception:  # keep the loop alive; a failed snapshot is not fatal
            log.exception("portfolio snapshot failed")
        await asyncio.sleep(interval)
