"""SQLite persistence (stdlib sqlite3, synchronous). Consumers import only from here."""

from .connection import DB_PATH, get_conn, init_db
from .queries import (
    add_message,
    add_watchlist,
    get_cash,
    get_position,
    get_positions,
    get_recent_messages,
    get_snapshots,
    get_trades,
    get_watchlist,
    record_snapshot,
    remove_watchlist,
    tracked_tickers,
)
from .schema import DEFAULT_CASH, DEFAULT_WATCHLIST
from .trades import TradeError, apply_trade

__all__ = [
    "DB_PATH",
    "DEFAULT_CASH",
    "DEFAULT_WATCHLIST",
    "TradeError",
    "add_message",
    "add_watchlist",
    "apply_trade",
    "get_cash",
    "get_conn",
    "get_position",
    "get_positions",
    "get_recent_messages",
    "get_snapshots",
    "get_trades",
    "get_watchlist",
    "init_db",
    "record_snapshot",
    "remove_watchlist",
    "tracked_tickers",
]
