"""Watchlist changes shared by the REST routes and the LLM chat."""

from __future__ import annotations

from app import db
from app.market import normalize_ticker, sync_tracked_tickers


async def sync_tracking(app, user_id: str = "default") -> None:
    """Make the market source track watchlist ∪ open positions."""
    await sync_tracked_tickers(app.state.market, db.tracked_tickers(db.get_conn(), user_id))


def _invalid(raw, e: Exception) -> dict:
    return {"status": "failed", "ticker": raw if isinstance(raw, str) else str(raw),
            "error": "invalid_ticker", "detail": str(e)}


async def add_ticker(app, ticker, user_id: str = "default") -> dict:
    """{"status": "added"|"exists"|"failed", "ticker", "error"?, "detail"?}"""
    try:
        t = normalize_ticker(ticker)
    except (ValueError, AttributeError) as e:
        return _invalid(ticker, e)
    inserted = db.add_watchlist(db.get_conn(), t, user_id)
    await sync_tracking(app, user_id)
    return {"status": "added" if inserted else "exists", "ticker": t}


async def remove_ticker(app, ticker, user_id: str = "default") -> dict:
    """{"status": "removed"|"not_found"|"failed", "ticker", "error"?, "detail"?}

    A ticker that is still held stays tracked (priced) after leaving the watchlist.
    """
    try:
        t = normalize_ticker(ticker)
    except (ValueError, AttributeError) as e:
        return _invalid(ticker, e)
    removed = db.remove_watchlist(db.get_conn(), t, user_id)
    if not removed:
        return {"status": "not_found", "ticker": t, "error": "not_found",
                "detail": f"{t} is not on the watchlist"}
    await sync_tracking(app, user_id)
    return {"status": "removed", "ticker": t}
