# Market Simulator — Approach & Code Structure

This doc covers the default price source, used whenever `MASSIVE_API_KEY` is empty. It implements the `MarketDataSource` interface from `MARKET_INTERFACE.md` and writes into the shared `PriceCache`. It runs in-process with no network access, using only the Python standard library.

Requirements (PLAN.md §6, REVIEW.md):

- Geometric Brownian motion (GBM) with per-ticker drift and volatility
- Updates every ~500 ms
- Correlated moves: tech names move together
- Occasional random "events": sudden 2–5 % jumps on a single ticker
- Realistic seed prices (AAPL ≈ $190, GOOGL ≈ $175, …). Unknown tickers get a plausible price.
- Reproducible under a fixed seed, for tests and E2E (REVIEW item 8)
- A simple sector-factor model, not a full covariance/Cholesky setup (REVIEW §13 item 33)

---

## 1. The model

### 1.1 GBM step

For each ticker *i* with annualized drift μᵢ and volatility σᵢ, one tick of length Δt (in years) is:

```
log_return_i = (μᵢ − ½σᵢ²)·Δt + σᵢ·√Δt·Zᵢ  [+ Jᵢ if an event fires]
Sᵢ ← Sᵢ · exp(log_return_i)
```

This is the exact solution of GBM over Δt. It isn't an Euler approximation, so prices stay strictly positive and the step can't drift numerically. The ½σ² term is the Itô correction, which keeps the *expected* price growing at μ.

### 1.2 Time scaling (why prices visibly move)

If one 0.5 s tick were 0.5 s of real trading time, then with Δt = 0.5 / (252 × 6.5 × 3600) ≈ 8.5 × 10⁻⁸ years and σ = 25 %, the per-tick move would be about 0.007 %. That's ~1¢ on AAPL, so the UI would barely flicker.

We compress time instead: **`time_scale = 30`**, so one real second equals 30 market seconds.

```
Δt = tick_seconds × time_scale / TRADING_SECONDS_PER_YEAR
   = 0.5 × 30 / 5,896,800 ≈ 2.54 × 10⁻⁶ years
per-tick σ (σ = 25 %) = 0.25 × √Δt ≈ 0.040 %   → ≈ 8¢ on a $190 stock
```

| Horizon (real time) | Typical move at σ = 25 % | σ = 55 % (TSLA) |
|---|---|---|
| 1 tick (0.5 s) | 0.04 % | 0.09 % |
| 1 minute | 0.44 % | 0.96 % |
| 1 hour | 3.4 % | 7.4 % |

That's lively enough to look like a busy trading day, without prices running off over a demo session. `time_scale` is a constructor argument; tests set it high to make statistical checks quick and robust.

Drift is tiny at this scale (μ = 5 %/yr adds ~0.0001 % per tick). We keep it for correctness, but it has no visible effect.

### 1.3 Correlation: one market factor plus sector factors

Each tick draws one market shock *M*, one shock *Sₖ* per sector, and one idiosyncratic shock *εᵢ* per ticker, all independent N(0,1):

```
Zᵢ = a·M + bₖ·S_k(i) + cᵢ·εᵢ        with  cᵢ = √(1 − a² − bₖ²)
```

Then Var(Zᵢ) = 1 exactly, so σᵢ still means what it says, and:

- corr(i, j) for the **same sector** = a² + bₖ²
- corr(i, j) for **different sectors** = a²

With a = 0.5 and b = 0.5 that gives **0.50** within a sector and **0.25** across sectors, which is roughly realistic for large-cap US equities. The `"other"` sector (unknown tickers) has b = 0, so those names share only the market factor.

| Sector | Tickers | b |
|---|---|---|
| `tech` | AAPL, MSFT, GOOGL, META, AMZN, NFLX | 0.5 |
| `growth` | NVDA, TSLA | 0.5 |
| `finance` | JPM, V | 0.5 |
| `other` | anything not in the seed table | 0.0 |

### 1.4 Events (jumps)

