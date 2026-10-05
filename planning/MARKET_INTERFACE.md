# Market Data Interface — Unified Python API

This is the design for the backend's market-data layer: one abstract interface with two implementations (the **simulator** and the **Massive** poller). Which one runs depends on `MASSIVE_API_KEY`. Everything downstream (SSE, trades, portfolio valuation, snapshots, the LLM context) reads prices from one **`PriceCache`** and never knows which source produced them.

Related docs: `MASSIVE_API.md` (provider endpoints and plan limits), `MARKET_SIMULATOR.md` (simulation maths and code), `PLAN.md` §6, `REVIEW.md` §§2, 5, 6.

---

## 1. Goals & rules

1. **One writer, many readers.** Exactly one background task (the active source) writes to the cache. SSE, trade execution, `/api/portfolio`, `/api/watchlist`, the 30 s snapshot task and the chat context only read it.
2. **Source-agnostic consumers.** No module outside `app/market/` imports the simulator or the Massive client.
3. **Selection by environment.** If `MASSIVE_API_KEY` is non-empty after stripping whitespace, use Massive. Otherwise use the simulator. Selection happens once, at startup.
4. **Never silently mix real and simulated prices.** If Massive is configured but failing, report it through `status()`. Don't fall back to the simulator.
5. **Tracked tickers = watchlist ∪ open positions.** The app layer tells the source which tickers to track. Removing a ticker from the watchlist must not stop pricing a held position.
6. **Single process.** The cache lives in memory, so run uvicorn with **one worker**. Start the source in the FastAPI lifespan, after DB init, and stop it on shutdown.
7. **Testable.** Sources take the cache, a clock and an RNG or HTTP transport as constructor arguments. Nothing reads env vars except the factory.

---

## 2. Module layout

```
backend/app/market/
├── __init__.py          # re-exports: PriceCache, PriceQuote, MarketDataSource, create_market_data_source, ...
├── models.py            # PriceQuote, Direction, SourceState, SourceStatus
├── cache.py             # PriceCache (in-memory, versioned)
├── interface.py         # MarketDataSource ABC, normalize_ticker, PriceUnavailable
├── simulator.py         # GBMSimulator (pure maths) + SimulatorDataSource   → see MARKET_SIMULATOR.md
├── seed_prices.py       # seed price / volatility / sector table              → see MARKET_SIMULATOR.md
├── massive_client.py    # MassiveClient (httpx) + extract_quote              → see MASSIVE_API.md §8
├── massive_source.py    # MassiveDataSource (poller, EOD fallback)
├── factory.py           # create_market_data_source(cache, env)
└── tracking.py          # sync_tracked_tickers(), price_for_trade()
```

Dependencies: `httpx` (runtime, for Massive). Tests also need `pytest` and `pytest-asyncio`. The simulator uses only the standard library.

---

## 3. Data model (`models.py`)

```python
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
    DEGRADED = "degraded"   # running, but data is limited (EOD-only plan, rate-limited, transient errors)
    ERROR = "error"         # not producing data (invalid key); needs operator action
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class SourceStatus:
    source: str                     # "simulator" | "massive"
    state: SourceState
    message: str | None = None      # human-readable, safe to show in the UI
    last_success: float | None = None  # unix seconds of last successful update

    def to_dict(self) -> dict:
        return {"source": self.source, "state": self.state.value, "message": self.message}


@dataclass(frozen=True, slots=True)
class PriceQuote:
    ticker: str
    price: float              # latest price, rounded to cents
    previous_price: float     # price before this update (== price on first sighting)
    reference_price: float    # basis for change %: previous close (Massive) or seed price (simulator)
    timestamp: float          # unix seconds: when the price was true at the source
    received_at: float        # unix seconds: when the cache stored it (used for staleness)
    source: str               # "simulator" | "massive"

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
        """Wire format used by SSE and REST (see §8)."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "reference_price": self.reference_price,
            "change": round(self.change, 4),
            "change_percent": round(self.change_percent, 4),
            "direction": self.direction.value,
            "timestamp": _iso(self.timestamp),
        }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
```

Notes:

