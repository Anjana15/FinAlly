# Market Data Backend — Implementation Design

This is the **build document** for FinAlly's market-data layer. It brings together the three research docs (`MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, `MASSIVE_API.md`), settles the open market-data items from `PLAN.md` §13 and `REVIEW.md`, and gives complete code for every module:

- the unified API: models, price cache, abstract source, factory, tracking helpers, SSE endpoint
- the GBM simulator, which is the default source
- the Massive (Polygon.io) REST poller

**Status of the code:** every Python listing below was run as a package (`app/market/…`) under Python 3.11 with FastAPI, httpx, pytest and pytest-asyncio. The test suite in §12 and Appendix A passed in full (59 tests). The Massive tests use `httpx.MockTransport`; no listing has been run against the live Massive API. Copy the files as they are into `backend/app/market/` and `backend/tests/market/`.

Where this doc differs from the earlier three, **this doc wins**. §14 lists the differences.

---

## 1. Requirements recap

| Source | Requirement |
|---|---|
| PLAN §6 | One interface, two implementations. `MASSIVE_API_KEY` non-empty → Massive, otherwise the simulator. Downstream code doesn't know which one is running. |
| PLAN §6 | Simulator: GBM, ~500 ms ticks, correlated moves, random 2–5 % events, realistic seed prices, in-process. |
| PLAN §6 | Massive: REST polling of watched tickers. The response is normalized to the same format as the simulator's. |
| PLAN §6 | One background writer → in-memory cache (latest price, previous price, timestamp). SSE reads only from the cache. |
| PLAN §6/§8 | `GET /api/stream/prices`: SSE at a ~500 ms cadence, with ticker, price, previous price, timestamp and direction. |
| PLAN §13 #2, #29 | Define the SSE format and batch it per tick. |
| PLAN §13 #5 | "Change %" needs a defined reference price. |
| PLAN §13 #7, REVIEW §2 | Tracked tickers = watchlist ∪ open positions. A held ticker keeps its price after it's removed from the watchlist. |
| PLAN §13 #8 | Seed prices for unknown tickers. Ticker format validation. Reject trades with no price. |
| PLAN §13 #22 | Massive cadence is slower than SSE. Flash only when the price actually changes. |
| PLAN §13 #33 | Use a sector-factor correlation model, not Cholesky. |
| REVIEW §2 | Staleness rules. Never silently fall back from real to simulated prices. |
| REVIEW §6 | Request budget, backoff, timeouts, a visible degraded state. |
| REVIEW §7 | Single worker. Lifespan start/stop. Cancel background tasks on shutdown. |
| REVIEW (acceptance) | Fixed simulator seed, injected clock and mock provider, so tests are reproducible. |

---

## 2. Architecture

```
                    ┌──────────────────────────── app/market ────────────────────────────┐
  env ──► factory ──┤                                                                     │
                    │   ┌─────────────────────┐        ┌────────────────────────────┐     │
                    │   │ SimulatorDataSource │   or   │ MassiveDataSource          │     │
                    │   │  GBMSimulator (pure)│        │  MassiveClient (httpx)     │     │
                    │   │  500 ms loop        │        │  snapshot poll / EOD mode  │     │
                    │   └─────────┬───────────┘        └──────────────┬─────────────┘     │
                    │             │  cache.update(...)   (one writer) │                   │
                    │             ▼                                   ▼                   │
                    │        ┌──────────────────────────────────────────────┐            │
                    │        │ PriceCache  {ticker: PriceQuote}, version    │            │
                    │        └──────────────────────────────────────────────┘            │
                    └──────────────┬────────────┬─────────────┬────────────┬──────────────┘
                                   │ read       │ read        │ read       │ read
                         SSE /api/stream   trade service   portfolio /   30 s snapshot task,
                         /prices           (price_for_     watchlist     LLM context,
                                           trade)          REST          /api/health
```

Rules:

1. **One writer, many readers.** Only the active source calls `cache.update` and `cache.remove`.
2. **Consumers import only from `app.market`** (the package `__init__`). No module outside `app/market/` imports `simulator` or `massive_*`.
3. **The source is selected once, at startup**, by `create_market_data_source`. That factory is the only code that reads market-data env vars.
4. **No silent fallback.** If Massive is configured and failing, `status()` says so. The simulator is never swapped in.
5. **Tracked = watchlist ∪ open positions.** The app tells the source the tracked set with `sync_tracked_tickers`.
6. **Single process, single event loop.** Run uvicorn with one worker. Everything is asyncio on that loop, so no locks are needed around the cache.
7. **Everything is injectable.** The cache takes a clock, the simulator takes a seed or engine, the Massive client takes an httpx transport, and the Massive source takes a "today" function.

---

## 3. Module layout & dependencies

```
backend/
├── pyproject.toml
├── app/
│   ├── main.py                 # lifespan wiring (§11)
│   └── market/
│       ├── __init__.py         # public API re-exports
│       ├── models.py           # Direction, SourceState, SourceStatus, PriceQuote
│       ├── cache.py            # PriceCache
│       ├── interface.py        # MarketDataSource ABC, normalize_ticker, PriceUnavailable
│       ├── seed_prices.py      # TickerProfile, SEED_PROFILES, correlation weights, profile_for
│       ├── simulator.py        # GBMSimulator + SimulatorDataSource
│       ├── massive_client.py   # MassiveClient, errors, extract_quote
│       ├── massive_source.py   # MassiveDataSource
│       ├── factory.py          # create_market_data_source
│       ├── tracking.py         # sync_tracked_tickers, price_for_trade
│       └── sse.py              # GET /api/stream/prices
└── tests/market/
    ├── conftest.py
    ├── test_contract.py
    ├── test_cache_models.py
    ├── test_simulator.py
    ├── test_massive.py
    └── test_tracking_factory_sse.py
```

Dependencies (`backend/pyproject.toml`). The simulator needs only the standard library. httpx is used only by the Massive path.

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

`massive_source.py` uses `zoneinfo`. Add the `tzdata` package to the dependencies (`uv add tzdata`) so `ZoneInfo("America/New_York")` works whether or not the slim base image has system time-zone data. Without any tz data it raises at import time.

Public API (`__init__.py`):

```python
"""Market data: one PriceCache, one active MarketDataSource. Consumers import only from here."""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource, PriceUnavailable, normalize_ticker
from .models import Direction, PriceQuote, SourceState, SourceStatus
from .tracking import price_for_trade, sync_tracked_tickers

__all__ = [
    "Direction",
    "MarketDataSource",
    "PriceCache",
    "PriceQuote",
    "PriceUnavailable",
    "SourceState",
    "SourceStatus",
    "create_market_data_source",
    "normalize_ticker",
    "price_for_trade",
    "sync_tracked_tickers",
]
```

---

## 4. Data model — `models.py`

```python
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
```

Field semantics:

| Field | Simulator | Massive (snapshot) | Massive (EOD mode) |
|---|---|---|---|
| `price` | GBM price, rounded to cents | `lastTrade.p` → `min.c` → `day.c` → `prevDay.c` | grouped-daily close `c` |
| `previous_price` | price at the previous tick | price at the previous poll (often equal → `flat`) | previous refresh |
| `reference_price` | first price this run (seed, or resumed price) | `prevDay.c`, i.e. a true daily change | that session's open `o` |
| `timestamp` | now | `updated` (ns) / `lastTrade.t` / `min.t` | bar `t` (ms) |
| `received_at` | now | now | now |