Each tick, each ticker independently has probability **p = 0.001** of an event. An event adds `log(1 ± m)` to the log return, with m ~ Uniform(2 %, 5 %) and a random sign.

- Per ticker: one event every ~1,000 ticks ≈ **8 minutes**.
- Across the 10-ticker default watchlist: roughly **one event every 50 seconds**. That's enough drama without turning into noise.
- Events are idiosyncratic. They don't spill over to sector peers.

### 1.5 Seed prices & unknown tickers

The defaults come from a hand-written table (§3). They're approximate and only need to look plausible.

A ticker that isn't in the table gets a deterministic profile derived from `crc32(f"{seed}:{ticker}")`: price ~ U($50, $300), σ ~ U(25 %, 45 %), sector `other`. Using `crc32` instead of `hash()` matters: Python's string hash is randomized per process, which would break reproducibility.

### 1.6 Reproducibility

All randomness flows from one `random.Random(seed)`. Tickers are processed in sorted order and sectors are drawn in sorted order, so:

> Same `seed` + same sequence of `add` / `remove` / `step` calls ⇒ identical prices.

`SIMULATOR_SEED` (env) sets the seed. When it's unset, the seed is random, which is fine for normal use.

### 1.7 Removing and re-adding

`remove()` parks the ticker's current price instead of discarding it, and `add()` resumes from the parked price. Removing NVDA and adding it back a minute later doesn't jump it back to its seed price.

---

## 2. Code structure

```
backend/app/market/
├── seed_prices.py   # TickerProfile, SEED_PROFILES, SECTOR_WEIGHTS, profile_for()
└── simulator.py     # GBMSimulator (pure, synchronous, no I/O) + SimulatorDataSource (async adapter)
```

| Class | Responsibility | Async? | Touches cache? |
|---|---|---|---|
| `GBMSimulator` | Holds per-ticker state; `step()` advances every ticker by one tick and returns the new prices | No | No |
| `SimulatorDataSource` | Implements `MarketDataSource`; owns the 500 ms loop; copies `step()` output into `PriceCache` | Yes | Yes |

Keeping the maths in a pure synchronous class means statistical tests can run 100k steps in milliseconds with no event loop or sleeps.

---

## 3. `seed_prices.py`

```python
from __future__ import annotations

import random
import zlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TickerProfile:
    price: float          # starting price, USD
    volatility: float     # annualized σ (0.25 = 25 %)
    drift: float = 0.05   # annualized μ
    sector: str = "other"


# Approximate, illustrative levels. Realism is nice-to-have, not a requirement.
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

MARKET_WEIGHT = 0.5                      # a
SECTOR_WEIGHTS: dict[str, float] = {     # b_k; must satisfy a² + b² ≤ 1
    "tech": 0.5,
    "growth": 0.5,
    "finance": 0.5,
    "other": 0.0,
}


def profile_for(ticker: str, seed: int | None = None) -> TickerProfile:
    """Seed-table profile, or a deterministic pseudo-random one for unknown tickers."""
    if ticker in SEED_PROFILES:
        return SEED_PROFILES[ticker]
    rng = random.Random(zlib.crc32(f"{seed}:{ticker}".encode()))
    return TickerProfile(
        price=round(rng.uniform(50.0, 300.0), 2),
        volatility=round(rng.uniform(0.25, 0.45), 3),
        sector="other",
    )
```

---

## 4. `simulator.py`: the engine

```python
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .seed_prices import MARKET_WEIGHT, SECTOR_WEIGHTS, TickerProfile

TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600      # 5,896,800
MIN_PRICE = 0.01


@dataclass(slots=True)
class _TickerState:
    profile: TickerProfile
    price: float


class GBMSimulator:
    """Correlated geometric Brownian motion with random jump events. Pure; no I/O."""

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
                raise ValueError(f"market² + sector² weights exceed 1 for {sector!r}")
        self._state: dict[str, _TickerState] = {}
        self._parked: dict[str, _TickerState] = {}

    # ---- ticker management ----
    def add(self, ticker: str, profile: TickerProfile) -> float:
        """Start simulating `ticker`; returns its current price (seed or resumed)."""
        if ticker not in self._state:
            self._state[ticker] = self._parked.pop(ticker, None) or _TickerState(profile, profile.price)
        return self._state[ticker].price

    def remove(self, ticker: str) -> None:
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
        """Advance every tracked ticker by one tick. Returns {ticker: new_price}."""
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
```