- `previous_price` is **the price before this update**. If a Massive poll returns the same price as before, `direction` is `flat` and the frontend doesn't flash (REVIEW §13 item 22).
- `reference_price` answers "change % since what?" (PLAN §13 item 5). For Massive it's `prevDay.c`, which gives a true daily change. For the simulator it's the seed price, i.e. the change since the backend started. The UI label should read "Change %".
- Staleness uses `received_at`, not `timestamp`. A 15-minute-delayed quote has an old `timestamp` even when we just confirmed it.

---

## 4. Price cache (`cache.py`)

```python
from __future__ import annotations

import time
from collections.abc import Callable

from .models import PriceQuote


class PriceCache:
    """In-memory latest-price store. Single-threaded (asyncio); no locks needed."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._quotes: dict[str, PriceQuote] = {}
        self._version = 0

    # ---- writes (only the active MarketDataSource calls these) ----
    def update(
        self,
        ticker: str,
        price: float,
        *,
        source: str,
        timestamp: float | None = None,
        reference_price: float | None = None,
    ) -> PriceQuote:
        now = self._clock()
        prev = self._quotes.get(ticker)
        price = round(float(price), 2)
        quote = PriceQuote(
            ticker=ticker,
            price=price,
            previous_price=prev.price if prev else price,
            reference_price=reference_price or (prev.reference_price if prev else price),
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
        """Shallow copy; safe to iterate while sources keep writing."""
        return dict(self._quotes)

    @property
    def version(self) -> int:
        """Increments on every write. SSE compares it to skip unchanged ticks."""
        return self._version

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._quotes

    def __len__(self) -> int:
        return len(self._quotes)
```

