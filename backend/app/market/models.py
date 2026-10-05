"""Value types shared by every market-data module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class SourceState(StrEnum):
    STARTING = "starting"
    OK = "ok"
    DEGRADED = "degraded"  # producing data, but limited (EOD-only plan, rate-limited, transient errors)
    ERROR = "error"        # not producing data (invalid key); needs operator action
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class SourceStatus:
    source: str                        # "simulator" | "massive"
    state: SourceState
    message: str | None = None         # human-readable, safe to show in the UI
    last_success: float | None = None  # unix seconds of the last successful update

    def to_dict(self) -> dict:
        return {"source": self.source, "state": self.state.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class PriceQuote:
    ticker: str
    price: float            # latest price, rounded to cents
    previous_price: float   # price before this update (== price on first sighting)
    reference_price: float  # basis for change %: prev close (Massive) or first price this run (simulator)
    timestamp: float        # unix seconds: when the price was true at the source
    received_at: float      # unix seconds: when the cache stored it (used for staleness)
    source: str             # "simulator" | "massive"

    @property
    def direction(self) -> Direction:
        if self.price > self.previous_price:
            return Direction.UP
        if self.price < self.previous_price:
            return Direction.DOWN
        return Direction.FLAT

    @property
    def change(self) -> float:
        return self.price - self.reference_price

    @property
    def change_percent(self) -> float:
        return (self.change / self.reference_price * 100.0) if self.reference_price else 0.0

    def age(self, now: float) -> float:
        return now - self.received_at

    def to_dict(self) -> dict:
        """Wire format shared by SSE and REST."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "reference_price": self.reference_price,
            "change": round(self.change, 4),
            "change_percent": round(self.change_percent, 4),
            "direction": self.direction.value,
            "timestamp": iso_utc(self.timestamp),
        }


def iso_utc(ts: float) -> str:
    """Unix seconds -> '2026-10-05T14:03:21.512Z'."""
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
