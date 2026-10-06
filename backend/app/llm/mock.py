"""Deterministic LLM_MOCK=true responses (TEAM_CONTRACT §4). The E2E suite depends on these exact strings."""

from __future__ import annotations

import re

from .schema import LLMResponse, TradeInstruction, WatchlistInstruction

_QTY = r"(\d+(?:\.\d+)?|\.\d+)"
_TICKER = r"([a-z][a-z.]{0,5})(?![a-z.])"

_TRADE_RE = {
    side: re.compile(rf"\b{side}\s+{_QTY}\s+{_TICKER}", re.IGNORECASE) for side in ("buy", "sell")
}
_WATCH_RE = {
    action: re.compile(rf"\b{action}\s+{_TICKER}", re.IGNORECASE) for action in ("add", "remove")
}

DEFAULT_MESSAGE = (
    "Mock response: I can help you analyze your portfolio, place trades, and manage your watchlist."
)


def mock_response(user_message: str) -> LLMResponse:
    """Apply the first matching rule, in order: buy, sell, add, remove, fallback."""
    for side, rx in _TRADE_RE.items():
        m = rx.search(user_message)
        if m:
            qty_text, ticker = m.group(1), m.group(2).upper()
            return LLMResponse(
                message=f"Placing a {side} order for {qty_text} {ticker}.",
                trades=[TradeInstruction(ticker=ticker, side=side, quantity=float(qty_text))],
                watchlist_changes=[],
            )
    for action, rx in _WATCH_RE.items():
        m = rx.search(user_message)
        if m:
            ticker = m.group(1).upper()
            text = (
                f"Adding {ticker} to your watchlist."
                if action == "add"
                else f"Removing {ticker} from your watchlist."
            )
            return LLMResponse(
                message=text,
                trades=[],
                watchlist_changes=[WatchlistInstruction(ticker=ticker, action=action)],
            )
    return LLMResponse(message=DEFAULT_MESSAGE, trades=[], watchlist_changes=[])
