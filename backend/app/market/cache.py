"""In-memory latest-price store: one writer (the active source), many readers."""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from .models import PriceQuote


class PriceCache:
    """Single-threaded (asyncio only), so no locks are needed."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._quotes: dict[str, PriceQuote] = {}
        self._version = 0

    def now(self) -> float:
        """The cache's clock. Staleness checks use this so tests can inject time."""
        return self._clock()

    # ---- writes: only the active MarketDataSource calls these ----
    def update(
        self,
        ticker: str,
        price: float,
        *,
        source: str,
        timestamp: float | None = None,
        reference_price: float | None = None,
    ) -> PriceQuote:
        price = float(price)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"invalid price for {ticker}: {price!r}")  # contract C7
        now = self._clock()
        prev = self._quotes.get(ticker)
        price = round(price, 2)
        if reference_price is None or reference_price <= 0:
            reference_price = prev.reference_price if prev else price
        quote = PriceQuote(
            ticker=ticker,
            price=price,
            previous_price=prev.price if prev else price,
            reference_price=round(float(reference_price), 2),
            timestamp=timestamp if timestamp is not None else now,
            received_at=now,
            source=source,
        )
        self._quotes[ticker] = quote
        self._version += 1
        return quote

    def remove(self, ticker: str) -> None:
        if self._quotes.pop(ticker, None) is not None:
            self._version += 1

    # ---- reads ----
    def get(self, ticker: str) -> PriceQuote | None:
        return self._quotes.get(ticker)

    def get_price(self, ticker: str) -> float | None:
        q = self._quotes.get(ticker)
        return q.price if q else None

    def snapshot(self) -> dict[str, PriceQuote]:
        """Shallow copy; safe to iterate while the source keeps writing."""
        return dict(self._quotes)

    @property
    def version(self) -> int:
        """Increments on every write. SSE compares it to skip unchanged ticks."""
        return self._version

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._quotes

    def __len__(self) -> int:
        return len(self._quotes)
