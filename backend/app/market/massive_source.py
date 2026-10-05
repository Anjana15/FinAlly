"""Massive REST poller: live snapshots on paid plans, end-of-day closes on the free plan."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import (
    MassiveAuthError,
    MassiveClient,
    MassiveError,
    MassiveNotEntitledError,
    MassiveRateLimitError,
    extract_quote,
)
from .models import SourceState, SourceStatus

log = logging.getLogger(__name__)

NEW_YORK = ZoneInfo("America/New_York")
EOD_REFRESH_SECONDS = 30 * 60
EOD_LOOKBACK_DAYS = 5
MIN_BACKOFF, MAX_BACKOFF = 5.0, 60.0


def _yesterday_new_york() -> date:
    return datetime.now(NEW_YORK).date() - timedelta(days=1)


class MassiveDataSource(MarketDataSource):
    name = "massive"

    def __init__(
        self,
        cache: PriceCache,
        client: MassiveClient,
        *,
        poll_interval: float = 5.0,
        today: Callable[[], date] = _yesterday_new_york,  # first EOD day to try; injectable for tests
    ) -> None:
        super().__init__(cache)
        self._client = client
        self._poll_interval = max(1.0, poll_interval)
        self._eod_start = today
        self._tickers: set[str] = set()
        self._missing: set[str] = set()     # tracked tickers the provider returned nothing for
        self._mode = "snapshot"             # -> "eod" after a 403 on snapshots
        self._eod_bars: dict[str, dict] = {}
        self._eod_day: date | None = None
        self._task: asyncio.Task | None = None
        self._fetch_lock = asyncio.Lock()
        self._backoff = 0.0
        self._fatal = False
        self._closed = False
        self._status = SourceStatus(self.name, SourceState.STARTING)

    # ------------------------------------------------------------------ interface
    @property
    def max_quote_age(self) -> float | None:
        return None if self._mode == "eod" else 3 * self._poll_interval + 10

    async def start(self, tickers: Iterable[str]) -> None:
        if self._task:
            return
        self._tickers = set(tickers)
        await self._fetch()  # warm the cache; errors land in status()
        self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if not self._closed:
            self._closed = True
            await self._client.aclose()
        self._status = SourceStatus(self.name, SourceState.STOPPED)

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        self._tickers.add(ticker)
        if self._mode == "eod":
            self._write_eod(ticker)            # free: the whole market is already downloaded
            self._refresh_status()
        elif not self._fatal and self._backoff == 0:
            await self._fetch(only={ticker})   # one extra call; paid plans are unlimited

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._missing.discard(ticker)
        self.cache.remove(ticker)

    def tickers(self) -> frozenset[str]:
        return frozenset(self._tickers)

    def status(self) -> SourceStatus:
        return self._status

    # ------------------------------------------------------------------ internals
    async def _run(self) -> None:
        while not self._fatal:
            delay = self._backoff or (EOD_REFRESH_SECONDS if self._mode == "eod" else self._poll_interval)
            await asyncio.sleep(delay)
            await self._fetch()

    async def _fetch(self, only: set[str] | None = None) -> None:
        async with self._fetch_lock:
            tickers = set(only) if only else set(self._tickers)
            if not tickers or self._fatal:
                return
            try:
                if self._mode == "snapshot":
                    try:
                        await self._fetch_snapshot(tickers)
                    except MassiveNotEntitledError:
                        log.warning("Massive plan lacks snapshot access; switching to end-of-day prices")
                        self._mode = "eod"
                        await self._fetch_eod()
                else:
                    await self._fetch_eod()
                self._backoff = 0.0
                self._refresh_status()
            except MassiveAuthError as e:
                self._fatal = True
                self._set(SourceState.ERROR, f"Invalid MASSIVE_API_KEY ({e})")
            except MassiveRateLimitError as e:
                self._backoff = e.retry_after or 60.0
                self._set(SourceState.DEGRADED, f"Rate limited by Massive; retrying in {self._backoff:.0f}s")
            except (MassiveError, httpx.HTTPError, ValueError) as e:  # ValueError: bad JSON
                self._backoff = min(MAX_BACKOFF, max(MIN_BACKOFF, self._backoff * 2))
                log.warning("Massive fetch failed: %s", e)
                self._set(SourceState.DEGRADED, f"Massive unavailable ({type(e).__name__}); retrying")

    async def _fetch_snapshot(self, tickers: set[str]) -> None:
        seen: set[str] = set()
        for snap in await self._client.get_snapshots(tickers):
            sym = snap.get("ticker")
            quote = extract_quote(snap)
            if sym not in self._tickers or quote is None:  # removed mid-flight, or unusable row
                continue
            price, ts, prev_close = quote
            self.cache.update(sym, price, source=self.name, timestamp=ts, reference_price=prev_close)
            seen.add(sym)
        self._missing = (self._missing - seen) | (tickers - seen)

    async def _fetch_eod(self) -> None:
        day = self._eod_start()
        for _ in range(EOD_LOOKBACK_DAYS):  # step back over weekends and holidays
            rows = await self._client.get_grouped_daily(day)
            if rows:
                self._eod_bars = {r["T"]: r for r in rows if r.get("T")}
                self._eod_day = day
                break
            day -= timedelta(days=1)
        else:
            raise MassiveError(f"no end-of-day data in the {EOD_LOOKBACK_DAYS} days up to {self._eod_start()}")
        for t in self._tickers:
            self._write_eod(t)

    def _write_eod(self, ticker: str) -> None:
        bar = self._eod_bars.get(ticker)
        close = bar.get("c") if bar else None
        if not isinstance(close, (int, float)) or close <= 0:
            self._missing.add(ticker)
            return
        self._missing.discard(ticker)
        ts = bar.get("t")
        self.cache.update(
            ticker, close, source=self.name,
            timestamp=ts / 1000 if ts else None,
            reference_price=bar.get("o"),  # EOD "change %" = that session's open-to-close move
        )

    def _refresh_status(self) -> None:
        notes = []
        if self._mode == "eod":
            notes.append(f"Massive plan has no live snapshots; showing end-of-day closes from {self._eod_day}")
        if self._missing:
            notes.append(f"No data for: {', '.join(sorted(self._missing))}")
        state = SourceState.DEGRADED if self._mode == "eod" else SourceState.OK
        self._set(state, "; ".join(notes) or None)

    def _set(self, state: SourceState, message: str | None) -> None:
        produced = state in (SourceState.OK, SourceState.DEGRADED) and self._backoff == 0
        last = self.cache.now() if produced else self._status.last_success
        self._status = SourceStatus(self.name, state, message, last)
