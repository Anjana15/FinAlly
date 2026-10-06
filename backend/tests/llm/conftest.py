from __future__ import annotations

import sys
import types
import uuid
from types import SimpleNamespace

import pytest

from app.market.cache import PriceCache


class FakeDB(types.ModuleType):
    """Stands in for app.db (TEAM_CONTRACT §2.1): only the functions the chat service uses."""

    def __init__(self) -> None:
        super().__init__("app.db")
        self.messages: list[dict] = []
        self.watchlist: list[str] = ["AAPL", "TSLA"]

    def get_conn(self):
        return object()

    def get_watchlist(self, conn, user_id="default"):
        return list(self.watchlist)

    def get_recent_messages(self, conn, user_id="default", limit=20):
        return [dict(m) for m in self.messages[-limit:]]

    def add_message(self, conn, role, content, actions=None, user_id="default"):
        row = {"id": str(uuid.uuid4()), "role": role, "content": content, "actions": actions,
               "created_at": "2026-10-06T12:00:00Z"}
        self.messages.append(row)
        return dict(row)


class FakeServices:
    def __init__(self) -> None:
        self.trade_calls: list[tuple] = []
        self.watch_calls: list[tuple] = []
        self.fail_tickers: set[str] = set()
        self.portfolio = {"cash": 10000.0, "total_value": 10000.0, "valuation_complete": True,
                          "positions": []}

        self.trading = types.ModuleType("app.services.trading")
        self.watchlist = types.ModuleType("app.services.watchlist")
        self.portfolio_mod = types.ModuleType("app.services.portfolio")
        self.trading.execute_trade = self.execute_trade
        self.watchlist.add_ticker = self.add_ticker
        self.watchlist.remove_ticker = self.remove_ticker
        self.portfolio_mod.portfolio_view = lambda app, user_id="default": self.portfolio

    async def execute_trade(self, app, ticker, side, quantity, user_id="default"):
        self.trade_calls.append((ticker, side, quantity))
        if ticker in self.fail_tickers:
            return {"status": "failed", "ticker": ticker, "side": side, "quantity": quantity,
                    "error": "insufficient_cash", "detail": "Not enough cash"}
        return {"status": "executed", "ticker": ticker, "side": side, "quantity": quantity,
                "price": 100.0, "executed_at": "2026-10-06T12:00:00Z", "cash_balance": 9900.0}

    async def add_ticker(self, app, ticker, user_id="default"):
        self.watch_calls.append(("add", ticker))
        return {"status": "added", "ticker": ticker.upper()}

    async def remove_ticker(self, app, ticker, user_id="default"):
        self.watch_calls.append(("remove", ticker))
        return {"status": "not_found", "ticker": ticker.upper()}


@pytest.fixture
def fake_db(monkeypatch) -> FakeDB:
    db = FakeDB()
    monkeypatch.setitem(sys.modules, "app.db", db)
    return db


@pytest.fixture
def fake_services(monkeypatch) -> FakeServices:
    s = FakeServices()
    monkeypatch.setitem(sys.modules, "app.services.trading", s.trading)
    monkeypatch.setitem(sys.modules, "app.services.watchlist", s.watchlist)
    monkeypatch.setitem(sys.modules, "app.services.portfolio", s.portfolio_mod)
    return s


@pytest.fixture
def fake_app():
    cache = PriceCache()
    cache.update("AAPL", 190.0, source="simulator")
    return SimpleNamespace(state=SimpleNamespace(prices=cache))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any accidental real LLM call fails loudly instead of hitting OpenRouter."""
    from app.llm import client

    def boom(**kwargs):
        raise AssertionError("tests must not call litellm")

    monkeypatch.setattr(client, "_completion", boom)
    monkeypatch.delenv("LLM_MOCK", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
