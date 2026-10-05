# Massive (formerly Polygon.io) API — Stock Prices Reference

Research notes for the FinAlly market-data layer. This covers the endpoints for getting **real-time and end-of-day prices for multiple tickers**, plus the plan and rate-limit rules that decide which endpoints we can use. Researched 2026-10-05 against `https://massive.com/docs` (machine-readable index: `https://massive.com/docs/llms.txt`; each doc page is also served as raw Markdown by appending `.md`).

> **Rebrand:** Polygon.io became Massive.com on 2025-10-30. Existing keys keep working. The API base is now `https://api.massive.com`, and `https://api.polygon.io` stays supported "for an extended period". The Python SDK moved from `polygon-api-client` to `massive` (`pip install -U massive`, `from massive import RESTClient`). Paths, parameters and response shapes did not change.

---

## 1. TL;DR for FinAlly

| Need | Endpoint | Calls per cycle | Plans |
|---|---|---|---|
| Live price, many tickers (**primary**) | `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,…` | **1** for any number of tickers | Starter+ (15-min delayed on Starter/Developer, real-time on Advanced/Business). **Not on free Basic.** |
| Live price, many tickers (alternative) | `GET /v3/snapshot?ticker.any_of=AAPL,MSFT,…` (≤250) | 1 | Starter+ (same as above) |
| End-of-day close, all tickers | `GET /v2/aggs/grouped/locale/us/market/stocks/{date}` | **1** for the whole market | **All plans, including free Basic** |
| Previous close, one ticker | `GET /v2/aggs/ticker/{ticker}/prev` | 1 per ticker | All plans |
| Open/close for one ticker on a date | `GET /v1/open-close/{ticker}/{date}` | 1 per ticker | All plans |
| Historical bars | `GET /v2/aggs/ticker/{ticker}/range/{mult}/{timespan}/{from}/{to}` | 1 per ticker | All plans |
| Market open/closed | `GET /v1/marketstatus/now` | 1 | All plans |

**Key consequences:**

1. **The full-market snapshot with a `tickers=` filter is the right primary endpoint.** One request returns the whole watchlist, so a 10-ticker (or 100-ticker) watchlist costs one call per poll.
2. **The free Basic tier cannot use snapshots.** It only gets end-of-day data at 5 requests per minute. PLAN.md §6 says "Free tier (5 calls/min): poll every 15 seconds". That polling rate fits the budget (4 calls/min), but the snapshot endpoint returns `403 NOT_AUTHORIZED` on Basic. On a free key the best we can do is **end-of-day prices** from the grouped-daily endpoint (one call covers every ticker), and those don't change during the day. The client must detect this and degrade explicitly. See §7.
3. Per-ticker endpoints (`/prev`, `/v2/last/trade/{t}`) cost N calls per cycle. With 10 tickers they break the free-tier budget immediately, so don't use them for polling.

---

## 2. Basics

### Base URL & authentication

```
https://api.massive.com
```

Either form of auth works on every REST endpoint:

```bash
# Query parameter
curl "https://api.massive.com/v1/marketstatus/now?apiKey=$MASSIVE_API_KEY"

# Header (preferred: keeps the key out of URLs and access logs)
curl -H "Authorization: Bearer $MASSIVE_API_KEY" "https://api.massive.com/v1/marketstatus/now"
```

The official Python SDK sends `Authorization: Bearer …` and reads `MASSIVE_API_KEY` from the environment by default. That's the same variable name FinAlly uses.

### Plans (stocks)

| Plan | Snapshot endpoints | Recency | Aggregates history | Rate limit |
|---|---|---|---|---|
| **Basic (free)** | ✗ | End-of-day | 2 years | **5 req/min** |
| Starter | ✓ | 15-minute delayed | 5 years | unlimited |
| Developer | ✓ | 15-minute delayed | 10 years | unlimited |
| Advanced | ✓ | Real-time | all (from 2003-09-10) | unlimited |
| Business | ✓ (+ `fmv`) | Real-time | all | unlimited |

