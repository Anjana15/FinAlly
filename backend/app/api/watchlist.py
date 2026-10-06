"""/api/watchlist: list, add, remove."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import db
from app.services.watchlist import add_ticker, remove_ticker

from .errors import error_response

router = APIRouter()


class AddTickerRequest(BaseModel):
    ticker: str


def _quote(request: Request, ticker: str) -> dict | None:
    q = request.app.state.prices.get(ticker)
    return q.to_dict() if q else None


@router.get("/api/watchlist")
async def list_watchlist(request: Request):
    tickers = db.get_watchlist(db.get_conn())
    return {"tickers": [{"ticker": t, "quote": _quote(request, t)} for t in tickers]}


@router.post("/api/watchlist")
async def add_to_watchlist(body: AddTickerRequest, request: Request):
    r = await add_ticker(request.app, body.ticker)
    if r["status"] == "failed":
        return error_response(400, r["error"], r["detail"])
    return {"ticker": r["ticker"], "status": r["status"], "quote": _quote(request, r["ticker"])}


@router.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    r = await remove_ticker(request.app, ticker)
    if r["status"] == "failed":
        return error_response(400, r["error"], r["detail"])
    if r["status"] == "not_found":
        return error_response(404, "not_found", r["detail"])
    return {"ticker": r["ticker"], "status": "removed"}
