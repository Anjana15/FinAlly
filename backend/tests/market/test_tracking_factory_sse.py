import asyncio
import json

import pytest

from app.market import PriceUnavailable, price_for_trade, sync_tracked_tickers
from app.market.factory import create_market_data_source
from app.market.massive_source import MassiveDataSource
from app.market.simulator import SimulatorDataSource
from app.market.sse import price_events

from .conftest import make_massive


# ---- factory ---------------------------------------------------------------
@pytest.mark.parametrize("env", [{}, {"MASSIVE_API_KEY": ""}, {"MASSIVE_API_KEY": "   "}])
def test_factory_simulator(cache, env):
    assert isinstance(create_market_data_source(cache, env), SimulatorDataSource)


async def test_factory_massive(cache):
    src = create_market_data_source(cache, {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": "2"})
    assert isinstance(src, MassiveDataSource) and src.max_quote_age == 16
    await src.stop()


def test_factory_seed(cache):
    a = create_market_data_source(cache, {"SIMULATOR_SEED": "7"})
    assert a._seed == 7
    assert create_market_data_source(cache, {})._seed is None


# ---- tracking --------------------------------------------------------------
async def test_sync_tracked_tickers(cache):
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL", "MSFT"])
    await sync_tracked_tickers(src, {"AAPL", "TSLA"})
    assert src.tickers() == {"AAPL", "TSLA"} and "MSFT" not in cache
    await src.stop()


async def test_price_for_trade(cache, clock):
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL"])
    assert (await price_for_trade(cache, src, "AAPL")).price == 190.0
    assert (await price_for_trade(cache, src, "PYPL")).ticker == "PYPL"  # auto-tracked
    clock.advance(src.max_quote_age + 1)
    with pytest.raises(PriceUnavailable) as e:
        await price_for_trade(cache, src, "AAPL")
    assert e.value.code == "stale_price"
    await src.stop()


async def test_price_for_trade_no_price(cache, fake_massive):
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    with pytest.raises(PriceUnavailable) as e:
        await price_for_trade(cache, src, "ZZZZ")
    assert e.value.code == "no_price"
    await src.stop()


# ---- SSE -------------------------------------------------------------------
async def test_sse_sends_snapshot_then_only_on_change(cache):
    src = SimulatorDataSource(cache, seed=1, tick_interval=3600)  # loop ticks once, then idles
    await src.start(["AAPL", "MSFT"])
    await asyncio.sleep(0)
    stops = iter([False, False, False, True])

    async def should_stop():
        return next(stops)

    frames = []
    gen = price_events(cache, src, should_stop, interval=0, keepalive=3600)
    async for f in gen:
        frames.append(f)
        if len([x for x in frames if x.startswith("data:")]) == 1:
            src.tick()  # change prices once, after the first data frame
    data = [json.loads(f[6:]) for f in frames if f.startswith("data: ")]
    assert frames[0] == "retry: 3000\n\n"
    assert len(data) == 2  # initial snapshot + one after tick; third loop had no change
    assert set(data[0]["quotes"]) == {"AAPL", "MSFT"}
    assert data[0]["source"] == {"source": "simulator", "state": "ok", "message": None}
    await src.stop()


async def test_sse_keepalive(cache):
    src = SimulatorDataSource(cache, seed=1, tick_interval=3600)
    await src.start(["AAPL"])
    await asyncio.sleep(0)
    stops = iter([False, False, True])

    async def should_stop():
        return next(stops)

    frames = [f async for f in price_events(cache, src, should_stop, interval=0, keepalive=0)]
    assert frames[-1] == ": keep-alive\n\n"
    await src.stop()


async def test_sse_route_streams_and_stops_on_shutdown(cache):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.market.sse import router

    app = FastAPI()
    app.include_router(router)
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL"])
    app.state.prices, app.state.market = cache, src
    app.state.shutting_down = asyncio.Event()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        app.state.shutting_down.set()  # stream ends after the initial retry/data frame
        r = await client.get("/api/stream/prices")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.text.startswith("retry: 3000")
    await src.stop()