- Rate limits are counted **per asset class**. An account with no stocks subscription is on the stocks Basic tier.
- Paid tiers are "unlimited", but Massive still expects reasonable use. For a UI that refreshes every few seconds, polling every 2–5 s is plenty.
- `lastTrade` / `lastQuote` inside snapshots are only returned if the plan includes trades/quotes. Lower tiers may get a snapshot without `lastTrade`, so the parser must fall back to bar closes (§6).
- `GET /v2/last/trade/{ticker}` is **not** on Basic or Starter.

### Errors

| HTTP | Meaning | Typical body |
|---|---|---|
| 200 | OK (`"status": "OK"`; some endpoints use `"DELAYED"` on delayed plans) | data |
| 400 | Bad parameter | `{"status":"ERROR","message":"…"}` |
| 401 | Missing or unknown key | `{"status":"ERROR","request_id":"…","error":"Unknown API Key"}` |
| 403 | Key valid but plan not entitled to this endpoint or recency | `{"status":"NOT_AUTHORIZED","message":"You are not entitled to this data. Please upgrade your plan at https://massive.com/pricing"}` |
| 429 | Over the per-minute limit (Basic only) | "You've exceeded the maximum requests per minute, please wait or upgrade your subscription to continue." |
| 5xx | Transient server error | — |

Treat **401 and 403 as non-retryable configuration errors**. Back off on 429 and 5xx. The official SDK retries 413/429/499/500/502/503/504 three times with a 0.1 s exponential backoff. That's too aggressive for a 5/min budget, so our client handles retries itself (§8).

### Timestamps & symbols

- Snapshot `updated` and `lastTrade.t` / `lastQuote.t` are **Unix nanoseconds**. Aggregate bar `t` (including snapshot `min.t`) is **Unix milliseconds**.
- Tickers are **case-sensitive** and must be upper-case (`AAPL`, `BRK.B`).
- A ticker that doesn't exist is **silently left out** of the multi-ticker snapshot response (no error). Detect missing tickers by diffing requested and returned symbols.
- Snapshot data is **cleared daily at ~3:30 AM ET** and refills as exchanges report, as early as 4:00 AM ET. In that gap `day` can be empty or zero while `prevDay` is still valid.

---

## 3. Real-time / delayed prices for multiple tickers

### 3.1 Full Market Snapshot (primary endpoint)

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

| Param | Type | Notes |
|---|---|---|
| `tickers` | comma-separated string | Case-sensitive, e.g. `AAPL,TSLA,GOOG`. Empty or omitted means **all ~10,000+ tickers** (a large payload; always pass the list). |
| `include_otc` | bool | Default `false`. |

```bash
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,NVDA"
```

Response (trimmed from the docs sample):

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "BCAT",
      "todaysChange": -0.124,
      "todaysChangePerc": -0.601,
      "updated": 1605192894630916600,
      "day":     {"o": 20.64, "h": 20.64, "l": 20.506, "c": 20.506, "v": 37216, "vw": 20.616},
      "prevDay": {"o": 20.79, "h": 21,    "l": 20.5,   "c": 20.63,  "v": 292738, "vw": 20.6939},
      "min":     {"t": 1684428600000, "o": 20.506, "h": 20.506, "l": 20.506, "c": 20.506, "v": 5000, "vw": 20.5105, "n": 1, "av": 37216},
      "lastTrade": {"t": 1605192894630916600, "p": 20.506, "s": 2416, "x": 4, "c": [14, 41], "i": "71675577320245"},
      "lastQuote": {"t": 1605192959994246100, "p": 20.5, "s": 13, "P": 20.6, "S": 22}
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `lastTrade.p` | Last trade price. Best "current price", **if the plan includes trades**. |
| `lastQuote.p` / `lastQuote.P` | Bid / ask (lower-case = bid, upper-case = ask). Only if the plan includes quotes. |
| `min.c` | Close of the most recent minute bar |
| `day.c` | Latest close of today's running daily bar |
| `prevDay.c` | Previous session's close. **Reference for daily change %.** |
| `todaysChange`, `todaysChangePerc` | Change vs `prevDay.c` (percent is already ×100) |
| `updated` | Last-update time, ns |
| `fmv` | Fair market value (Business only) |

