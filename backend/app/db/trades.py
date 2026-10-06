"""The one atomic trade write: validation + cash + position + trades row in a single transaction."""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from .queries import get_cash, get_position
from .util import new_id, utc_now_iso

QTY_DP = 4
CASH_EPS = 1e-9
QTY_EPS = 1e-6


def _fmt_qty(qty: float) -> str:
    """Plain notation, up to 4 dp, trailing zeros stripped (1000000 -> "1000000", 1.5 -> "1.5")."""
    text = f"{qty:.{QTY_DP}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


class TradeError(Exception):
    """A business-rule rejection. Nothing was written when this is raised."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code  # "insufficient_cash" | "insufficient_shares" | "invalid_quantity" | "invalid_side"
        self.detail = detail


def _validate(side: Any, quantity: Any, price: Any) -> tuple[str, float, float]:
    side_n = side.strip().lower() if isinstance(side, str) else side
    if side_n not in ("buy", "sell"):
        raise TradeError("invalid_side", f"side must be 'buy' or 'sell', got {side!r}")
    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        raise TradeError("invalid_quantity", f"quantity must be a number, got {quantity!r}") from None
    if isinstance(quantity, bool) or not math.isfinite(qty) or qty <= 0:
        raise TradeError("invalid_quantity", f"quantity must be a positive finite number, got {quantity!r}")
    qty = round(qty, QTY_DP)
    if qty <= 0:
        raise TradeError("invalid_quantity", f"quantity {quantity!r} rounds to 0 at {QTY_DP} decimal places")
    px = float(price)
    if not math.isfinite(px) or px <= 0:
        # The caller (services.trading) guarantees a cached price; this is a programming error.
        raise ValueError(f"invalid price: {price!r}")
    return side_n, qty, px


def apply_trade(
    conn: sqlite3.Connection,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = "default",
) -> dict:
    """Validate and write atomically, or raise TradeError and write nothing.

    Returns {"id","ticker","side","quantity","price","executed_at","cash_balance",
             "position": {"ticker","quantity","avg_cost"} | None}.
    """
    side, qty, price = _validate(side, quantity, price)
    if conn.in_transaction:
        conn.commit()  # never fold someone else's pending writes into (or roll them back with) ours
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _apply(conn, ticker, side, qty, price, user_id)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return result


def _apply(conn: sqlite3.Connection, ticker: str, side: str, qty: float, price: float, user_id: str) -> dict:
    cash = get_cash(conn, user_id)
    pos = get_position(conn, ticker, user_id)
    held = pos["quantity"] if pos else 0.0
    now = utc_now_iso()
    notional = round(qty * price, 2)

    if side == "buy":
        if notional > cash + CASH_EPS:
            raise TradeError(
                "insufficient_cash",
                f"buying {_fmt_qty(qty)} {ticker} costs ${notional:,.2f} but only ${cash:,.2f} is available",
            )
        new_cash = round(cash - notional, 2)
        new_qty = round(held + qty, QTY_DP)
        new_avg = ((held * pos["avg_cost"]) + qty * price) / new_qty if pos else price
    else:
        if qty > held + QTY_EPS:
            raise TradeError("insufficient_shares", f"cannot sell {_fmt_qty(qty)} {ticker}; only {_fmt_qty(held)} held")
        new_cash = round(cash + notional, 2)
        new_qty = round(held - qty, QTY_DP)
        new_avg = pos["avg_cost"] if pos else price

    conn.execute("UPDATE users_profile SET cash_balance = ? WHERE id = ?", (new_cash, user_id))
    position: dict | None
    if abs(new_qty) < QTY_EPS:
        conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker))
        position = None
    else:
        conn.execute(
            "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id, ticker) DO UPDATE SET "
            "quantity = excluded.quantity, avg_cost = excluded.avg_cost, updated_at = excluded.updated_at",
            (new_id(), user_id, ticker, new_qty, new_avg, now),
        )
        position = {"ticker": ticker, "quantity": new_qty, "avg_cost": new_avg}

    trade_id = new_id()
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trade_id, user_id, ticker, side, qty, price, now),
    )
    return {
        "id": trade_id,
        "ticker": ticker,
        "side": side,
        "quantity": qty,
        "price": price,
        "executed_at": now,
        "cash_balance": new_cash,
        "position": position,
    }
