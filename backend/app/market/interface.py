"""The abstract market-data source and the helpers every consumer shares."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache
from .models import SourceStatus

TICKER_RE = re.compile(r"^[A-Z][A-Z.]{0,5}$")


def normalize_ticker(raw: str) -> str:
    """Upper-case and validate the format. Raises ValueError. Format-valid does not mean it exists."""
    t = raw.strip().upper()
    if not TICKER_RE.fullmatch(t):
        raise ValueError(f"invalid ticker symbol: {raw!r}")
    return t


class PriceUnavailable(Exception):
    """Raised by price_for_trade(). `code` goes into API and chat error payloads."""

    def __init__(self, ticker: str, code: str, message: str) -> None:
        super().__init__(message)
        self.ticker = ticker
        self.code = code  # "no_price" | "stale_price"


class MarketDataSource(ABC):
    """A producer of live prices that writes into a PriceCache.

    Lifecycle: construct -> await start(tickers) -> add/remove tickers -> await stop().
    """

    name: str  # "simulator" | "massive"

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @property
    @abstractmethod
    def max_quote_age(self) -> float | None:
        """Seconds a quote stays tradable. None = no limit (e.g. end-of-day data)."""

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Track `tickers` and spawn the background task.

        Makes a best-effort attempt to price every ticker before returning.
        Never raises for provider errors (they go into status()). A second call is a no-op.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task, await it, release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Track a normalized ticker. Idempotent. Best-effort prices it before returning."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and drop it from the cache. Idempotent."""

    @abstractmethod
    def tickers(self) -> frozenset[str]:
        """Currently tracked tickers."""

    @abstractmethod
    def status(self) -> SourceStatus:
        """Health of the source, shown in the UI via SSE and /api/health."""