Single ticker variant: `GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}`. It returns the same object under `"ticker"` instead of a `"tickers"` array.

### 3.2 Unified Snapshot (v3, alternative)

```
GET /v3/snapshot?ticker.any_of=AAPL,MSFT,NVDA&limit=250
```

- Up to **250 tickers** per call via `ticker.any_of`. Paginated with `next_url`. Plan access is the same as 3.1.
- Snake_case fields: `last_trade.price`, `last_minute.close`, `session.close`, `session.previous_close`, `session.change_percent`, `market_status` (`open` / `closed` / `early_trading` / `late_trading`).
- **Unknown tickers come back as error rows** (`{"ticker":"TSLAAPL","error":"NOT_FOUND","message":"Ticker not found."}`). That's nicer for validating user-added symbols.
- Use it if per-ticker errors or `market_status` become important. Otherwise 3.1 is simpler and returns everything we need.

### 3.3 Last Trade (per ticker, don't poll with it)

```
GET /v2/last/trade/{ticker}   →  {"results": {"T": "AAPL", "p": 129.8473, "s": 25, "t": 1617901342969834000, ...}}
```

One call per ticker, and not available on Basic or Starter. Listed for completeness only.

### 3.4 WebSocket (not used)

`wss://socket.massive.com/stocks` (delayed: `wss://delayed.massive.com/stocks`) streams trades (`T.*`), quotes (`Q.*`) and per-second/minute aggregates (`A.*`, `AM.*`). It needs a paid plan and a persistent connection. PLAN.md deliberately picks REST polling, so we only mention it here as a possible future upgrade.

---

## 4. End-of-day prices for multiple tickers

### 4.1 Daily Market Summary / "grouped daily" (one call, all tickers)

```
GET /v2/aggs/grouped/locale/us/market/stocks/{date}     # date = YYYY-MM-DD
    ?adjusted=true&include_otc=false
```

Returns one OHLCV bar per US ticker for that trading day. Available on **all plans** (Basic gets it once the day has closed). Filter client-side to the tickers you care about.

```json
{
  "status": "OK", "adjusted": true, "queryCount": 3, "resultsCount": 3,
  "results": [
    {"T": "VSAT", "o": 34.9, "h": 35.47, "l": 34.21, "c": 34.24, "v": 312583, "vw": 34.4736, "n": 4966, "t": 1602705600000}
  ]
}
```

- `T` = ticker, `c` = close, `t` = ms timestamp.
- Weekends and holidays return `resultsCount: 0` with no `results` key. To find the latest trading day, step back one day at a time until results appear (at most ~4 tries across a long weekend). Or call `/v1/marketstatus/upcoming` / market holidays first.
- On Basic, asking for **today** before the close typically returns empty or 403. Start from yesterday.

### 4.2 Previous Day Bar (per ticker)

```
GET /v2/aggs/ticker/{ticker}/prev?adjusted=true
→ {"ticker":"AAPL","resultsCount":1,"results":[{"T":"AAPL","o":115.55,"h":117.59,"l":114.13,"c":115.97,"v":131704427,"vw":116.3058,"t":1605042000000}]}
```

All plans. Simple, but N calls for N tickers.

### 4.3 Daily Ticker Summary / open-close (per ticker)

```
GET /v1/open-close/{ticker}/{date}
→ {"status":"OK","symbol":"AAPL","from":"2023-01-09","open":324.66,"high":326.2,"low":322.3,"close":325.12,"volume":26122646,"preMarket":324.5,"afterHours":322.1}
```

