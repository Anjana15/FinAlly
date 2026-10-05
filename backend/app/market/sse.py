"""GET /api/stream/prices: full-snapshot SSE stream read from the PriceCache."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache
from .interface import MarketDataSource

router = APIRouter()

PUSH_INTERVAL = 0.5
KEEPALIVE_SECONDS = 15.0


def build_price_event(cache: PriceCache, source: MarketDataSource) -> dict:
    return {
        "type": "prices",
        "source": source.status().to_dict(),
        "quotes": {t: q.to_dict() for t, q in sorted(cache.snapshot().items())},
    }


async def price_events(
    cache: PriceCache,
    source: MarketDataSource,
    should_stop: Callable[[], Awaitable[bool]],
    *,
    interval: float = PUSH_INTERVAL,
    keepalive: float = KEEPALIVE_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE frames. A data frame only when prices or source status changed."""
    yield "retry: 3000\n\n"
    last_key: tuple | None = None
    last_sent = time.monotonic()
    while not await should_stop():
        status = source.status()
        key = (cache.version, status.state, status.message)  # not last_success: it changes every poll
        now = time.monotonic()
        if key != last_key:
            payload = json.dumps(build_price_event(cache, source), separators=(",", ":"))
            yield f"data: {payload}\n\n"
            last_key, last_sent = key, now
        elif now - last_sent >= keepalive:
            yield ": keep-alive\n\n"
            last_sent = now
        await asyncio.sleep(interval)


@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    state = request.app.state

    async def should_stop() -> bool:
        shutting_down = getattr(state, "shutting_down", None)
        return (shutting_down is not None and shutting_down.is_set()) or await request.is_disconnected()

    return StreamingResponse(
        price_events(state.prices, state.market, should_stop),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