Notes:

- Every random draw happens in a fixed order: market, then sorted sectors, then sorted tickers, with `gauss → random → (uniform → random)` per ticker. That's what makes the seed meaningful.
- The engine keeps prices at full precision. `PriceCache.update` rounds to cents on write, so the path is never contaminated by rounding.
- `MIN_PRICE` is only a guard. GBM can't reach zero on its own.

---

## 5. `simulator.py`: the data source

```python
import asyncio
import logging
import time
from collections.abc import Callable, Iterable

from .cache import PriceCache
from .interface import MarketDataSource
from .models import SourceState, SourceStatus
from .seed_prices import profile_for

log = logging.getLogger(__name__)


class SimulatorDataSource(MarketDataSource):
    name = "simulator"
    max_quote_age = 5.0     # ~10 missed ticks ⇒ something is wrong; reject trades

    def __init__(
        self,
        cache: PriceCache,
        *,
        seed: int | None = None,
        tick_interval: float = 0.5,
        time_scale: float = 30.0,
        engine: GBMSimulator | None = None,       # tests may inject a configured engine
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(cache)
        self._seed = seed
        self._interval = tick_interval
        self._sim = engine or GBMSimulator(seed=seed, tick_seconds=tick_interval, time_scale=time_scale)
        self._clock = clock
        self._task: asyncio.Task | None = None
        self._status = SourceStatus(self.name, SourceState.STARTING)

    # ---- MarketDataSource ----
    async def start(self, tickers: Iterable[str]) -> None:
        if self._task:
            return
        for t in tickers:
            self._track(t)
        self._task = asyncio.create_task(self._run(), name="market-simulator")
        self._status = SourceStatus(self.name, SourceState.OK, None, self._clock())

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
        self._track(ticker)                 # priced immediately → tradable at once

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
        # reference_price = first price seen this run → "change %" means "since start"
        self.cache.update(ticker, price, source=self.name, reference_price=price)

    def tick(self) -> None:
        """Advance one step and publish. Public so tests can drive it without the loop."""
        for ticker, price in self._sim.step().items():
            self.cache.update(ticker, price, source=self.name)
        self._status = SourceStatus(self.name, SourceState.OK, None, self._clock())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            try:
                self.tick()
            except Exception:                       # never let the loop die (contract C4)
                log.exception("simulator tick failed")
            next_tick += self._interval
            now = loop.time()
            if next_tick < now:                     # fell behind (e.g. suspended laptop): don't burst
                next_tick = now
            await asyncio.sleep(next_tick - now)
```

A few design points:

- **Fixed Δt per tick**, not measured wall-clock time. If the event loop stalls, the simulation slows down instead of jumping, which keeps it deterministic.
- **Deadline scheduling** (`next_tick += interval`) stops the cadence drifting by the tick's own runtime. A stall resets the deadline instead of firing a burst of catch-up ticks.
- `reference_price` is set only on the first `cache.update` for a ticker. The cache carries it forward on every later update.
- Re-adding a removed ticker resumes the parked engine state. The cache entry was removed, though, so `reference_price` restarts at the resumed price.

---

## 6. Parameters