All plans. Includes pre-market and after-hours prices.

### 4.4 Custom bars (history, per ticker)

```
GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}?adjusted=true&sort=asc&limit=5000
# e.g. /v2/aggs/ticker/AAPL/range/1/day/2026-09-01/2026-10-02
```

- `timespan` ∈ `second, minute, hour, day, week, month, quarter, year`. `from` / `to` are `YYYY-MM-DD` or ms timestamps.
- `t` is the bar **start**, in ms. Pagination via `next_url`.
- Useful later for seeding the main chart with history. Not needed for v1.

---

## 5. Market status

```
GET /v1/marketstatus/now
→ {"market":"extended-hours","earlyHours":false,"afterHours":true,
   "exchanges":{"nasdaq":"extended-hours","nyse":"extended-hours","otc":"closed"},
   "serverTime":"2020-11-10T17:37:37-05:00"}
```

`market` ∈ `open`, `closed`, `extended-hours`. All plans. It's handy for slowing the poll rate down when the market is closed. It costs a request, though, so on Basic don't call it every cycle.

---

## 6. Choosing "the price" from a snapshot

Snapshot fields differ by plan and time of day, so pick the first one that's present and positive:

```
lastTrade.p  →  min.c  →  day.c  →  prevDay.c
```

The reference price for daily change is `prevDay.c`. Timestamp: `updated` (ns), falling back to `lastTrade.t` (ns), then `min.t` (ms), then "now".

```python
import time

def extract_quote(snap: dict) -> tuple[float, float, float | None] | None:
    """Return (price, unix_ts_seconds, prev_close) from one snapshot entry, or None."""
    def pos(x):  # positive number or None
        return x if isinstance(x, (int, float)) and x > 0 else None

    trade, minute = snap.get("lastTrade") or {}, snap.get("min") or {}
    day, prev = snap.get("day") or {}, snap.get("prevDay") or {}

    price = pos(trade.get("p")) or pos(minute.get("c")) or pos(day.get("c")) or pos(prev.get("c"))
    if price is None:
        return None

    if pos(snap.get("updated")):
        ts = snap["updated"] / 1e9
    elif pos(trade.get("t")):
        ts = trade["t"] / 1e9
    elif pos(minute.get("t")):
        ts = minute["t"] / 1e3
    else:
        ts = time.time()
    return float(price), ts, pos(prev.get("c"))
```

---

## 7. Free-tier (Basic) strategy

| Approach | Calls/cycle (10 tickers) | Works on Basic? |
|---|---|---|
| Full-market snapshot | 1 | ✗ (403) |
| Per-ticker `/prev` | 10 | ✓, but only one cycle per ~2 min, and the data doesn't change anyway |
| **Grouped daily for the last trading day** | 1 (plus a few to find the date) | **✓** |

Recommended behaviour for the Massive data source:

1. On startup, call the snapshot endpoint.
2. If it returns **403**, switch to **EOD mode**. Load the last trading day's grouped-daily bars once, write those closes into the price cache, and refresh roughly every 30–60 minutes (the data only changes once a day). Report source status `degraded` with the message *"Massive plan does not include snapshots; showing end-of-day prices"* so the UI can show it.
3. If it returns **401**, report status `error` ("invalid MASSIVE_API_KEY") and stop polling. **Don't** silently fall back to the simulator: a user who set a key expects real data, and mixing simulated prices into a "real" portfolio is misleading (REVIEW.md §2).
4. On **429**, honour `Retry-After` if present. Otherwise wait 60 s.

---

## 8. Code examples

### 8.1 Async client with `httpx` (recommended for FinAlly)

The official SDK is synchronous (urllib3). We only need a handful of endpoints, and `httpx.AsyncClient` fits FastAPI's event loop and is easy to mock in tests with `httpx.MockTransport`.

