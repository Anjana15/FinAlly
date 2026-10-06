"""FastAPI app: lifespan wiring, /api routers, static frontend at "/"."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
# Before importing app.db: it reads FINALLY_DB_PATH at import time. Real env vars win.
load_dotenv(REPO_ROOT / ".env", override=False)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app import db  # noqa: E402
from app.api import chat_history_router, portfolio_router, watchlist_router  # noqa: E402
from app.api.errors import validation_error_handler  # noqa: E402
from app.market import PriceCache, create_market_data_source  # noqa: E402
from app.market.sse import router as market_router  # noqa: E402
from app.services.portfolio import portfolio_snapshot_loop  # noqa: E402

log = logging.getLogger(__name__)

DEFAULT_STATIC_DIR = REPO_ROOT / "frontend" / "out"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(os.environ.get("FINALLY_DB_PATH") or None)  # schema + seed; must finish first
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(db.tracked_tickers(db.get_conn()))  # cache is warm before the first request
    app.state.prices, app.state.market = cache, source
    app.state.shutting_down = asyncio.Event()
    snapshot_task = asyncio.create_task(portfolio_snapshot_loop(app))
    try:
        yield
    finally:
        app.state.shutting_down.set()
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
        await source.stop()


def create_app(static_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/api/health")
    async def health(request: Request):
        return {"status": "ok", "market": request.app.state.market.status().to_dict()}

    app.include_router(market_router)
    app.include_router(watchlist_router)
    app.include_router(portfolio_router)
    app.include_router(chat_history_router)
    from app.llm.router import router as chat_router

    app.include_router(chat_router)

    # Mounted LAST so it never shadows /api/*. Absent in dev/tests without a frontend build.
    static = Path(static_dir or os.environ.get("FINALLY_STATIC_DIR") or DEFAULT_STATIC_DIR)
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    else:
        log.info("static dir %s not found; serving API only", static)
    return app


app = create_app()
