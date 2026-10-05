import asyncio
import math
import statistics

import pytest

from app.market.cache import PriceCache
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


def test_empty_step_returns_empty():
    assert GBMSimulator(seed=1).step() == {}


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


def test_invalid_weights_rejected():
    with pytest.raises(ValueError):
        GBMSimulator(market_weight=0.9, sector_weights={"tech": 0.9})


def test_unknown_ticker_profile_stable():
    a, b = profile_for("ZZZZ", seed=1), profile_for("ZZZZ", seed=1)
    assert a == b and 50 <= a.price <= 300 and a.sector == "other"
    assert 0.25 <= a.volatility <= 0.45
    assert profile_for("ZZZZ", seed=2) != a


def test_seed_table_complete_and_weights_valid():
    assert set(DEFAULT_WATCHLIST) <= set(SEED_PROFILES)
    assert all(MARKET_WEIGHT**2 + b**2 <= 1 for b in SECTOR_WEIGHTS.values())
    assert all(p.sector in SECTOR_WEIGHTS for p in SEED_PROFILES.values())


def test_park_and_resume():
    sim = GBMSimulator(seed=2)
    sim.add("AAPL", SEED_PROFILES["AAPL"])
    run(sim, 10)
    at_removal = sim.price("AAPL")
    sim.remove("AAPL")
    assert "AAPL" not in sim and sim.price("AAPL") is None
    assert sim.add("AAPL", SEED_PROFILES["AAPL"]) == at_removal


def test_add_is_idempotent():
    sim = GBMSimulator(seed=2)
    sim.add("AAPL", SEED_PROFILES["AAPL"])
    run(sim, 3)
    p = sim.price("AAPL")
    assert sim.add("AAPL", SEED_PROFILES["AAPL"]) == p
    sim.remove("NOPE")  # no-op


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


async def test_source_add_remove(cache):
    src = SimulatorDataSource(cache, seed=1)
    await src.start([])
    await src.add_ticker("NVDA")
    assert cache.get("NVDA").price == 120.0
    await src.remove_ticker("NVDA")
    assert "NVDA" not in cache and src.tickers() == frozenset()
    await src.stop()


def test_max_quote_age_scales_with_interval(cache):
    assert SimulatorDataSource(cache, tick_interval=0.5).max_quote_age == 5.0
    assert SimulatorDataSource(cache, tick_interval=2.0).max_quote_age == 20.0


async def test_source_loop_survives_tick_error(cache):
    class Boom(GBMSimulator):
        calls = 0

        def step(self):
            Boom.calls += 1
            if Boom.calls == 1:
                raise RuntimeError("boom")
            return super().step()

    src = SimulatorDataSource(cache, tick_interval=0.01, engine=Boom(seed=1, tick_seconds=0.01))
    await src.start(["AAPL"])
    await asyncio.sleep(0.1)
    assert Boom.calls > 2  # loop kept going after the exception
    await src.stop()


async def test_source_loop_runs():
    cache = PriceCache()
    src = SimulatorDataSource(cache, seed=1, tick_interval=0.01)
    await src.start(["AAPL"])
    v = cache.version
    await asyncio.sleep(0.1)
    assert cache.version > v + 3
    await src.stop()