```python
# backend/app/market/massive_client.py
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

import httpx

BASE_URL = "https://api.massive.com"
SNAPSHOT_PATH = "/v2/snapshot/locale/us/markets/stocks/tickers"


class MassiveError(Exception):
    """Any non-success response from Massive."""


class MassiveAuthError(MassiveError):
    """401: missing/invalid key. Not retryable."""


class MassiveNotEntitledError(MassiveError):
    """403: plan does not include this endpoint/recency. Not retryable."""


class MassiveRateLimitError(MassiveError):
    def __init__(self, message: str, retry_after: float | None):
        super().__init__(message)
        self.retry_after = retry_after


class MassiveClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject MockTransport
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
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
            ra = r.headers.get("Retry-After")
            raise MassiveRateLimitError(msg, float(ra) if ra and ra.isdigit() else None)
        raise MassiveError(f"HTTP {r.status_code}: {msg}")

    # ---- real-time / delayed -------------------------------------------------
    async def get_snapshots(self, tickers: Iterable[str]) -> list[dict]:
        """One call for all tickers. Unknown tickers are simply absent."""
        symbols = sorted({t.upper() for t in tickers})
        if not symbols:
            return []
        data = await self._get(SNAPSHOT_PATH, {"tickers": ",".join(symbols)})
        return data.get("tickers") or []

    # ---- end of day ------------------------------------------------------------
    async def get_grouped_daily(self, day: date, *, adjusted: bool = True) -> list[dict]:
        data = await self._get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}",
            {"adjusted": str(adjusted).lower()},
        )
        return data.get("results") or []

    async def get_latest_eod(
        self, tickers: Iterable[str], *, start: date | None = None, max_lookback: int = 5
    ) -> tuple[date, dict[str, dict]]:
        """Walk back from `start` (default: yesterday) to the last day with data."""
        wanted = {t.upper() for t in tickers}
        day = start or (date.today() - timedelta(days=1))
        for _ in range(max_lookback):
            rows = await self.get_grouped_daily(day)
            if rows:
                return day, {r["T"]: r for r in rows if r.get("T") in wanted}
            day -= timedelta(days=1)
        raise MassiveError(f"no grouped-daily data in the {max_lookback} days before {start}")

    async def get_previous_close(self, ticker: str) -> dict | None:
        data = await self._get(f"/v2/aggs/ticker/{ticker.upper()}/prev", {"adjusted": "true"})
        results = data.get("results") or []
        return results[0] if results else None

    async def get_market_status(self) -> dict:
        return await self._get("/v1/marketstatus/now")


def _error_message(r: httpx.Response) -> str:
    try:
        body = r.json()
        return body.get("message") or body.get("error") or r.text
    except ValueError:
        return r.text
```

Usage:

```python
import asyncio, os

async def main():
    client = MassiveClient(os.environ["MASSIVE_API_KEY"])
    try:
        snaps = await client.get_snapshots(["AAPL", "MSFT", "NVDA"])
        for s in snaps:
            print(s["ticker"], extract_quote(s))
    except MassiveNotEntitledError:
        day, bars = await client.get_latest_eod(["AAPL", "MSFT", "NVDA"])
        for t, bar in bars.items():
            print(day, t, bar["c"])
    finally:
        await client.aclose()

asyncio.run(main())
```

### 8.2 Official SDK equivalents (`pip install -U massive`)

Useful for quick exploration in a REPL. The SDK is synchronous; in FastAPI it would need `asyncio.to_thread`.