Prices are rounded to cents when stored, so all consumers see the same number. Sources keep their own full-precision state (the simulator's GBM path is never rounded).

---

## 5. The interface (`interface.py`)

```python
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable

from .cache import PriceCache
from .models import SourceStatus

TICKER_RE = re.compile(r"^[A-Z][A-Z.]{0,5}$")


def normalize_ticker(raw: str) -> str:
    """Upper-case and validate format. Raises ValueError. Format-valid ≠ exists (REVIEW item 8)."""
    t = raw.strip().upper()
    if not TICKER_RE.fullmatch(t):
        raise ValueError(f"invalid ticker symbol: {raw!r}")
    return t


class PriceUnavailable(Exception):
    """Raised by price_for_trade(). `code` goes into API / chat error payloads."""

    def __init__(self, ticker: str, code: str, message: str) -> None:
        super().__init__(message)
        self.ticker, self.code = ticker, code   # code: "no_price" | "stale_price"


class MarketDataSource(ABC):
    """A producer of live prices that writes into a PriceCache.

    Lifecycle: construct → await start(tickers) → add/remove tickers at runtime → await stop().
    """

    name: str                       # "simulator" | "massive"
    max_quote_age: float | None     # seconds a quote stays tradable; None = no limit

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin tracking `tickers` and spawn the background task.

        Must make a best-effort attempt to populate the cache for every ticker before
        returning (simulator: always; Massive: one fetch, errors go into status()).
        Must not raise for provider errors. Calling start() twice is a no-op.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task, await it, release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Start tracking a (normalized) ticker. Idempotent.

        Returns after a best-effort attempt to price it, so a trade right after
        add_ticker() can usually execute.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and drop it from the cache. Idempotent."""

    @abstractmethod
    def tickers(self) -> frozenset[str]:
        """Currently tracked tickers."""

    @abstractmethod
    def status(self) -> SourceStatus:
        """Health of the source, surfaced to the UI via SSE and /api/health."""
```

### Behavioural contract (both implementations; enforced by a shared test suite)

| # | Rule |
|---|---|
| C1 | After `await start(["AAPL", …])` with a healthy source, `cache.get("AAPL")` is not `None`. |
| C2 | Only tracked tickers are written to the cache. `remove_ticker(t)` removes `t` from the cache. |
| C3 | `add_ticker` / `remove_ticker` / `start` / `stop` are idempotent. |
| C4 | The background task never dies on a provider error. Errors are caught, logged and shown in `status()`. |
| C5 | `stop()` leaves no running tasks. Afterwards `status().state == STOPPED`. |
| C6 | Every write goes through `cache.update(..., source=self.name)`. |
| C7 | Prices are finite and > 0. Bad provider rows are skipped, never written. |

Tests in `backend/tests/market/test_contract.py` are parametrized over `[simulator, massive-with-MockTransport]`.

---

## 6. Implementations

### 6.1 `SimulatorDataSource` (default)

The full design is in **MARKET_SIMULATOR.md**. Summary:

- `name = "simulator"`, `max_quote_age = 5.0`.
- Ticks every 0.5 s. Each tick advances a correlated GBM for all tracked tickers and writes every price to the cache.
- `start()` and `add_ticker()` write the seed price into the cache immediately, so new tickers are tradable at once.
- Status is always `OK` while running.
- Constructor: `SimulatorDataSource(cache, *, seed: int | None = None, tick_interval: float = 0.5, clock=time.time)`.

### 6.2 `MassiveDataSource` (`massive_source.py`)

- `name = "massive"`.
- **Snapshot mode** (paid plans): one `GET /v2/snapshot/...?tickers=…` per `poll_interval` (default 5 s) for every tracked ticker. `max_quote_age = 3 × poll_interval + 10`.
- **EOD mode** (free Basic plan, detected from a 403 on the snapshot): loads the latest grouped-daily bars (one call covers *all* US tickers, so tickers added later are priced without another call) and refreshes every 30 min. `max_quote_age = None`, because the prices are end-of-day by definition and that is stated in `status()`.
- 401 → `ERROR`, polling stops. 429 → wait `Retry-After` or 60 s. Other errors → exponential backoff (5 s → 60 s), `DEGRADED`.

```python
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from datetime import date, timedelta

import httpx

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import (
    MassiveAuthError, MassiveClient, MassiveError, MassiveNotEntitledError,
    MassiveRateLimitError, extract_quote,
)
from .models import SourceState, SourceStatus

log = logging.getLogger(__name__)

EOD_REFRESH_SECONDS = 30 * 60
MAX_BACKOFF = 60.0


class MassiveDataSource(MarketDataSource):
    name = "massive"

    def __init__(
        self,
        cache: PriceCache,
        client: MassiveClient,
        *,
        poll_interval: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(cache)
        self._client = client
        self._poll_interval = max(1.0, poll_interval)
        self._clock = clock
        self._tickers: set[str] = set()
        self._mode = "snapshot"                     # or "eod"
        self._eod_bars: dict[str, dict] = {}        # full-market grouped daily, keyed by ticker
        self._eod_day: date | None = None
        self._task: asyncio.Task | None = None
        self._fetch_lock = asyncio.Lock()
        self._backoff = 0.0
        self._fatal = False
        self._status = SourceStatus(self.name, SourceState.STARTING)

    # ---------------------------------------------------------------- interface
    @property
    def max_quote_age(self) -> float | None:
        return None if self._mode == "eod" else 3 * self._poll_interval + 10

    async def start(self, tickers: Iterable[str]) -> None:
        if self._task:
            return
        self._tickers = set(tickers)
        await self._fetch()                                  # warm the cache
        self._task = asyncio.create_task(self._run(), name="massive-poller")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._client.aclose()
        self._status = SourceStatus(self.name, SourceState.STOPPED)

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        self._tickers.add(ticker)
        if self._mode == "eod" and ticker in self._eod_bars:
            self._write_eod(ticker)                        # free: already downloaded
        elif self._mode == "snapshot" and not self._fatal and self._backoff == 0:
            await self._fetch(only={ticker})               # one extra call (paid plans: unlimited)

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self.cache.remove(ticker)

    def tickers(self) -> frozenset[str]:
        return frozenset(self._tickers)

    def status(self) -> SourceStatus:
        return self._status

    # ---------------------------------------------------------------- internals
    async def _run(self) -> None:
        while not self._fatal:
            delay = self._backoff or (EOD_REFRESH_SECONDS if self._mode == "eod" else self._poll_interval)
            await asyncio.sleep(delay)
            await self._fetch()

    async def _fetch(self, only: set[str] | None = None) -> None:
        tickers = set(only or self._tickers)
        if not tickers or self._fatal:
            return
        async with self._fetch_lock:
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
            except MassiveAuthError as e:
                self._fatal = True
                self._set(SourceState.ERROR, f"Invalid MASSIVE_API_KEY: {e}")
            except MassiveRateLimitError as e:
                self._backoff = e.retry_after or 60.0
                self._set(SourceState.DEGRADED, f"Rate limited by Massive; retrying in {self._backoff:.0f}s")
            except (MassiveError, httpx.HTTPError) as e:
                self._backoff = min(MAX_BACKOFF, max(5.0, self._backoff * 2))
                log.warning("Massive fetch failed: %s", e)
                self._set(SourceState.DEGRADED, f"Massive unavailable ({type(e).__name__}); retrying")

    async def _fetch_snapshot(self, tickers: set[str]) -> None:
        seen: set[str] = set()
        for snap in await self._client.get_snapshots(tickers):
            sym = snap.get("ticker")
            quote = extract_quote(snap)
            if sym not in self._tickers or quote is None:
                continue
            price, ts, prev_close = quote
            self.cache.update(sym, price, source=self.name, timestamp=ts, reference_price=prev_close)
            seen.add(sym)
        missing = tickers - seen
        self._set(SourceState.OK, f"No data for: {', '.join(sorted(missing))}" if missing else None)

    async def _fetch_eod(self) -> None:
        day = date.today() - timedelta(days=1)
        for _ in range(5):                                   # step back over weekends/holidays
            rows = await self._client.get_grouped_daily(day)
            if rows:
                self._eod_bars = {r["T"]: r for r in rows if r.get("T")}
                self._eod_day = day
                break
            day -= timedelta(days=1)
        else:
            raise MassiveError("no end-of-day data found in the last 5 days")
        for t in self._tickers:
            self._write_eod(t)
        self._set(SourceState.DEGRADED,
                  f"Massive plan has no live snapshots; showing end-of-day closes from {self._eod_day}")

    def _write_eod(self, ticker: str) -> None:
        bar = self._eod_bars.get(ticker)
        if bar and bar.get("c", 0) > 0:
            self.cache.update(ticker, bar["c"], source=self.name,
                              timestamp=bar.get("t", 0) / 1000 or None, reference_price=bar.get("o"))

    def _set(self, state: SourceState, message: str | None) -> None:
        ok = state in (SourceState.OK, SourceState.DEGRADED)
        self._status = SourceStatus(self.name, state, message,
                                    self._clock() if ok else self._status.last_success)
```

In EOD mode `reference_price` is the day's open, so "change %" shows that session's open-to-close move. If we want close-vs-previous-close there instead, fetch two grouped-daily days (still ≤ 10 calls per 30 min).

---

## 7. Factory (`factory.py`)

```python
from __future__ import annotations

import os
from collections.abc import Mapping

from .cache import PriceCache
from .interface import MarketDataSource


def create_market_data_source(
    cache: PriceCache, env: Mapping[str, str] = os.environ
) -> MarketDataSource:
    api_key = (env.get("MASSIVE_API_KEY") or "").strip()
    if api_key:
        from .massive_client import MassiveClient
        from .massive_source import MassiveDataSource

        interval = float(env.get("MASSIVE_POLL_INTERVAL") or 5.0)
        return MassiveDataSource(cache, MassiveClient(api_key), poll_interval=interval)

    from .simulator import SimulatorDataSource

    seed = env.get("SIMULATOR_SEED")
    return SimulatorDataSource(cache, seed=int(seed) if seed else None)
```

| Env var | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | Non-empty → Massive; empty → simulator |
| `MASSIVE_POLL_INTERVAL` | `5` | Seconds between snapshot polls (paid plans) |
| `SIMULATOR_SEED` | unset | Integer → reproducible simulator prices (E2E tests set this) |

Add the two optional vars to `.env.example`, commented out.

---

## 8. How consumers use it

### 8.1 Lifespan wiring (`app/main.py`)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source
from app.db import init_db, tracked_tickers   # tracked_tickers(): watchlist ∪ positions for "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                      # lazy schema + seed; must finish first
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())
    app.state.prices, app.state.market = cache, source
    # ... start the 30 s portfolio snapshot task here (it reads app.state.prices)
    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
