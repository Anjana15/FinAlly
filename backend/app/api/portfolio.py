"""/api/portfolio: valuation, trades, value history."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import db
from app.services.portfolio import portfolio_view
from app.services.trading import execute_trade

from .errors import error_response

router = APIRouter()

HISTORY_DEFAULT = 500
HISTORY_MAX = 2000


class TradeRequest(BaseModel):
    ticker: str
    side: str
    quantity: float


@router.get("/api/portfolio")
async def get_portfolio(request: Request):
    return portfolio_view(request.app)


@router.post("/api/portfolio/trade")
async def trade(body: TradeRequest, request: Request):
    r = await execute_trade(request.app, body.ticker, body.side, body.quantity)
    if r["status"] != "executed":
        # {"error","detail"} plus the rest of the failed TradeResult
        return error_response(400, r["error"], r["detail"],
                              **{k: v for k, v in r.items() if k not in ("error", "detail")})
    return r


@router.get("/api/portfolio/history")
async def history(limit: int = HISTORY_DEFAULT):
    limit = max(1, min(limit, HISTORY_MAX))
    return {"snapshots": db.get_snapshots(db.get_conn(), limit=limit)}
