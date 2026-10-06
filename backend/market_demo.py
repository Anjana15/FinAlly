"""Run the market-data layer on its own, before the full app exists.

    uv run python market_demo.py                    # print live prices in the terminal
    uv run python market_demo.py --seconds 30 AAPL TSLA
    uv run python market_demo.py --serve            # SSE at http://localhost:8000/api/stream/prices

Uses the simulator unless MASSIVE_API_KEY is set (same rule as the real app).
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager

from app.market import PriceCache, create_market_data_source

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

LIVE_PAGE = """<!doctype html><meta charset="utf-8"><title>Market demo</title>
<style>body{background:#0d1117;color:#c9d1d9;font:14px monospace;padding:16px}
td,th{padding:2px 12px;text-align:right}.up{color:#3fb950}.down{color:#f85149}</style>
<p id="s">connecting...</p><table><thead><tr><th>TICKER<th>PRICE<th>CHG%</thead><tbody id="b"></tbody></table>
<script>
new EventSource("/api/stream/prices").onmessage = (e) => {
  const d = JSON.parse(e.data);
  document.getElementById("s").textContent = "source: " + d.source.source + " (" + d.source.state + ")";
  document.getElementById("b").innerHTML = Object.values(d.quotes).map(q =>
    `<tr class="${q.direction}"><td>${q.ticker}<td>${q.price.toFixed(2)}<td>${q.change_percent.toFixed(2)}%`).join("");
};
</script>"""


async def print_prices(tickers: list[str], seconds: float) -> None:
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tickers)
    print(f"source: {source.name}  status: {source.status().to_dict()}")
    try:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while loop.time() < end:
            await asyncio.sleep(1.0)
            print(f"\n{'TICKER':<7}{'PRICE':>10}{'CHG%':>9}  DIR")
            for t, q in sorted(cache.snapshot().items()):
                print(f"{t:<7}{q.price:>10.2f}{q.change_percent:>+8.2f}%  {q.direction}")
    finally:
        await source.stop()


def serve(tickers: list[str], port: int) -> None:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    from app.market.sse import router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.prices = PriceCache()
        app.state.market = create_market_data_source(app.state.prices)
        app.state.shutting_down = asyncio.Event()
        await app.state.market.start(tickers)
        yield
        app.state.shutting_down.set()
        await app.state.market.stop()

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return LIVE_PAGE

    print(f"Live table: http://localhost:{port}/")
    print(f"SSE stream: http://localhost:{port}/api/stream/prices")
    uvicorn.run(app, host="127.0.0.1", port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tickers", nargs="*", default=DEFAULT_TICKERS)
    parser.add_argument("--seconds", type=float, default=10.0, help="how long to print prices")
    parser.add_argument("--serve", action="store_true", help="serve the SSE endpoint instead of printing")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    tickers = [t.upper() for t in args.tickers]
    if args.serve:
        serve(tickers, args.port)
    else:
        asyncio.run(print_prices(tickers, args.seconds))


if __name__ == "__main__":
    main()
