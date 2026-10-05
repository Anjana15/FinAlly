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