| Parameter | Default | Where | Effect |
|---|---|---|---|
| `tick_interval` | 0.5 s | `SimulatorDataSource` | Update cadence (PLAN: ~500 ms) |
| `time_scale` | 30 | both | Market seconds per real second; scales per-tick volatility by √ |
| `event_probability` | 0.001 | `GBMSimulator` | Per ticker per tick |
| `event_range` | (0.02, 0.05) | `GBMSimulator` | Jump magnitude, random sign |
| `MARKET_WEIGHT` (a) | 0.5 | `seed_prices` | Cross-sector correlation = a² |
| `SECTOR_WEIGHTS` (b) | 0.5 / 0.0 | `seed_prices` | Same-sector correlation = a² + b² |
| `seed` | env `SIMULATOR_SEED` or random | factory | Reproducibility |
| per-ticker σ, μ, price | `SEED_PROFILES` | `seed_prices` | Character of each name |

Only `SIMULATOR_SEED` is exposed as an env var. Everything else is a code constant, to keep configuration small.

---

## 7. Possible extensions (not in v1)

- **Mean reversion** toward the seed price (an Ornstein–Uhlenbeck term on log price) if long-running demos drift too far. Over 24 h of real time at `time_scale=30`, a 25 % σ name moves about ±17 % (1σ), which is acceptable for v1.
- **Intraday volatility smile** (higher σ near the "open" and "close").
- **Event spill-over**: a fraction of a jump propagated to sector peers.
- **Synthetic history** for the main chart: run the engine backward or forward N steps at startup.

---

## 8. Tests (`backend/tests/market/test_simulator.py`)

All engine tests are synchronous and use a fixed seed. A large `time_scale` makes the statistics converge quickly.

| Test | Method |
|---|---|
| Deterministic | Two engines, same seed, same adds → identical `step()` output over 100 steps; a different seed gives different output |
| Positive & finite | 10k steps, all prices > 0 and finite |
| GBM moments | `event_probability=0`, one ticker, 50k steps: mean log return ≈ (μ − ½σ²)Δt and std ≈ σ√Δt, within a few standard errors |
| Correlation | `event_probability=0`, 20k steps: sample corr(AAPL, MSFT) ≈ 0.50 ± 0.03; corr(AAPL, JPM) ≈ 0.25 ± 0.03 |
| Events: frequency | `volatility=0` profile, `event_probability=0.01`, 50k steps: event count ≈ 500 ± 4·√500 |
| Events: magnitude | `volatility=0`, `drift=0`: every non-zero simple return has |r| ∈ [2 %, 5 %] |
| Unknown ticker | `profile_for("ZZZZ", seed=1)` is stable across calls, price ∈ [50, 300], sector `other` |
| Seed table | All default watchlist tickers present; a² + b² ≤ 1 for every sector |
| Park/resume | add → step × 10 → remove → add: price equals the price at removal |
| Source: start | After `await start([...])` every ticker is in the cache at its seed price, `direction == "flat"` |
| Source: tick | `tick()` changes cache prices, bumps `cache.version`, keeps `reference_price` |
| Source: add/remove | `add_ticker` prices immediately; `remove_ticker` drops it from the cache |
| Source: loop | With `tick_interval=0.01`, after ~0.1 s the version has advanced; `stop()` cancels cleanly |

Example:

```python
import math, statistics
from app.market.simulator import GBMSimulator
from app.market.seed_prices import TickerProfile, SEED_PROFILES

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
    assert abs(statistics.fmean(rets) - (prof.drift - 0.5 * prof.volatility**2) * sim.dt) < 4 * sd / math.sqrt(len(rets))
    assert abs(statistics.stdev(rets) / sd - 1) < 0.02

def test_same_sector_correlation():
    sim = GBMSimulator(seed=1, event_probability=0.0)
    for t in ("AAPL", "MSFT", "JPM"):
        sim.add(t, SEED_PROFILES[t])
    prev = {t: sim.price(t) for t in ("AAPL", "MSFT", "JPM")}
    r = {t: [] for t in prev}
    for _ in range(20_000):
        for t, p in sim.step().items():
            r[t].append(math.log(p / prev[t])); prev[t] = p
    assert abs(statistics.correlation(r["AAPL"], r["MSFT"]) - 0.50) < 0.03
    assert abs(statistics.correlation(r["AAPL"], r["JPM"]) - 0.25) < 0.03
```