```

### 8.2 Keeping tracked tickers in sync (`tracking.py`)

Call this after any watchlist change and after every trade, whether manual or from the LLM:

```python
async def sync_tracked_tickers(source: MarketDataSource, wanted: set[str]) -> None:
    current = source.tickers()
    for t in sorted(wanted - current):
        await source.add_ticker(t)
    for t in sorted(current - wanted):
        await source.remove_ticker(t)
```

### 8.3 Trade execution price (`tracking.py`)

Manual and LLM trades share this lookup, so both validation paths behave the same:

```python
import time

def price_for_trade(cache: PriceCache, source: MarketDataSource, ticker: str) -> PriceQuote:
    quote = cache.get(ticker)
    if quote is None:
        raise PriceUnavailable(ticker, "no_price", f"No price available for {ticker} yet")
    max_age = source.max_quote_age
    if max_age is not None and quote.age(time.time()) > max_age:
        raise PriceUnavailable(ticker, "stale_price", f"Price for {ticker} is stale; try again shortly")
    return quote
```

For a trade on a ticker that isn't tracked yet: `await source.add_ticker(t)` first (the plan auto-adds bought tickers to the watchlist), then call `price_for_trade`.

### 8.4 SSE stream (`GET /api/stream/prices`)

Each event is **one unnamed `data:` message holding a full snapshot** of all tracked tickers plus the source status (REVIEW §13 items 2 and 29). Full snapshots make reconnects and removals trivial: the client replaces its state on every event. Events are sent only when the cache version or the status changes. A comment keep-alive goes out every 15 s.

```python
import asyncio, json, time
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    cache, source = request.app.state.prices, request.app.state.market

    async def events():
        yield "retry: 3000\n\n"
        last_key, last_sent = None, 0.0
        while not await request.is_disconnected():
            status = source.status()
            key = (cache.version, status)
            now = time.monotonic()
            if key != last_key:
                payload = {
                    "type": "prices",
                    "source": status.to_dict(),
                    "quotes": {t: q.to_dict() for t, q in cache.snapshot().items()},
                }
                yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
                last_key, last_sent = key, now
            elif now - last_sent >= 15:
                yield ": keep-alive\n\n"
                last_sent = now
            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Example event payload:

