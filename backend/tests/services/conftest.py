from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pytest

from app import db
from app.market import MarketDataSource, PriceCache, SourceState, SourceStatus


class FakeClock:
    def __init__(self, t: float = 1_760_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeSource(MarketDataSource):
    """Deterministic source: prices tickers from `prices` when tracked; unknown tickers stay unpriced."""

    name = "fake"

    def __init__(self, cache: PriceCache, prices: dict[str, float], max_age: float | None = 10.0) -> None:
        super().__init__(cache)
        self.prices = prices
        self.max_age = max_age
        self._tickers: set[str] = set()

    @property
    def max_quote_age(self) -> float | None:
        return self.max_age

    async def start(self, tickers: Iterable[str]) -> None:
        for t in tickers:
            await self.add_ticker(t)

    async def stop(self) -> None:
        pass

    async def add_ticker(self, ticker: str) -> None:
        self._tickers.add(ticker)
        if ticker in self.prices:
            self.cache.update(ticker, self.prices[ticker], source=self.name)

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self.cache.remove(ticker)

    def tickers(self) -> frozenset[str]:
        return frozenset(self._tickers)

    def status(self) -> SourceStatus:
        return SourceStatus(self.name, SourceState.OK)


PRICES = {"AAPL": 100.0, "MSFT": 200.0, "GOOGL": 50.0, "AMZN": 10.0, "TSLA": 250.0,
          "NVDA": 120.0, "META": 300.0, "JPM": 150.0, "V": 250.0, "NFLX": 400.0, "PYPL": 60.0}


@pytest.fixture
async def app(tmp_path):
    db.init_db(str(tmp_path / "finally.db"))
    clock = FakeClock()
    cache = PriceCache(clock=clock)
    source = FakeSource(cache, dict(PRICES))
    await source.start(db.tracked_tickers(db.get_conn()))
    yield SimpleNamespace(state=SimpleNamespace(prices=cache, market=source, clock=clock))
    await source.stop()
