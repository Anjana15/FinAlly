"""Structured output the LLM must return (TEAM_CONTRACT §4). Every field is required; arrays may be empty."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class TradeInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: Literal["add", "remove"]


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    trades: list[TradeInstruction]
    watchlist_changes: list[WatchlistInstruction]
