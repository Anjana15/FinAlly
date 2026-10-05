import httpx
import pytest

from app.market.massive_client import (
    MassiveAuthError,
    MassiveClient,
    MassiveError,
    MassiveNotEntitledError,
    MassiveRateLimitError,
    extract_quote,
)
from app.market.models import SourceState

from .conftest import make_massive, snapshot_row


# ---- extract_quote ---------------------------------------------------------
def test_extract_prefers_last_trade():
    assert extract_quote(snapshot_row("AAPL", 191.23, 189.5)) == (191.23, 1_759_500_000.0, 189.5)


def test_extract_falls_back_to_bars():
    snap = {"ticker": "AAPL", "min": {"c": 10.5, "t": 1_759_499_940_000}, "day": {"c": 10.4}, "prevDay": {"c": 10.0}}
    assert extract_quote(snap) == (10.5, 1_759_499_940.0, 10.0)
    assert extract_quote({"ticker": "AAPL", "day": {"c": 0}, "prevDay": {"c": 9.0}})[0] == 9.0
    assert extract_quote({"ticker": "AAPL", "day": {"c": 10.4}})[0] == 10.4


def test_extract_timestamp_fallbacks():
    assert extract_quote({"lastTrade": {"p": 5.0, "t": 2_000_000_000_000_000_000}})[1] == 2_000_000_000.0
    ts = extract_quote({"day": {"c": 5.0}})[1]  # nothing usable: falls back to "now"
    assert ts > 1_700_000_000


def test_extract_unusable():
    assert extract_quote({"ticker": "AAPL", "day": {"c": 0}}) is None
    assert extract_quote({"ticker": "AAPL", "lastTrade": {"p": True}, "day": {"c": "x"}}) is None
    assert extract_quote({"ticker": "AAPL"}) is None


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


async def test_client_empty_ticker_list_makes_no_request():
    def handler(r):
        raise AssertionError("no request expected")

    client = MassiveClient("k", transport=httpx.MockTransport(handler))
    assert await client.get_snapshots([]) == []
    await client.aclose()


@pytest.mark.parametrize(
    "status,exc",
    [(401, MassiveAuthError), (403, MassiveNotEntitledError), (429, MassiveRateLimitError), (500, MassiveError)],
)
async def test_client_error_mapping(status, exc):
    t = httpx.MockTransport(lambda r: httpx.Response(status, json={"message": "nope"}))
    client = MassiveClient("k", transport=t)
    with pytest.raises(exc):
        await client.get_snapshots(["AAPL"])
    await client.aclose()


async def test_client_429_retry_after_and_plain_text_error():
    t = httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "7"}, text="slow"))
    client = MassiveClient("k", transport=t)
    with pytest.raises(MassiveRateLimitError) as e:
        await client.get_snapshots(["AAPL"])
    assert e.value.retry_after == 7.0 and str(e.value) == "slow"
    await client.aclose()


async def test_client_grouped_daily_path_and_empty():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append((r.url.path, r.url.params["adjusted"]))
        return httpx.Response(200, json={"resultsCount": 0})

    client = MassiveClient("k", transport=httpx.MockTransport(handler))
    from datetime import date

    assert await client.get_grouped_daily(date(2026, 10, 2)) == []
    assert seen == [("/v2/aggs/grouped/locale/us/market/stocks/2026-10-02", "true")]
    await client.aclose()


# ---- data source -----------------------------------------------------------
async def test_snapshot_reference_is_prev_close(cache, fake_massive):
    fake_massive.prices["AAPL"] = 105.0
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    q = cache.get("AAPL")
    assert (q.price, q.reference_price, q.change_percent) == (105.0, 100.0, 5.0)
    assert src.status().state == SourceState.OK
    assert src.max_quote_age == 25.0
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


async def test_bad_rows_are_skipped(cache):
    def handler(r):
        rows = [snapshot_row("AAPL", 10.0), {"ticker": "MSFT", "day": {"c": 0}}, snapshot_row("OLD", 5.0)]
        return httpx.Response(200, json={"tickers": rows})

    src = make_massive(cache, handler)
    await src.start(["AAPL", "MSFT"])
    assert "MSFT" not in cache and "OLD" not in cache  # unusable row; untracked row
    assert cache.get("AAPL").price == 10.0
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


async def test_429_without_retry_after_waits_60s(cache):
    src = make_massive(cache, lambda r: httpx.Response(429, json={"message": "slow"}))
    await src.start(["AAPL"])
    assert src._backoff == 60.0
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


async def test_network_error_and_bad_json_degrade(cache):
    def boom(r):
        raise httpx.ConnectError("down")

    src = make_massive(cache, boom)
    await src.start(["AAPL"])
    assert src.status().state == SourceState.DEGRADED and src._backoff == 5.0
    await src.stop()

    src = make_massive(cache, lambda r: httpx.Response(200, text="not json"))
    await src.start(["AAPL"])
    assert src.status().state == SourceState.DEGRADED
    await src.stop()


async def test_add_ticker_skips_request_while_backing_off(cache, fake_massive):
    fake_massive.status_code = 503
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    n = len(fake_massive.calls)
    await src.add_ticker("MSFT")
    assert len(fake_massive.calls) == n and "MSFT" in src.tickers()
    await src.stop()


async def test_add_ticker_fetches_only_that_ticker(cache, fake_massive):
    src = make_massive(cache, fake_massive)
    await src.start(["AAPL"])
    await src.add_ticker("MSFT")
    assert fake_massive.calls[-1].url.params["tickers"] == "MSFT"
    assert cache.get("MSFT") is not None
    await src.stop()


async def test_removed_ticker_not_resurrected_by_inflight_response(cache):
    src = None

    async def noop():
        pass

    def handler(r):
        return httpx.Response(200, json={"tickers": [snapshot_row("AAPL", 10.0)]})

    src = make_massive(cache, handler)
    await src.start(["AAPL"])
    await src.remove_ticker("AAPL")
    src._tickers.add("MSFT")  # something is tracked so the fetch proceeds
    await src._fetch()
    assert "AAPL" not in cache
    await src.stop()


async def test_poll_loop_keeps_polling(cache, fake_massive):
    src = make_massive(cache, fake_massive, poll_interval=1.0)
    src._poll_interval = 0.01  # the constructor clamps to >= 1 s; shorten for the test
    await src.start(["AAPL"])
    import asyncio

    await asyncio.sleep(0.1)
    assert len(fake_massive.calls) > 2
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

    await src.add_ticker("ZZZZ")  # not in the bars
    assert "ZZZZ" not in cache and "No data for: ZZZZ" in src.status().message
    await src.stop()


async def test_eod_no_data_in_lookback_degrades(cache):
    def handler(r):
        if "snapshot" in r.url.path:
            return httpx.Response(403, json={"message": "upgrade"})
        return httpx.Response(200, json={"resultsCount": 0})

    src = make_massive(cache, handler)
    await src.start(["AAPL"])
    assert "AAPL" not in cache and src.status().state == SourceState.DEGRADED
    await src.stop()