- **Change % reference (PLAN §13 #5):** this is `reference_price`. The UI label should read **"Change %"**, because for the simulator it means "since the backend started".
- **Staleness uses `received_at`, not `timestamp`.** A 15-minute-delayed quote that was just confirmed is fresh for our purposes.
- **`direction`** compares the price with `previous_price`. A Massive poll that returns an unchanged price is `flat`, and the frontend doesn't flash it (PLAN §13 #22).

---

## 5. Price cache — `cache.py`

```python
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
```

Usage:

```python
cache = PriceCache()
cache.update("AAPL", 190.0, source="simulator", reference_price=190.0)
q = cache.update("AAPL", 190.123, source="simulator")
q.price, q.previous_price, q.direction, q.reference_price   # (190.12, 190.0, 'up', 190.0)
cache.get("AAPL").to_dict()["change_percent"]               # 0.0632
cache.version                                               # 2
```

Design notes:

- Prices are **rounded to cents when stored**, so every reader sees the same number. Sources keep their own full-precision state.
- `reference_price=None` (or ≤ 0) **carries the previous reference forward**. The first write sets it to the price itself.
- `update` **rejects non-finite or ≤ 0 prices** with `ValueError`. This is contract C7, enforced in one place. The sources catch bad rows before calling it, so a `ValueError` here means there's a bug.
- `version` lets SSE skip frames when nothing changed, without diffing quotes.
- `now()` exposes the injected clock. `price_for_trade` uses it so staleness tests need no sleeps.

---

## 6. The unified interface — `interface.py`

```python
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
```

### Behavioural contract (tested against both implementations in `test_contract.py`)

| # | Rule |
|---|---|
| C1 | After `await start([...])` with a healthy provider, every requested ticker is in the cache. |
| C2 | Only tracked tickers are in the cache. `remove_ticker(t)` removes `t` from the cache. |
| C3 | `start`, `stop`, `add_ticker` and `remove_ticker` are idempotent. |
| C4 | The background task never dies from a provider or tick error. Errors are logged and reflected in `status()`. |
| C5 | `stop()` leaves no running tasks, and afterwards `status().state == STOPPED`. |
| C6 | Every cache write is tagged `source=self.name`. |
| C7 | Prices are finite and > 0. Unusable provider rows are skipped. |

### Ticker validation

`normalize_ticker` checks format only: an upper-case letter followed by up to 5 more letters or dots (`AAPL`, `BRK.B`, `V`). The API layer calls it on every user- or LLM-supplied symbol **before** it reaches the DB or the source.

- **Simulator mode:** any format-valid symbol is accepted and gets a deterministic synthetic price (§7.3).
- **Massive mode:** a symbol that doesn't exist is silently absent from the snapshot response. It stays in the watchlist with `price: null`, and `status().message` lists it ("No data for: ZZZZ"). Trades on it fail with `no_price`.

---

## 7. Simulator

### 7.1 Model

For each ticker *i*, each tick of length Δt (in years):

```
Zᵢ          = a·M + b_k·S_k(i) + √(1 − a² − b_k²)·εᵢ            M, S_k, εᵢ ~ N(0,1) independent
log_return  = (μᵢ − ½σᵢ²)·Δt + σᵢ·√Δt·Zᵢ   [+ log(1 ± m) with prob p, m ~ U(2 %, 5 %)]
Sᵢ         ← Sᵢ · exp(log_return)
```

- This is the **exact GBM solution**, so prices stay positive and the step has no Euler error. Var(Zᵢ) = 1, so σᵢ keeps its meaning.
- **Correlation:** a = 0.5 and b = 0.5 give 0.50 within a sector and 0.25 across sectors. The `other` sector (unknown tickers) has b = 0.
- **Time compression:** `time_scale = 30` (1 real second = 30 market seconds), so Δt = 0.5 × 30 / 5,896,800 ≈ 2.5 × 10⁻⁶ years. At σ = 25 % that's about 0.04 % per tick, or ~8¢ on AAPL. Moves are visible on every tick without prices running away. Typical moves: 0.44 % per minute and 3.4 % per hour at σ = 25 %.
- **Events:** p = 0.001 per ticker per tick. That's one event per ticker every ~8 minutes, or about one every 50 s across the 10 default tickers.
- **Determinism:** one `random.Random(seed)`, and draws happen in a fixed order (market, then sorted sectors, then sorted tickers). Same seed plus the same add/remove/step sequence gives identical prices.

### 7.2 Seed table — `seed_prices.py`

```python
"""Seed prices, volatilities and sectors for the simulator."""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerProfile:
    price: float         # starting price, USD
    volatility: float    # annualized sigma (0.25 = 25 %)
    drift: float = 0.05  # annualized mu
    sector: str = "other"


# Approximate, illustrative levels. They only need to look plausible.
SEED_PROFILES: dict[str, TickerProfile] = {
    "AAPL":  TickerProfile(190.00, 0.25, sector="tech"),
    "GOOGL": TickerProfile(175.00, 0.30, sector="tech"),
    "MSFT":  TickerProfile(420.00, 0.25, sector="tech"),
    "AMZN":  TickerProfile(185.00, 0.32, sector="tech"),
    "META":  TickerProfile(500.00, 0.38, sector="tech"),
    "NFLX":  TickerProfile(650.00, 0.40, sector="tech"),
    "NVDA":  TickerProfile(120.00, 0.50, sector="growth"),
    "TSLA":  TickerProfile(250.00, 0.55, sector="growth"),
    "JPM":   TickerProfile(200.00, 0.22, sector="finance"),
    "V":     TickerProfile(275.00, 0.20, sector="finance"),
}

MARKET_WEIGHT = 0.5  # a: cross-sector correlation = a^2
SECTOR_WEIGHTS: dict[str, float] = {  # b_k: same-sector correlation = a^2 + b_k^2; need a^2 + b^2 <= 1
    "tech": 0.5,
    "growth": 0.5,
    "finance": 0.5,
    "other": 0.0,
}


def profile_for(ticker: str, seed: int | None = None) -> TickerProfile:
    """Seed-table profile, or a deterministic pseudo-random one for unknown tickers.

    crc32 rather than hash(): str hashes are randomized per process.
    """
    if ticker in SEED_PROFILES:
        return SEED_PROFILES[ticker]
    rng = random.Random(zlib.crc32(f"{seed}:{ticker}".encode()))
    return TickerProfile(
        price=round(rng.uniform(50.0, 300.0), 2),
        volatility=round(rng.uniform(0.25, 0.45), 3),
        sector="other",
    )
```

### 7.3 Engine and data source — `simulator.py`

```python
"""Default price source: correlated GBM with random jump events."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .cache import PriceCache
from .interface import MarketDataSource
from .models import SourceState, SourceStatus
from .seed_prices import MARKET_WEIGHT, SECTOR_WEIGHTS, TickerProfile, profile_for

log = logging.getLogger(__name__)

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
MIN_PRICE = 0.01


@dataclass(slots=True)
class _TickerState:
    profile: TickerProfile
    price: float


class GBMSimulator:
    """Correlated geometric Brownian motion with jump events. Pure: no I/O, no asyncio."""

    def __init__(
        self,
        *,
        seed: int | None = None,
        tick_seconds: float = 0.5,
        time_scale: float = 30.0,
        event_probability: float = 0.001,
        event_range: tuple[float, float] = (0.02, 0.05),
        market_weight: float = MARKET_WEIGHT,
        sector_weights: dict[str, float] | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self.dt = tick_seconds * time_scale / TRADING_SECONDS_PER_YEAR
        self._sqrt_dt = math.sqrt(self.dt)
        self.event_probability = event_probability
        self.event_range = event_range
        self._a = market_weight
        self._b = dict(SECTOR_WEIGHTS if sector_weights is None else sector_weights)
        for sector, b in self._b.items():
            if self._a**2 + b**2 > 1:
                raise ValueError(f"market^2 + sector^2 weights exceed 1 for {sector!r}")
        self._state: dict[str, _TickerState] = {}
        self._parked: dict[str, _TickerState] = {}

    # ---- ticker management ----
    def add(self, ticker: str, profile: TickerProfile) -> float:
        """Start simulating `ticker`; returns its current price (seed, or resumed if parked)."""
        if ticker not in self._state:
            self._state[ticker] = self._parked.pop(ticker, None) or _TickerState(profile, profile.price)
        return self._state[ticker].price

    def remove(self, ticker: str) -> None:
        """Stop simulating, but park the state so a re-add resumes instead of jumping to seed."""
        state = self._state.pop(ticker, None)
        if state is not None:
            self._parked[ticker] = state

    def price(self, ticker: str) -> float | None:
        state = self._state.get(ticker)
        return state.price if state else None

    def tickers(self) -> frozenset[str]:
        return frozenset(self._state)

    def __contains__(self, ticker: str) -> bool:
        return ticker in self._state

    # ---- simulation ----
    def step(self) -> dict[str, float]:
        """Advance every tracked ticker one tick. Returns {ticker: new_price}.

        Draw order is fixed (market, sorted sectors, sorted tickers) so a seed fully
        determines the path for a given sequence of add/remove/step calls.
        """
        if not self._state:
            return {}
        rng = self._rng
        market = rng.gauss(0.0, 1.0)
        sectors = sorted({s.profile.sector for s in self._state.values()})
        sector_shock = {s: rng.gauss(0.0, 1.0) for s in sectors}

        out: dict[str, float] = {}
        for ticker in sorted(self._state):
            st = self._state[ticker]
            p = st.profile
            b = self._b.get(p.sector, 0.0)
            c = math.sqrt(max(0.0, 1.0 - self._a**2 - b**2))
            z = self._a * market + b * sector_shock[p.sector] + c * rng.gauss(0.0, 1.0)

            log_ret = (p.drift - 0.5 * p.volatility**2) * self.dt + p.volatility * self._sqrt_dt * z
            if rng.random() < self.event_probability:
                size = rng.uniform(*self.event_range)
                log_ret += math.log1p(size if rng.random() < 0.5 else -size)

            st.price = max(MIN_PRICE, st.price * math.exp(log_ret))
            out[ticker] = st.price
        return out


class SimulatorDataSource(MarketDataSource):
    name = "simulator"

    def __init__(
        self,
        cache: PriceCache,
        *,
        seed: int | None = None,
        tick_interval: float = 0.5,
        time_scale: float = 30.0,
        engine: GBMSimulator | None = None,  # tests may inject a configured engine
    ) -> None:
        super().__init__(cache)
        self._seed = seed
        self._interval = tick_interval
        self._sim = engine or GBMSimulator(seed=seed, tick_seconds=tick_interval, time_scale=time_scale)
        self._task: asyncio.Task | None = None
        self._status = SourceStatus(self.name, SourceState.STARTING)

    @property
    def max_quote_age(self) -> float:
        return max(5.0, 10 * self._interval)  # ~10 missed ticks means the loop is stuck

    # ---- MarketDataSource ----
    async def start(self, tickers: Iterable[str]) -> None:
        if self._task:
            return
        for t in tickers:
            self._track(t)
        self._task = asyncio.create_task(self._run(), name="market-simulator")
        self._status = SourceStatus(self.name, SourceState.OK, None, self.cache.now())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status = SourceStatus(self.name, SourceState.STOPPED)

    async def add_ticker(self, ticker: str) -> None:
        self._track(ticker)  # priced immediately, so it is tradable at once

    async def remove_ticker(self, ticker: str) -> None:
        self._sim.remove(ticker)
        self.cache.remove(ticker)

    def tickers(self) -> frozenset[str]:
        return self._sim.tickers()

    def status(self) -> SourceStatus:
        return self._status

    # ---- internals ----
    def _track(self, ticker: str) -> None:
        if ticker in self._sim:
            return
        price = self._sim.add(ticker, profile_for(ticker, self._seed))
        # reference_price = first price this run, so "change %" means "since start"
        self.cache.update(ticker, price, source=self.name, reference_price=price)

    def tick(self) -> None:
        """Advance one step and publish. Public so tests can drive it without the loop."""
        for ticker, price in self._sim.step().items():
            self.cache.update(ticker, price, source=self.name)
        self._status = SourceStatus(self.name, SourceState.OK, None, self.cache.now())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                self.tick()
            except Exception:  # never let the loop die (contract C4)
                log.exception("simulator tick failed")
            next_tick += self._interval
            now = loop.time()
            if next_tick < now:  # fell behind (e.g. laptop suspended): don't burst
                next_tick = now
            await asyncio.sleep(next_tick - now)
```

Behaviour worth knowing:

- `start()` and `add_ticker()` **write the seed price straight into the cache**, so a newly added ticker can be traded in the same request.
- `_run` **ticks immediately** and then every `tick_interval`. It uses deadline scheduling (no drift), and after a stall it resets the deadline instead of firing a burst of catch-up ticks. Δt per tick is fixed, so a stalled loop slows the simulation down; it never jumps.
- `remove()` **parks** the engine state, so re-adding NVDA resumes from its last price. The cache entry was dropped, so `reference_price` restarts at the resumed price.
- `max_quote_age = max(5 s, 10 ticks)`. If the loop is stuck for that long, trades are rejected with `stale_price`.

### 7.4 Parameters

| Parameter | Default | Exposed as |
|---|---|---|
| `tick_interval` | 0.5 s | constructor |
| `time_scale` | 30 | constructor |
| `event_probability` | 0.001 | `GBMSimulator` constructor |
| `event_range` | (0.02, 0.05) | `GBMSimulator` constructor |
| `MARKET_WEIGHT` a / `SECTOR_WEIGHTS` b | 0.5 / 0.5 (`other` 0.0) | `seed_prices.py` constants |
| per-ticker price, σ, μ, sector | `SEED_PROFILES` | `seed_prices.py` |
| `seed` | random | env `SIMULATOR_SEED` |

### 7.5 Example

```python
from app.market.simulator import GBMSimulator
from app.market.seed_prices import profile_for

sim = GBMSimulator(seed=42)
for t in ("AAPL", "MSFT", "PYPL"):          # PYPL is not in the table → synthetic, sector "other"
    sim.add(t, profile_for(t, seed=42))
for _ in range(3):
    print({t: round(p, 2) for t, p in sim.step().items()})
# Same seed → the same three lines every run.
```

---

## 8. Massive (Polygon.io) source

### 8.1 Endpoint strategy

| Plan | Endpoint | Calls per cycle | Cadence | Mode |
|---|---|---|---|---|
| Starter and up (paid) | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=A,B,…` | **1 for any N** | `MASSIVE_POLL_INTERVAL` (default 5 s) | `snapshot` |
| Basic (free): snapshot returns **403** | `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` | 1 (+ ≤ 4 lookback over weekends) | every 30 min | `eod` |

Per-ticker endpoints (`/prev`, `/v2/last/trade/{t}`) are never used for polling. They cost N calls per cycle, which breaks the free plan's 5 req/min straight away.

### 8.2 State machine

```
            start()
               │
               ▼
      ┌──── snapshot ────┐  403 NOT_AUTHORIZED   ┌──────── eod ─────────┐
      │ poll every 5 s   │ ─────────────────────►│ grouped daily /30min │
      │ state OK         │                       │ state DEGRADED + note│
      └──┬──────┬────────┘                       └──┬──────────┬────────┘
         │      │ 429 / 5xx / timeout / bad JSON    │          │
         │      ▼                                   ▼          │
         │   backoff (Retry-After or 5→10→…→60 s), state DEGRADED; success resets
         │
         └─ 401 (either mode) ──► ERROR, polling stops for good (fatal) ◄─┘
```

| Response | Exception | Effect |
|---|---|---|
| 200 | — | write quotes. `OK` (snapshot) or `DEGRADED` with an EOD note. Backoff reset. |
| 401 | `MassiveAuthError` | `ERROR` "Invalid MASSIVE_API_KEY". Fatal: no more requests. |
| 403 on snapshot | `MassiveNotEntitledError` | switch to `eod` mode (permanent for this process) |
| 429 | `MassiveRateLimitError` | `DEGRADED`. Wait `Retry-After` or 60 s. |
| 5xx, timeout, network, bad JSON | `MassiveError` / `httpx.HTTPError` / `ValueError` | `DEGRADED`. Exponential backoff 5 → 60 s. |

During any failure the last good quotes stay in the cache. They become **untradable** once older than `max_quote_age` (`3 × poll_interval + 10` = 25 s by default). EOD mode has no age limit, because its prices are end-of-day by definition and `status()` says so.

### 8.3 HTTP client — `massive_client.py`

```python
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
```

Notes:

- Authentication uses an `Authorization: Bearer` header instead of `?apiKey=`, which keeps the key out of URLs and logs.
- A 10 s timeout bounds startup: `start()` awaits the first fetch, so app boot waits at most ~10 s when Massive is unreachable.
- The base URL is `https://api.massive.com`. The old `api.polygon.io` still works, but don't use it.
- `extract_quote` timestamp units: `updated` and `lastTrade.t` are **nanoseconds**, and `min.t` and bar `t` are **milliseconds**.

Example raw snapshot entry → quote:

```python
snap = {
    "ticker": "AAPL", "updated": 1759500000000000000,
    "lastTrade": {"p": 191.23, "t": 1759500000000000000},
    "min": {"c": 191.21, "t": 1759499940000}, "day": {"c": 191.20}, "prevDay": {"c": 189.50},
}
extract_quote(snap)   # (191.23, 1759500000.0, 189.5)
```

### 8.4 Data source — `massive_source.py`

```python
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
```

Behaviour worth knowing:

- **`_fetch_lock`** serializes the poll loop and `add_ticker`'s one-off fetch, so there are never two concurrent requests and never an out-of-order write.
- **Race-safe removal:** rows for a ticker removed while a request was in flight are dropped (`sym not in self._tickers`). That keeps contract C2.
- **`add_ticker` in snapshot mode** makes one immediate request for just that ticker, so it can be traded right away. It skips the request while backing off or after a fatal error. In **EOD mode** it costs no request, because the grouped-daily response already covers the whole market.
- **Missing tickers** (unknown symbols, or no EOD bar) are collected in `_missing` and listed in `status().message`.
- **EOD date** is computed in `America/New_York`, starting from yesterday (Basic can't see today before the close) and stepping back up to 5 days over weekends and holidays.
- **`last_success`** is updated only on a successful fetch. It doesn't drive any behaviour; it's there for diagnostics.

### 8.5 Request budget

| Mode | Requests/min | Limit |
|---|---|---|
| snapshot @ 5 s | 12 (independent of N) + 1 per `add_ticker` | paid: unlimited |
| snapshot @ 2 s | 30 | paid: unlimited |
| eod @ 30 min | ≤ 5 per refresh → ≤ 0.17/min average | free: 5/min |

---

## 9. Factory — `factory.py`

```python
"""The only place that reads market-data env vars."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .cache import PriceCache
from .interface import MarketDataSource


def create_market_data_source(cache: PriceCache, env: Mapping[str, str] = os.environ) -> MarketDataSource:
    api_key = (env.get("MASSIVE_API_KEY") or "").strip()
    if api_key:
        from .massive_client import MassiveClient
        from .massive_source import MassiveDataSource

        interval = float(env.get("MASSIVE_POLL_INTERVAL") or 5.0)
        return MassiveDataSource(cache, MassiveClient(api_key), poll_interval=interval)

    from .simulator import SimulatorDataSource

    seed = (env.get("SIMULATOR_SEED") or "").strip()
    return SimulatorDataSource(cache, seed=int(seed) if seed else None)
```

| Env var | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | non-empty after `.strip()` → Massive; otherwise the simulator |
| `MASSIVE_POLL_INTERVAL` | `5` | seconds between snapshot polls (minimum 1). Ignored in EOD mode. |
| `SIMULATOR_SEED` | unset | integer → reproducible simulator prices. E2E tests should set it, because `LLM_MOCK` alone doesn't make prices deterministic. |

Add these to `.env.example`, commented out:

```bash
# Optional: seconds between Massive snapshot polls (paid plans). Default 5.
# MASSIVE_POLL_INTERVAL=5
# Optional: integer seed for reproducible simulator prices (E2E tests).
# SIMULATOR_SEED=42
```

---

## 10. Tracking & trade pricing — `tracking.py`

```python
"""Glue between app state (watchlist, positions, trades) and the market-data source."""

from __future__ import annotations

from collections.abc import Iterable

from .cache import PriceCache
from .interface import MarketDataSource, PriceUnavailable
from .models import PriceQuote


async def sync_tracked_tickers(source: MarketDataSource, wanted: Iterable[str]) -> None:
    """Make the source track exactly `wanted` (watchlist ∪ open positions)."""
    wanted = set(wanted)
    current = source.tickers()
    for t in sorted(wanted - current):
        await source.add_ticker(t)
    for t in sorted(current - wanted):
        await source.remove_ticker(t)


async def price_for_trade(cache: PriceCache, source: MarketDataSource, ticker: str) -> PriceQuote:
    """The one fill-price lookup shared by manual and LLM trades.

    Starts tracking an untracked ticker first (the source prices it best-effort).
    """
    if ticker not in source.tickers():
        await source.add_ticker(ticker)
    quote = cache.get(ticker)
    if quote is None:
        raise PriceUnavailable(ticker, "no_price", f"No price available for {ticker} yet")
    max_age = source.max_quote_age
    if max_age is not None and quote.age(cache.now()) > max_age:
        raise PriceUnavailable(ticker, "stale_price", f"Price for {ticker} is stale; try again shortly")
    return quote
```

### 10.1 When to call `sync_tracked_tickers`

After **every** change to the watchlist or positions: watchlist add/remove (REST or LLM), and after every trade (a buy can open a position, and a full sell can close one). The app layer computes `wanted` from the DB:

```python
# app/db/queries.py (sketch, owned by the backend agent)
def tracked_tickers(conn, user_id: str = "default") -> set[str]:
    rows = conn.execute(
        """SELECT ticker FROM watchlist WHERE user_id = ?
           UNION
           SELECT ticker FROM positions WHERE user_id = ? AND quantity > 0""",
        (user_id, user_id),
    ).fetchall()
    return {r[0] for r in rows}
```

Example: the watchlist routes.

```python
from fastapi import APIRouter, HTTPException, Request
from app.market import normalize_ticker, sync_tracked_tickers

router = APIRouter()

@router.post("/api/watchlist")
async def add_to_watchlist(body: dict, request: Request):
    try:
        ticker = normalize_ticker(body.get("ticker", ""))
    except ValueError as e:
        raise HTTPException(400, {"error": "invalid_ticker", "detail": str(e)})
    db_add_watchlist(ticker)                                       # INSERT OR IGNORE
    await sync_tracked_tickers(request.app.state.market, tracked_tickers(get_conn()))
    q = request.app.state.prices.get(ticker)
    return {"ticker": ticker, "quote": q.to_dict() if q else None}

@router.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    ticker = normalize_ticker(ticker)
    db_remove_watchlist(ticker)
    # Still tracked if a position is held: removing from the watchlist never stops pricing a holding.
    await sync_tracked_tickers(request.app.state.market, tracked_tickers(get_conn()))
    return {"ticker": ticker, "removed": True}
```

### 10.2 Trade pricing

Manual trades (`POST /api/portfolio/trade`) and LLM trades go through **one** trade service, which gets its fill price from `price_for_trade`:

```python
from app.market import PriceUnavailable, normalize_ticker, price_for_trade, sync_tracked_tickers

async def execute_trade(app, ticker: str, side: str, quantity: float) -> dict:
    ticker = normalize_ticker(ticker)
    try:
        quote = await price_for_trade(app.state.prices, app.state.market, ticker)
    except PriceUnavailable as e:
        return {"status": "failed", "error": e.code, "detail": str(e)}   # "no_price" | "stale_price"
    # Fetch the price outside the DB transaction, then validate and write atomically (REVIEW §1):
    result = run_trade_transaction(ticker, side, quantity, fill_price=quote.price,
                                   quote_source=quote.source, quote_ts=quote.timestamp)
    await sync_tracked_tickers(app.state.market, tracked_tickers(get_conn()))
    return result
```

`price_for_trade` starts tracking an unknown ticker on demand. In simulator mode a first-time buy of `PYPL` therefore fills at its synthetic seed price straight away, and in Massive mode it costs one snapshot request. If the trade fails, the trailing `sync_tracked_tickers` drops the ticker again unless it's on the watchlist. PLAN §13 #7 settled on auto-adding bought tickers to the watchlist, so after a successful buy it will be.

---

## 11. SSE endpoint & app wiring

### 11.1 Wire format

Each SSE `data:` frame is one **full snapshot** of every tracked ticker, plus the source status. A full snapshot makes reconnects and ticker removals trivial: the client replaces its state on every frame. A frame is sent only when `cache.version` or the source state/message changed, checked every 500 ms. When nothing has changed for 15 s, a `: keep-alive` comment goes out. The first frame is `retry: 3000`, so `EventSource` reconnects after 3 s.

```
retry: 3000

data: {"type":"prices","source":{"source":"simulator","state":"ok","message":null},"quotes":{"AAPL":{"ticker":"AAPL","price":190.42,"previous_price":190.37,"reference_price":190.0,"change":0.42,"change_percent":0.2211,"direction":"up","timestamp":"2026-10-05T14:03:21.512Z"},"MSFT":{...}}}

: keep-alive
```

Massive free plan example (the status explains why prices aren't moving):

```json
{"type": "prices",
 "source": {"source": "massive", "state": "degraded",
            "message": "Massive plan has no live snapshots; showing end-of-day closes from 2026-10-02"},
 "quotes": {"AAPL": {"ticker": "AAPL", "price": 226.78, "previous_price": 226.78, "reference_price": 224.5,
                     "change": 2.28, "change_percent": 1.0156, "direction": "flat",
                     "timestamp": "2026-10-02T04:00:00.000Z"}}}
```

At 10 tickers a frame is about 2 KB, so 4 KB/s per client in simulator mode.

### 11.2 Endpoint — `sse.py`

```python
"""GET /api/stream/prices: full-snapshot SSE stream read from the PriceCache."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache
from .interface import MarketDataSource

router = APIRouter()

PUSH_INTERVAL = 0.5
KEEPALIVE_SECONDS = 15.0


def build_price_event(cache: PriceCache, source: MarketDataSource) -> dict:
    return {
        "type": "prices",
        "source": source.status().to_dict(),
        "quotes": {t: q.to_dict() for t, q in sorted(cache.snapshot().items())},
    }


async def price_events(
    cache: PriceCache,
    source: MarketDataSource,
    should_stop: Callable[[], Awaitable[bool]],
    *,
    interval: float = PUSH_INTERVAL,
    keepalive: float = KEEPALIVE_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE frames. A data frame only when prices or source status changed."""
    yield "retry: 3000\n\n"
    last_key: tuple | None = None
    last_sent = time.monotonic()
    while not await should_stop():
        status = source.status()
        key = (cache.version, status.state, status.message)  # not last_success: it changes every poll
        now = time.monotonic()
        if key != last_key:
            payload = json.dumps(build_price_event(cache, source), separators=(",", ":"))
            yield f"data: {payload}\n\n"
            last_key, last_sent = key, now
        elif now - last_sent >= keepalive:
            yield ": keep-alive\n\n"
            last_sent = now
        await asyncio.sleep(interval)


@router.get("/api/stream/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    state = request.app.state

    async def should_stop() -> bool:
        return state.shutting_down.is_set() or await request.is_disconnected()

    return StreamingResponse(
        price_events(state.prices, state.market, should_stop),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

`shutting_down` matters. Without it, uvicorn's graceful shutdown waits on open SSE responses, because `is_disconnected()` stays false while the browser is still connected. Setting the event in the lifespan `finally` ends every stream within one interval.

### 11.3 Lifespan wiring — `app/main.py`

```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import get_conn, init_db, tracked_tickers
from app.market import PriceCache, create_market_data_source
from app.market.sse import router as market_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                          # schema + seed; must finish first
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers(get_conn()))    # cache is warm before the first request
    app.state.prices, app.state.market = cache, source
    app.state.shutting_down = asyncio.Event()
    snapshot_task = asyncio.create_task(portfolio_snapshot_loop(app))   # 30 s task, reads the cache
    try:
        yield
    finally:
        app.state.shutting_down.set()
        snapshot_task.cancel()
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(market_router)
# ... other /api routers, then StaticFiles(html=True) mounted at "/" LAST


@app.get("/api/health")
async def health():
    return {"status": "ok", "market": app.state.market.status().to_dict()}
```

Run with **one worker** (the cache is per-process):

```dockerfile
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### 11.4 Frontend consumption (reference for the frontend agent)

```ts
type Quote = {
  ticker: string; price: number; previous_price: number; reference_price: number;
  change: number; change_percent: number; direction: "up" | "down" | "flat"; timestamp: string;
};
type PriceEvent = {
  type: "prices";
  source: { source: "simulator" | "massive"; state: "starting" | "ok" | "degraded" | "error" | "stopped"; message: string | null };
  quotes: Record<string, Quote>;
};

const MAX_POINTS = 600;                                 // bound sparkline memory (REVIEW §5)
const last: Record<string, number> = {};                // last price seen by this client

const es = new EventSource("/api/stream/prices");
es.onopen = () => setConnection("connected");           // green dot
es.onerror = () => setConnection(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
es.onmessage = (e) => {
  const ev: PriceEvent = JSON.parse(e.data);
  for (const q of Object.values(ev.quotes)) {
    const prev = last[q.ticker];
    if (prev !== undefined && prev !== q.price) {
      flash(q.ticker, q.price > prev ? "up" : "down");  // flash on a real change only
    }
    if (prev !== q.price) appendSparkline(q.ticker, q.price, MAX_POINTS);
    last[q.ticker] = q.price;
  }
  for (const t of Object.keys(last)) if (!(t in ev.quotes)) delete last[t];
  setQuotes(ev.quotes);                                 // full replace: removals handled for free
  setSourceStatus(ev.source);                           // show message next to the connection dot
};
```

The client compares against its own previous price, not `direction`, so a reconnect snapshot (where `direction` reflects the server's last tick) doesn't flash every ticker at once.

---

## 12. Other consumers

| Consumer | How it reads | Missing or stale quote |
|---|---|---|
| `GET /api/watchlist` | `cache.get(t)` per row → `quote.to_dict()` | `"quote": null`. The UI shows "—". |
| `GET /api/portfolio` | `cache.get(t)` per position | position `price: null` and `"valuation_complete": false`. Never value it at 0. |
| 30 s snapshot task | `cache.snapshot()` | skip the snapshot if any held ticker is unpriced, so the chart never shows a fake drop |
| LLM context | `{t: q.to_dict() for t, q in cache.snapshot().items()}` + `source.status().to_dict()` | the model sees exactly what the UI shows |
| `/api/health` | `source.status().to_dict()` | — |

Portfolio valuation helper (shared by `/api/portfolio`, the snapshot task and the LLM context):

```python
from app.market import PriceCache

def mark_to_market(cache: PriceCache, cash: float, positions: list[dict]) -> dict:
    rows, total, complete = [], cash, True
    for p in positions:                                  # p: {"ticker", "quantity", "avg_cost"}
        q = cache.get(p["ticker"])
        if q is None:
            complete = False
            rows.append({**p, "price": None, "market_value": None, "unrealized_pnl": None, "pnl_percent": None})
            continue
        mv = p["quantity"] * q.price
        cost = p["quantity"] * p["avg_cost"]
        total += mv
        rows.append({**p, "price": q.price, "market_value": round(mv, 2),
                     "unrealized_pnl": round(mv - cost, 2),
                     "pnl_percent": round((q.price - p["avg_cost"]) / p["avg_cost"] * 100, 2) if p["avg_cost"] else 0.0})
    return {"cash": round(cash, 2), "positions": rows,
            "total_value": round(total, 2) if complete else None, "valuation_complete": complete}
```

---

## 13. Tests

Run with `cd backend && uv run pytest tests/market -q`. No test sleeps for more than 0.1 s of real time. Time comes from `FakeClock`, randomness from fixed seeds, and HTTP from `httpx.MockTransport`.

| File | Covers |
|---|---|
| `conftest.py` | `FakeClock`, `cache`, a fake Massive HTTP handler, and a `source` fixture parametrized over **both** implementations |
| `test_contract.py` | C1–C7 against the simulator and against Massive |
| `test_cache_models.py` | previous/reference carry-forward, direction, change %, rounding, version, invalid prices, exact wire format, `normalize_ticker` |
| `test_simulator.py` | determinism, positivity, GBM mean and std, sector correlation 0.50 / 0.25, event frequency and size, unknown tickers, park/resume, source start/tick/loop |
| `test_massive.py` | `extract_quote` fallbacks, auth header and ticker batching, 403 → EOD (with holiday lookback and a request-free `add_ticker`), 401 fatal, 429 `Retry-After`, 5xx backoff 5→60 s and recovery, unknown-ticker status |
| `test_tracking_factory_sse.py` | factory selection (empty or whitespace key → simulator), `SIMULATOR_SEED`, `sync_tracked_tickers` diffing, `price_for_trade` ok / auto-track / `stale_price` / `no_price`, SSE first snapshot, change-only frames, keep-alive |

### 13.1 Fixtures — `tests/market/conftest.py`

```python
from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.market.cache import PriceCache
from app.market.massive_client import MassiveClient
from app.market.massive_source import MassiveDataSource
from app.market.simulator import SimulatorDataSource


class FakeClock:
    def __init__(self, t: float = 1_760_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def snapshot_row(ticker: str, price: float, prev_close: float = 100.0) -> dict:
    return {
        "ticker": ticker,
        "updated": 1_759_500_000_000_000_000,
        "lastTrade": {"p": price, "t": 1_759_500_000_000_000_000},
        "prevDay": {"c": prev_close},
    }


class FakeMassive:
    """httpx handler that serves snapshot prices for every requested ticker except `unknown`."""

    def __init__(self) -> None:
        self.prices: dict[str, float] = {}
        self.unknown: set[str] = {"ZZZZ"}
        self.calls: list[httpx.Request] = []
        self.status_code = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"status": "ERROR", "message": "boom"})
        wanted = request.url.params["tickers"].split(",")
        rows = [snapshot_row(t, self.prices.get(t, 150.0)) for t in wanted if t not in self.unknown]
        return httpx.Response(200, json={"status": "OK", "count": len(rows), "tickers": rows})


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def cache(clock: FakeClock) -> PriceCache:
    return PriceCache(clock=clock)


@pytest.fixture
def fake_massive() -> FakeMassive:
    return FakeMassive()


def make_massive(cache: PriceCache, handler, **kw) -> MassiveDataSource:
    client = MassiveClient("test-key", transport=httpx.MockTransport(handler))
    return MassiveDataSource(cache, client, today=lambda: date(2026, 10, 5), **kw)


@pytest.fixture(params=["simulator", "massive"])
async def source(request, cache, fake_massive):
    if request.param == "simulator":
        src = SimulatorDataSource(cache, seed=42, tick_interval=0.01)
    else:
        src = make_massive(cache, fake_massive, poll_interval=1.0)
    yield src
    await src.stop()
```

### 13.2 Contract suite — `tests/market/test_contract.py`

```python
"""Behavioural contract C1-C7, run against both implementations."""

import asyncio
import math

from app.market.models import SourceState


async def test_c1_start_populates_cache(source, cache):
    await source.start(["AAPL", "MSFT"])
    assert cache.get("AAPL") is not None and cache.get("MSFT") is not None
    assert source.tickers() == {"AAPL", "MSFT"}


async def test_c2_remove_drops_from_cache(source, cache):
    await source.start(["AAPL", "MSFT"])
    await source.remove_ticker("MSFT")
    assert "MSFT" not in cache and "MSFT" not in source.tickers()
    assert set(cache.snapshot()) <= source.tickers()


async def test_c3_idempotent(source, cache):
    await source.start(["AAPL"])
    await source.start(["AAPL"])
    await source.add_ticker("NVDA")
    await source.add_ticker("NVDA")
    await source.remove_ticker("NVDA")
    await source.remove_ticker("NVDA")
    assert source.tickers() == {"AAPL"}
    await source.stop()
    await source.stop()


async def test_add_ticker_prices_immediately(source, cache):
    await source.start(["AAPL"])
    await source.add_ticker("PYPL")
    assert cache.get("PYPL") is not None


async def test_c5_stop_leaves_no_tasks(source):
    await source.start(["AAPL"])
    await source.stop()
    assert source.status().state == SourceState.STOPPED
    names = {t.get_name() for t in asyncio.all_tasks()}
    assert not names & {"market-simulator", "massive-poller"}


async def test_c6_c7_writes_tagged_and_valid(source, cache):
    await source.start(["AAPL", "TSLA"])
    for q in cache.snapshot().values():
        assert q.source == source.name
        assert math.isfinite(q.price) and q.price > 0
```

The remaining test files are in Appendix A.

---

## 14. Changes relative to the earlier planning docs

| Topic | Earlier doc | This design | Why |
|---|---|---|---|
| Staleness clock | `price_for_trade` used `time.time()` | uses `cache.now()` (the injected clock) | staleness is testable without sleeping |
| `price_for_trade` | sync; caller had to `add_ticker` first | `async`, auto-tracks untracked tickers | one call for both manual and LLM trades |
| Invalid prices | rule C7 stated, not enforced | `PriceCache.update` raises on non-finite or ≤ 0 | one enforcement point |
| `reference_price` | `reference_price or …` (0 treated as missing implicitly) | explicit `None`/≤ 0 check, rounded to cents | clarity |
| `max_quote_age` | class attribute on the simulator, property on Massive | abstract property on the interface | uniform access |
| Simulator staleness | fixed 5 s | `max(5 s, 10 ticks)` | still correct if `tick_interval` changes |
| Massive missing-ticker status | snapshot mode only, overwritten by `add_ticker` fetches | `_missing` set kept across fetches, also covers EOD | an accurate message |
| Massive EOD date | `date.today()` (container local time, usually UTC) | yesterday in `America/New_York`, injectable | correct trading day; testable |
| Massive bad JSON | not handled | `ValueError` → backoff | C4 |
| Massive `stop()` | closed the client on every call | closes once | idempotency (C3) |
| SSE change key | `(version, status)`, where `status` includes `last_success` | `(version, state, message)` | avoids frames caused only by a timestamp change |
| SSE shutdown | `is_disconnected()` only | plus an `app.state.shutting_down` event | uvicorn graceful shutdown no longer hangs |
| SSE ordering | dict order | quotes sorted by ticker | stable output for tests and diffs |
| Client EOD helper | `get_latest_eod`, `get_previous_close`, `get_market_status` | removed; lookback lives in the source | unused code removed |

`MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md` and `MASSIVE_API.md` remain as background reading. Read `MASSIVE_API.md` for the provider's endpoints and plans, and `MARKET_SIMULATOR.md` for the derivations behind the simulator.

---

## 15. Implementation order

1. `models.py`, `cache.py`, `interface.py`, then `test_cache_models.py`.
2. `seed_prices.py`, `simulator.py`, then `test_simulator.py`.
3. `factory.py`, `tracking.py`, `sse.py`, `__init__.py`, plus a lifespan in `main.py`. This is enough for a working vertical slice with the frontend.
4. `massive_client.py`, `massive_source.py`, then `test_massive.py` and `test_contract.py`.
5. Add `MASSIVE_POLL_INTERVAL` / `SIMULATOR_SEED` to `.env.example`. E2E compose sets `SIMULATOR_SEED`.
6. Manual check with a real key, if one is available: `MASSIVE_API_KEY=… uv run uvicorn app.main:app`, then `curl -N localhost:8000/api/stream/prices`.

---

## Appendix A — remaining test files

### `tests/market/test_cache_models.py`

```python
import pytest

from app.market.cache import PriceCache
from app.market.interface import normalize_ticker
from app.market.models import Direction


def test_first_update_is_flat_and_sets_reference(cache):
    q = cache.update("AAPL", 190.004, source="simulator")
    assert q.price == 190.0 and q.previous_price == 190.0 and q.reference_price == 190.0
    assert q.direction == Direction.FLAT


def test_previous_and_reference_carry_forward(cache, clock):
    cache.update("AAPL", 190.0, source="massive", reference_price=188.0)
    clock.advance(1)
    q = cache.update("AAPL", 191.0, source="massive")
    assert q.previous_price == 190.0 and q.reference_price == 188.0
    assert q.direction == Direction.UP
    assert q.change_percent == pytest.approx(100 * 3 / 188)
    assert q.received_at == clock.t


def test_version_and_remove(cache):
    v0 = cache.version
    cache.update("AAPL", 1.0, source="s")
    cache.remove("AAPL")
    cache.remove("AAPL")  # no-op, no bump
    assert cache.version == v0 + 2 and len(cache) == 0


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_rejects_invalid_prices(cache, bad):
    with pytest.raises(ValueError):
        cache.update("AAPL", bad, source="s")


def test_to_dict_wire_format():
    c = PriceCache(clock=lambda: 1_759_500_000.5)
    c.update("AAPL", 100.0, source="s")
    d = c.update("AAPL", 99.5, source="s").to_dict()
    assert d == {
        "ticker": "AAPL", "price": 99.5, "previous_price": 100.0, "reference_price": 100.0,
        "change": -0.5, "change_percent": -0.5, "direction": "down",
        "timestamp": "2025-10-03T14:00:00.500Z",
    }


@pytest.mark.parametrize("raw,ok", [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("V", "V")])
def test_normalize_ok(raw, ok):
    assert normalize_ticker(raw) == ok


@pytest.mark.parametrize("raw", ["", "1ABC", "TOOLONGX", "AA PL", ".A"])
def test_normalize_rejects(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)
```

### `tests/market/test_simulator.py`

```python
import asyncio
import math
import statistics

from app.market.seed_prices import MARKET_WEIGHT, SECTOR_WEIGHTS, SEED_PROFILES, TickerProfile, profile_for
from app.market.simulator import GBMSimulator, SimulatorDataSource

DEFAULT_WATCHLIST = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def run(sim: GBMSimulator, n: int) -> list[dict[str, float]]:
    return [sim.step() for _ in range(n)]


def test_deterministic_under_seed():
    def path(seed):
        sim = GBMSimulator(seed=seed)
        for t in ("AAPL", "TSLA", "PYPL"):
            sim.add(t, profile_for(t, seed))
        return run(sim, 100)

    assert path(1) == path(1)
    assert path(1) != path(2)


def test_prices_positive_and_finite():
    sim = GBMSimulator(seed=3, time_scale=1_000)
    for t in DEFAULT_WATCHLIST:
        sim.add(t, SEED_PROFILES[t])
    for prices in run(sim, 10_000):
        assert all(math.isfinite(p) and p > 0 for p in prices.values())


def test_gbm_moments():
    sim = GBMSimulator(seed=7, time_scale=10_000, event_probability=0.0)
    prof = TickerProfile(100.0, 0.30, drift=0.10)
    sim.add("X", prof)
    prev, rets = 100.0, []
    for _ in range(50_000):
        p = sim.step()["X"]
        rets.append(math.log(p / prev))
        prev = p
    sd = prof.volatility * math.sqrt(sim.dt)
    expected_mean = (prof.drift - 0.5 * prof.volatility**2) * sim.dt
    assert abs(statistics.fmean(rets) - expected_mean) < 4 * sd / math.sqrt(len(rets))
    assert abs(statistics.stdev(rets) / sd - 1) < 0.02


def test_sector_correlation():
    sim = GBMSimulator(seed=1, event_probability=0.0)
    names = ("AAPL", "MSFT", "JPM")
    for t in names:
        sim.add(t, SEED_PROFILES[t])
    prev = {t: sim.price(t) for t in names}
    r = {t: [] for t in names}
    for _ in range(20_000):
        for t, p in sim.step().items():
            r[t].append(math.log(p / prev[t]))
            prev[t] = p
    assert abs(statistics.correlation(r["AAPL"], r["MSFT"]) - 0.50) < 0.03  # same sector: a² + b²
    assert abs(statistics.correlation(r["AAPL"], r["JPM"]) - 0.25) < 0.03   # cross sector: a²


def test_event_frequency_and_size():
    sim = GBMSimulator(seed=5, event_probability=0.01)
    sim.add("X", TickerProfile(100.0, volatility=0.0, drift=0.0))
    prev, jumps = 100.0, []
    for _ in range(50_000):
        p = sim.step()["X"]
        r = p / prev - 1
        if abs(r) > 1e-12:
            jumps.append(abs(r))
        prev = p
    assert abs(len(jumps) - 500) < 4 * math.sqrt(500)
    assert all(0.02 - 1e-9 <= j <= 0.05 + 1e-9 for j in jumps)


def test_unknown_ticker_profile_stable():
    a, b = profile_for("ZZZZ", seed=1), profile_for("ZZZZ", seed=1)
    assert a == b and 50 <= a.price <= 300 and a.sector == "other"


def test_seed_table_complete_and_weights_valid():
    assert set(DEFAULT_WATCHLIST) <= set(SEED_PROFILES)
    assert all(MARKET_WEIGHT**2 + b**2 <= 1 for b in SECTOR_WEIGHTS.values())


def test_park_and_resume():
    sim = GBMSimulator(seed=2)
    sim.add("AAPL", SEED_PROFILES["AAPL"])
    run(sim, 10)
    at_removal = sim.price("AAPL")
    sim.remove("AAPL")
    assert sim.add("AAPL", SEED_PROFILES["AAPL"]) == at_removal


async def test_source_start_and_tick(cache):
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL"])
    q0 = cache.get("AAPL")
    assert q0.price == 190.0 and q0.direction == "flat"
    v = cache.version
    src.tick()
    q1 = cache.get("AAPL")
    assert cache.version == v + 1 and q1.reference_price == 190.0 and q1.previous_price == 190.0
    await src.stop()


async def test_source_loop_runs():
    from app.market.cache import PriceCache

    cache = PriceCache()
    src = SimulatorDataSource(cache, seed=1, tick_interval=0.01)
    await src.start(["AAPL"])
    v = cache.version
    await asyncio.sleep(0.1)
    assert cache.version > v + 3
    await src.stop()
```

### `tests/market/test_massive.py`

```python
from datetime import date

import httpx
import pytest

from app.market.massive_client import MassiveClient, MassiveNotEntitledError, extract_quote
from app.market.models import SourceState

from .conftest import make_massive, snapshot_row


# ---- extract_quote ---------------------------------------------------------
def test_extract_prefers_last_trade():
    assert extract_quote(snapshot_row("AAPL", 191.23, 189.5)) == (191.23, 1_759_500_000.0, 189.5)


def test_extract_falls_back_to_bars():
    snap = {"ticker": "AAPL", "min": {"c": 10.5, "t": 1_759_499_940_000}, "day": {"c": 10.4}, "prevDay": {"c": 10.0}}
    assert extract_quote(snap) == (10.5, 1_759_499_940.0, 10.0)
    assert extract_quote({"ticker": "AAPL", "day": {"c": 0}, "prevDay": {"c": 9.0}})[0] == 9.0


def test_extract_unusable():
    assert extract_quote({"ticker": "AAPL", "day": {"c": 0}}) is None


# ---- client ----------------------------------------------------------------
async def test_client_sends_auth_and_sorted_tickers():
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["auth"], seen["tickers"] = r.headers["Authorization"], r.url.params["tickers"]
        return httpx.Response(200, json={"tickers": []})

    client = MassiveClient("k", transport=httpx.MockTransport(handler))
    await client.get_snapshots(["msft", "aapl", "AAPL"])
    assert seen == {"auth": "Bearer k", "tickers": "AAPL,MSFT"}
    await client.aclose()


async def test_client_403():
    t = httpx.MockTransport(lambda r: httpx.Response(403, json={"status": "NOT_AUTHORIZED", "message": "upgrade"}))
    with pytest.raises(MassiveNotEntitledError):
        await MassiveClient("k", transport=t).get_snapshots(["AAPL"])


# ---- data source -----------------------------------------------------------
async def test_snapshot_reference_is_prev_close(cache, fake_massive):
    fake_massive.prices["AAPL"] = 105.0
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    q = cache.get("AAPL")
    assert (q.price, q.reference_price, q.change_percent) == (105.0, 100.0, 5.0)
    assert src.status().state == SourceState.OK
    await src.stop()


async def test_unknown_ticker_reported(cache, fake_massive):
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL", "ZZZZ"])
    assert "ZZZZ" not in cache
    assert src.status().message == "No data for: ZZZZ"
    await src.remove_ticker("ZZZZ")
    await src._fetch()
    assert src.status().message is None
    await src.stop()


async def test_401_is_fatal(cache, fake_massive):
    fake_massive.status_code = 401
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    assert src.status().state == SourceState.ERROR
    n = len(fake_massive.calls)
    await src.add_ticker("MSFT")
    await src._fetch()
    assert len(fake_massive.calls) == n  # no further requests
    await src.stop()


async def test_429_backs_off_with_retry_after(cache):
    t = lambda r: httpx.Response(429, headers={"Retry-After": "12"}, json={"message": "slow down"})  # noqa: E731
    src = make_massive(cache, t)
    await src.start(["AAPL"])
    assert src.status().state == SourceState.DEGRADED and src._backoff == 12.0
    await src.stop()


async def test_5xx_exponential_backoff(cache, fake_massive):
    fake_massive.status_code = 503
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    delays = [src._backoff]
    for _ in range(5):
        await src._fetch()
        delays.append(src._backoff)
    assert delays == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]
    fake_massive.status_code = 200
    await src._fetch()
    assert src._backoff == 0 and src.status().state == SourceState.OK
    await src.stop()


async def test_403_switches_to_eod(cache):
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r.url.path)
        if "snapshot" in r.url.path:
            return httpx.Response(403, json={"status": "NOT_AUTHORIZED", "message": "upgrade"})
        if r.url.path.endswith("2026-10-05"):  # a holiday: empty
            return httpx.Response(200, json={"resultsCount": 0})
        rows = [{"T": "AAPL", "o": 100.0, "c": 102.0, "t": 1_759_464_000_000},
                {"T": "MSFT", "o": 400.0, "c": 396.0, "t": 1_759_464_000_000}]
        return httpx.Response(200, json={"results": rows})

    src = make_massive(cache, handler)
    await src.start(["AAPL"])
    assert cache.get("AAPL").price == 102.0 and cache.get("AAPL").change_percent == pytest.approx(2.0)
    st = src.status()
    assert st.state == SourceState.DEGRADED and "2026-10-04" in st.message
    assert src.max_quote_age is None

    n = len(calls)
    await src.add_ticker("MSFT")  # served from the already-downloaded grouped bars
    assert len(calls) == n and cache.get("MSFT").price == 396.0
    await src.stop()
```

### `tests/market/test_tracking_factory_sse.py`

```python
import asyncio
import json

import pytest

from app.market import PriceUnavailable, price_for_trade, sync_tracked_tickers
from app.market.factory import create_market_data_source
from app.market.massive_source import MassiveDataSource
from app.market.simulator import SimulatorDataSource
from app.market.sse import price_events


# ---- factory ---------------------------------------------------------------
@pytest.mark.parametrize("env", [{}, {"MASSIVE_API_KEY": ""}, {"MASSIVE_API_KEY": "   "}])
def test_factory_simulator(cache, env):
    assert isinstance(create_market_data_source(cache, env), SimulatorDataSource)


async def test_factory_massive(cache):
    src = create_market_data_source(cache, {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": "2"})
    assert isinstance(src, MassiveDataSource) and src.max_quote_age == 16
    await src.stop()


def test_factory_seed(cache):
    a = create_market_data_source(cache, {"SIMULATOR_SEED": "7"})
    assert a._seed == 7


# ---- tracking --------------------------------------------------------------
async def test_sync_tracked_tickers(cache):
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL", "MSFT"])
    await sync_tracked_tickers(src, {"AAPL", "TSLA"})
    assert src.tickers() == {"AAPL", "TSLA"} and "MSFT" not in cache
    await src.stop()


async def test_price_for_trade(cache, clock):
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL"])
    assert (await price_for_trade(cache, src, "AAPL")).price == 190.0
    assert (await price_for_trade(cache, src, "PYPL")).ticker == "PYPL"  # auto-tracked
    clock.advance(src.max_quote_age + 1)
    with pytest.raises(PriceUnavailable) as e:
        await price_for_trade(cache, src, "AAPL")
    assert e.value.code == "stale_price"
    await src.stop()


async def test_price_for_trade_no_price(cache, fake_massive):
    from .conftest import make_massive

    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    with pytest.raises(PriceUnavailable) as e:
        await price_for_trade(cache, src, "ZZZZ")
    assert e.value.code == "no_price"
    await src.stop()


# ---- SSE -------------------------------------------------------------------
async def test_sse_sends_snapshot_then_only_on_change(cache):
    src = SimulatorDataSource(cache, seed=1, tick_interval=3600)  # loop ticks once, then idles
    await src.start(["AAPL", "MSFT"])
    await asyncio.sleep(0)
    stops = iter([False, False, False, True])

    async def should_stop():
        return next(stops)

    frames = []
    gen = price_events(cache, src, should_stop, interval=0, keepalive=3600)
    async for f in gen:
        frames.append(f)
        if len([x for x in frames if x.startswith("data:")]) == 1:
            src.tick()  # change prices once, after the first data frame
    data = [json.loads(f[6:]) for f in frames if f.startswith("data: ")]
    assert frames[0] == "retry: 3000\n\n"
    assert len(data) == 2  # initial snapshot + one after tick; third loop had no change
    assert set(data[0]["quotes"]) == {"AAPL", "MSFT"}
    assert data[0]["source"] == {"source": "simulator", "state": "ok", "message": None}
    await src.stop()


async def test_sse_keepalive(cache):
    src = SimulatorDataSource(cache, seed=1, tick_interval=3600)
    await src.start(["AAPL"])
    await asyncio.sleep(0)
    stops = iter([False, False, True])

    async def should_stop():
        return next(stops)

    frames = [f async for f in price_events(cache, src, should_stop, interval=0, keepalive=0)]
    assert frames[-1] == ": keep-alive\n\n"
    await src.stop()
```
