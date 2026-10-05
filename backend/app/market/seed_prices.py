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
