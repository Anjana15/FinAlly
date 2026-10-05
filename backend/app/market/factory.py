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