```python
from massive import RESTClient

client = RESTClient()  # reads MASSIVE_API_KEY; or RESTClient(api_key="...")

# Real-time/delayed: multiple tickers in one call -> list[TickerSnapshot]
for s in client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT", "NVDA"]):
    price = (s.last_trade and s.last_trade.price) or (s.min and s.min.close) or (s.day and s.day.close)
    print(s.ticker, price, s.prev_day.close if s.prev_day else None, s.todays_change_percent)

# Single ticker snapshot
snap = client.get_snapshot_ticker("stocks", "AAPL")

# End of day: whole market for a date -> list[GroupedDailyAgg] (.ticker, .close, ...)
eod = {a.ticker: a.close for a in client.get_grouped_daily_aggs("2026-10-02")
       if a.ticker in {"AAPL", "MSFT", "NVDA"}}

# Previous close (per ticker) -> PreviousCloseAgg; open/close for a date -> DailyOpenCloseAgg
prev = client.get_previous_close_agg("AAPL")
oc = client.get_daily_open_close_agg("AAPL", "2026-10-02")

# Historical daily bars (auto-paginating iterator)
bars = list(client.list_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-02", limit=5000))

# Debug the raw HTTP exchange
debug_client = RESTClient(trace=True, verbose=True)
```

SDK model field names are snake_case (`last_trade.price`, `prev_day.close`, `todays_change_percent`, `min.close`). The raw JSON uses the short keys shown in §3.

### 8.3 Testing without a key

```python
import httpx, pytest

SAMPLE = {"status": "OK", "count": 1, "tickers": [{
    "ticker": "AAPL", "updated": 1759500000000000000,
    "lastTrade": {"p": 191.23, "t": 1759500000000000000},
    "prevDay": {"c": 189.50}, "day": {"c": 191.20}, "min": {"c": 191.21, "t": 1759499940000},
}]}

@pytest.mark.asyncio
async def test_get_snapshots_parses_price():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/stocks/tickers")
        assert request.url.params["tickers"] == "AAPL"
        assert request.headers["Authorization"] == "Bearer test"
        return httpx.Response(200, json=SAMPLE)

    client = MassiveClient("test", transport=httpx.MockTransport(handler))
    [snap] = await client.get_snapshots(["aapl"])
    assert extract_quote(snap) == (191.23, 1759500000.0, 189.50)

@pytest.mark.asyncio
async def test_403_raises_not_entitled():
    transport = httpx.MockTransport(lambda r: httpx.Response(403, json={"status": "NOT_AUTHORIZED", "message": "upgrade"}))
    with pytest.raises(MassiveNotEntitledError):
        await MassiveClient("k", transport=transport).get_snapshots(["AAPL"])
```

---

## 9. Request budget for FinAlly

Let *N* be the number of tracked tickers (watchlist ∪ open positions).

| Mode | Calls/min | Fits budget? |
|---|---|---|
| Paid, snapshot every 5 s | 12 (independent of N) | ✓ (unlimited) |
| Paid, snapshot every 2 s | 30 | ✓ |
| Basic, snapshot every 15 s | 4 | ✓ on budget, **but 403**, so not possible |
| Basic, EOD grouped daily every 30 min (≤5 lookback calls per refresh) | ≤ 0.17 | ✓ |
| Basic, per-ticker `/prev` every 15 s | 4·N = 40 | ✗ |

Default `MASSIVE_POLL_INTERVAL` = **5 s** for paid keys. The interval only matters in snapshot mode. EOD mode uses its own slow refresh.

---

## Sources

- Docs index: https://massive.com/docs/llms.txt
- Full Market Snapshot: https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot
- Single Ticker Snapshot: https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot
- Unified Snapshot: https://massive.com/docs/rest/stocks/snapshots/unified-snapshot
- Daily Market Summary: https://massive.com/docs/rest/stocks/aggregates/daily-market-summary
- Previous Day Bar: https://massive.com/docs/rest/stocks/aggregates/previous-day-bar
- Daily Ticker Summary: https://massive.com/docs/rest/stocks/aggregates/daily-ticker-summary
- Custom Bars: https://massive.com/docs/rest/stocks/aggregates/custom-bars
- Last Trade: https://massive.com/docs/rest/stocks/trades-quotes/last-trade
- Market Status: https://massive.com/docs/rest/stocks/market-operations/market-status
- Rate limits: https://massive.com/knowledge-base/article/what-is-the-request-limit-for-massives-restful-apis
- Python client: https://github.com/massive-com/client-python
