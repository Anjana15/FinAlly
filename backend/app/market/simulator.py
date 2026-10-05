"""Default price source: correlated GBM with random jump events."""

from __future__ import annotations

import asyncio
import logging
import math
import random
from collections.abc import Iterable
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
