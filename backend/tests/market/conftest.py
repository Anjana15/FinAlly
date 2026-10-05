from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.market.cache import PriceCache
from app.market.massive_client import MassiveClient
from app.market.massive_source import MassiveDataSource
from app.market.simulator import SimulatorDataSource


class FakeClock:
    def __init__(self, t: float = 1_760_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def snapshot_row(ticker: str, price: float, prev_close: float = 100.0) -> dict:
    return {
        "ticker": ticker,
        "updated": 1_759_500_000_000_000_000,
        "lastTrade": {"p": price, "t": 1_759_500_000_000_000_000},
        "prevDay": {"c": prev_close},
    }


class FakeMassive:
    """httpx handler that serves snapshot prices for every requested ticker except `unknown`."""

    def __init__(self) -> None:
        self.prices: dict[str, float] = {}
        self.unknown: set[str] = {"ZZZZ"}
        self.calls: list[httpx.Request] = []
        self.status_code = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"status": "ERROR", "message": "boom"})
        wanted = request.url.params["tickers"].split(",")
        rows = [snapshot_row(t, self.prices.get(t, 150.0)) for t in wanted if t not in self.unknown]
        return httpx.Response(200, json={"status": "OK", "count": len(rows), "tickers": rows})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(clock: FakeClock) -> PriceCache:
    return PriceCache(clock=clock)


@pytest.fixture
def fake_massive() -> FakeMassive:
    return FakeMassive()


def make_massive(cache: PriceCache, handler, **kw) -> MassiveDataSource:
    client = MassiveClient("test-key", transport=httpx.MockTransport(handler))
    return MassiveDataSource(cache, client, today=lambda: date(2026, 10, 5), **kw)


@pytest.fixture(params=["simulator", "massive"])
async def source(request, cache, fake_massive):
    if request.param == "simulator":
        src = SimulatorDataSource(cache, seed=42, tick_interval=0.01)
    else:
        src = make_massive(cache, fake_massive, poll_interval=1.0)
    yield src
    await src.stop()