```json
{
  "type": "prices",
  "source": {"source": "simulator", "state": "ok", "message": null},
  "quotes": {
    "AAPL": {"ticker": "AAPL", "price": 190.42, "previous_price": 190.37, "reference_price": 190.0,
             "change": 0.42, "change_percent": 0.2211, "direction": "up",
             "timestamp": "2026-10-05T14:03:21.512Z"}
  }
}
```

Frontend rules: flash only when `direction !== "flat"`; append to sparklines only when `price` changes; show `source.message` (e.g. the EOD notice) next to the connection dot.

### 8.5 Other readers

- `/api/watchlist`, `/api/portfolio`: `cache.get(t)` per row. If it's `None`, return `price: null` and let the UI show "—". Don't value unpriced positions at 0 (REVIEW §2).
- 30 s snapshot task: `cache.snapshot()`. Skip or flag tickers with no quote.
- LLM context: `{t: q.to_dict() for t, q in cache.snapshot().items()}` plus `source.status().to_dict()`.
- `/api/health`: include `source.status().to_dict()`.

---

## 9. Testing plan

| Test | What it checks |
|---|---|
| `test_cache.py` | `update` sets `previous_price`/`reference_price` correctly; version increments; `remove`; rounding to cents |
| `test_models.py` | `direction`, `change_percent` (including reference 0), ISO timestamp format |
| `test_factory.py` | Empty, whitespace or missing key → simulator; key → Massive; `SIMULATOR_SEED` parsed |
| `test_contract.py` | C1–C7, parametrized over both sources (Massive via `httpx.MockTransport`) |
| `test_massive_source.py` | `extract_quote` fallbacks; unknown ticker in status; 403 → EOD mode; 401 → ERROR and polling stops; 429 → backoff; EOD add_ticker without a new request |
| `test_simulator.py` | See MARKET_SIMULATOR.md §8 |
| `test_tracking.py` | `sync_tracked_tickers` diffing; `price_for_trade` no_price / stale_price / ok with an injected clock |
| `test_sse.py` | First event has all quotes; no event without a version change; keep-alive |

Use injected clocks and seeds. No test sleeps in real time for more than a tick.
