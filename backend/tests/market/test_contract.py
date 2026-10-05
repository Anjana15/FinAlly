"""Behavioural contract C1-C7, run against both implementations."""

import asyncio
import math

from app.market.models import SourceState


async def test_c1_start_populates_cache(source, cache):
    await source.start(["AAPL", "MSFT"])
    assert cache.get("AAPL") is not None and cache.get("MSFT") is not None
    assert source.tickers() == {"AAPL", "MSFT"}


async def test_c2_remove_drops_from_cache(source, cache):
    await source.start(["AAPL", "MSFT"])
    await source.remove_ticker("MSFT")
    assert "MSFT" not in cache and "MSFT" not in source.tickers()
    assert set(cache.snapshot()) <= source.tickers()


async def test_c3_idempotent(source, cache):
    await source.start(["AAPL"])
    await source.start(["AAPL"])
    await source.add_ticker("NVDA")
    await source.add_ticker("NVDA")
    await source.remove_ticker("NVDA")
    await source.remove_ticker("NVDA")
    assert source.tickers() == {"AAPL"}
    await source.stop()
    await source.stop()


async def test_add_ticker_prices_immediately(source, cache):
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    assert cache.get("PYPL") is not None


async def test_c5_stop_leaves_no_tasks(source):
    await source.start(["AAPL"])
    await source.stop()
    assert source.status().state == SourceState.STOPPED
    names = {t.get_name() for t in asyncio.all_tasks()}
    assert not names & {"market-simulator", "massive-poller"}


async def test_c6_c7_writes_tagged_and_valid(source, cache):
    await source.start(["AAPL", "TSLA"])
    for q in cache.snapshot().values():
        assert q.source == source.name
        assert math.isfinite(q.price) and q.price > 0
