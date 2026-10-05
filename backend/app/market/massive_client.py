"""Thin async client for the few Massive (formerly Polygon.io) endpoints we use."""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import date

import httpx

BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"
GROUPED_DAILY_PATH = "/v2/aggs/grouped/locale/us/market/stocks/{day}"


class MassiveError(Exception):
    """Any non-success response from Massive."""


class MassiveAuthError(MassiveError):
    """401: missing or unknown key. Not retryable."""


class MassiveNotEntitledError(MassiveError):
    """403: the plan does not include this endpoint or recency. Not retryable."""


class MassiveRateLimitError(MassiveError):
    """429: over the per-minute budget (free Basic plan)."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MassiveClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},  # header, not ?apiKey=, keeps it out of logs
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        r = await self._http.get(path, params=params)
        if r.status_code == 200:
            return r.json()
        msg = _error_message(r)
        if r.status_code == 401:
            raise MassiveAuthError(msg)
        if r.status_code == 403:
            raise MassiveNotEntitledError(msg)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After", "")
            raise MassiveRateLimitError(msg, float(ra) if ra.isdigit() else None)
        raise MassiveError(f"HTTP {r.status_code}: {msg}")

    async def get_snapshots(self, tickers: Iterable[str]) -> list[dict]:
        """One call for any number of tickers. Unknown tickers are simply absent."""
        symbols = sorted({t.upper() for t in tickers})
        if not symbols:
            return []
        data = await self._get(SNAPSHOT_PATH, {"tickers": ",".join(symbols)})
        return data.get("tickers") or []

    async def get_grouped_daily(self, day: date) -> list[dict]:
        """One OHLCV bar per US ticker for `day`. Empty on weekends/holidays."""
        data = await self._get(GROUPED_DAILY_PATH.format(day=day.isoformat()), {"adjusted": "true"})
        return data.get("results") or []


def extract_quote(snap: dict) -> tuple[float, float, float | None] | None:
    """(price, unix_ts_seconds, prev_close) from one snapshot entry, or None if unusable.

    Price preference: lastTrade.p -> min.c -> day.c -> prevDay.c (fields vary by plan and time of day).
    """

    def pos(x: object) -> float | None:
        return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 else None

    trade, minute = snap.get("lastTrade") or {}, snap.get("min") or {}
    day, prev = snap.get("day") or {}, snap.get("prevDay") or {}

    price = pos(trade.get("p")) or pos(minute.get("c")) or pos(day.get("c")) or pos(prev.get("c"))
    if price is None:
        return None

    if pos(snap.get("updated")):
        ts = snap["updated"] / 1e9  # ns
    elif pos(trade.get("t")):
        ts = trade["t"] / 1e9       # ns
    elif pos(minute.get("t")):
        ts = minute["t"] / 1e3      # ms
    else:
        ts = time.time()
    return price, ts, pos(prev.get("c"))


def _error_message(r: httpx.Response) -> str:
    try:
        body = r.json()
        return body.get("message") or body.get("error") or r.text
    except ValueError:
        return r.text
