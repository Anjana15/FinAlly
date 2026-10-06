# Team Contract — FinAlly build

Written by the team lead on 2026-10-06. This is the **binding cross-agent contract** for the parallel build. It settles every **[Contract]** item in PLAN §13 and the review answers recorded there. Where this file and PLAN.md disagree, this file wins. Market-data details come from `MARKET_DATA_DESIGN.md`, and that code already exists in `backend/app/market/` with 86 passing tests. **Don't rewrite it**; ask the lead if you need a change.

If you need to change something here, edit this file, add a line to the **Changelog** at the bottom, and message every affected team member.

---

## 1. Team and file ownership

Only edit files you own. If you need a change in someone else's files, message that owner, or the lead if you're blocked.

| Member (agent name) | Owns |
|---|---|
| **lead** | `planning/`, `CLAUDE.md`, `README.md`, coordination |
| **db-engineer** | `backend/app/db/**`, `backend/tests/db/**` |
| **backend-api** | `backend/app/main.py`, `backend/app/api/**` (routes, except chat), `backend/app/services/**` (trade service, valuation, snapshot loop), `backend/tests/api/**`, `backend/tests/services/**`, `backend/pyproject.toml` deps (others ask backend-api to add deps, or run `uv add` themselves and tell backend-api) |
| **llm-engineer** | `backend/app/llm/**` (schema, prompt, LiteLLM client, mock, chat service, and the chat router at `backend/app/llm/router.py`), `backend/tests/llm/**` |
| **frontend** | `frontend/**` |
| **devops** | `Dockerfile`, `.dockerignore`, `scripts/**`, `test/docker-compose.test.yml`, `.gitignore`, `.env.example` |
| **integration-tester** | `test/**` except `docker-compose.test.yml` (Playwright config, specs, `test/package.json`), `planning/E2E_REPORT.md` |

`backend/app/market/**` is frozen (lead-owned). `backend/market_demo.py` is a dev tool; leave it alone.

## 2. Backend module interfaces (Python)

Implement these **exact signatures**, so dependants can code against them before they exist. All DB functions are **synchronous** (stdlib `sqlite3`). `user_id` defaults to `"default"` everywhere.

### 2.1 `app.db` (db-engineer)

```python
# app/db/__init__.py re-exports all of these
DB_PATH: str  # env FINALLY_DB_PATH, default "<repo>/db/finally.db" locally; "/app/db/finally.db" in Docker (set by Dockerfile via FINALLY_DB_PATH)

def init_db(path: str | None = None) -> None
    # Create the parent dir, the tables (IF NOT EXISTS) and the seed (only if users_profile is empty). Idempotent. Called once from lifespan.
def get_conn() -> sqlite3.Connection
    # A connection to DB_PATH (or to the path init_db was given): row_factory=sqlite3.Row, foreign_keys on, WAL mode, check_same_thread=False.
    # One shared connection per process is fine (single worker, asyncio).

# reads
def get_cash(conn, user_id="default") -> float
def get_watchlist(conn, user_id="default") -> list[str]                  # tickers, ordered by added_at
def get_positions(conn, user_id="default") -> list[dict]                 # [{"ticker","quantity","avg_cost"}], qty > 0, ordered by ticker
def get_position(conn, ticker, user_id="default") -> dict | None
def tracked_tickers(conn, user_id="default") -> set[str]                 # watchlist ∪ tickers with qty > 0
def get_snapshots(conn, user_id="default", limit=500) -> list[dict]      # [{"total_value","recorded_at"}] oldest→newest, the last `limit` rows
def get_recent_messages(conn, user_id="default", limit=20) -> list[dict] # [{"id","role","content","actions"(parsed dict|None),"created_at"}] oldest→newest
def get_trades(conn, user_id="default", limit=100) -> list[dict]         # newest first

# writes (each commits)
def add_watchlist(conn, ticker, user_id="default") -> bool               # True if inserted, False if already present
def remove_watchlist(conn, ticker, user_id="default") -> bool            # True if a row was deleted
def record_snapshot(conn, total_value: float, user_id="default") -> None
def add_message(conn, role, content, actions: dict | None = None, user_id="default") -> dict   # returns the stored row (same shape as get_recent_messages)

# the ONE atomic trade write: validation + cash + position + trades row, in a single transaction
class TradeError(Exception):
    code: str      # "insufficient_cash" | "insufficient_shares" | "invalid_quantity" | "invalid_side"
    detail: str
def apply_trade(conn, ticker, side, quantity, price, user_id="default") -> dict
    # Validates and writes atomically, or raises TradeError and writes nothing.
    # Returns {"id","ticker","side","quantity","price","executed_at","cash_balance","position": {"ticker","quantity","avg_cost"} | None}
```

Trade math (PLAN §13 #15, settled):
- `quantity` must be > 0 and finite; round it to 4 dp. If it rounds to 0, raise `invalid_quantity`.
- A buy costs `round(qty*price, 2)`. It needs `cost <= cash + 1e-9`. The new avg cost is the weighted average.
- A sell needs `qty <= held + 1e-6`. Avg cost stays the same. If the remaining |qty| is < 1e-6, **delete** the position row.
- Store cash rounded to 2 dp. Use ISO-8601 UTC timestamps with a `Z` suffix.

Schema: PLAN §7, with these changes. `users_profile` keeps `id` as the user key; that's the documented exception to the `user_id` rule. Use UUID text ids. There is no migration step.

### 2.2 `app.services` (backend-api)

```python
# app/services/trading.py — the ONE trade path, used by REST and by the LLM chat
async def execute_trade(app, ticker: str, side: str, quantity: float, user_id="default") -> dict
    # Never raises for business errors. Returns a TradeResult dict:
    #   success: {"status":"executed","ticker","side","quantity","price","executed_at","cash_balance"}
    #   failure: {"status":"failed","ticker","side","quantity","error": <code>,"detail": <msg>}
    # Steps: normalize_ticker (failure → "invalid_ticker") → price_for_trade (failure → "no_price"/"stale_price")
    #   → app.db.apply_trade (TradeError → its code) → on a successful buy, add_watchlist (PLAN §13 #7)
    #   → record_snapshot(mark_to_market total, if complete) → sync_tracked_tickers.

# app/services/watchlist.py — shared by REST and LLM
async def add_ticker(app, ticker, user_id="default") -> dict     # {"status":"added"|"exists"|"failed","ticker", "error"?, "detail"?}
async def remove_ticker(app, ticker, user_id="default") -> dict  # {"status":"removed"|"not_found"|"failed","ticker", "error"?, "detail"?}

# app/services/portfolio.py
def mark_to_market(cache, cash, positions) -> dict   # exactly as in MARKET_DATA_DESIGN §12
def portfolio_view(app, user_id="default") -> dict   # the GET /api/portfolio body (see §3)
async def portfolio_snapshot_loop(app, interval=30.0) -> None   # records a snapshot every 30 s, including at startup; skips if valuation is incomplete
```

`app` is the FastAPI app (`request.app`). It carries `app.state.prices` (PriceCache), `app.state.market` (MarketDataSource) and `app.state.shutting_down`.

### 2.3 `app.llm` (llm-engineer)

```python
# app/llm/router.py
router = APIRouter()   # POST /api/chat. backend-api includes it in main.py: `from app.llm.router import router as chat_router`
# app/llm/service.py
async def handle_chat(app, user_message: str, user_id="default") -> dict   # the POST /api/chat body (see §3)
```

The chat service calls `app.services.trading.execute_trade` and `app.services.watchlist.add_ticker/remove_ticker`. It **never** writes trades itself.

## 3. HTTP API (frontend ↔ backend)

All JSON, same origin, no auth. Prices are numbers in USD, and timestamps are ISO-8601 UTC strings. A **Quote** is exactly `PriceQuote.to_dict()`:
`{"ticker","price","previous_price","reference_price","change","change_percent","direction":"up"|"down"|"flat","timestamp"}`.

**Error shape** (every 4xx/5xx from our routes): `{"error": "<code>", "detail": "<human message>"}`. Return it with `JSONResponse(status_code=..., content=...)`, **not** `HTTPException(detail=...)`, because that would nest the body under `detail`.

| Method & path | Request | 200 response | Errors |
|---|---|---|---|
| `GET /api/health` | — | `{"status":"ok","market":{"source","state","message"}}` | — |
| `GET /api/stream/prices` | — | SSE, see MARKET_DATA_DESIGN §11.1 (already built) | — |
| `GET /api/watchlist` | — | `{"tickers":[{"ticker":"AAPL","quote":Quote\|null}, ...]}`, ordered by added_at | — |
| `POST /api/watchlist` | `{"ticker":"pypl"}` | `{"ticker":"PYPL","status":"added"\|"exists","quote":Quote\|null}` | 400 `invalid_ticker` |
| `DELETE /api/watchlist/{ticker}` | — | `{"ticker":"PYPL","status":"removed"}` | 404 `not_found`, 400 `invalid_ticker` |
| `GET /api/portfolio` | — | see below | — |
| `POST /api/portfolio/trade` | `{"ticker":"AAPL","side":"buy","quantity":1.5}` | TradeResult (`status:"executed"`) | 400 with `{"error":code,"detail"}` where code ∈ `invalid_ticker, invalid_side, invalid_quantity, insufficient_cash, insufficient_shares, no_price, stale_price` |
| `GET /api/portfolio/history` | `?limit=500` (max 2000) | `{"snapshots":[{"total_value":10000.0,"recorded_at":"..."}]}` oldest→newest | — |
| `GET /api/chat/history` | `?limit=50` | `{"messages":[ChatMessage...]}` oldest→newest | — |
| `POST /api/chat` | `{"message":"buy 1 AAPL"}` | ChatResponse, below | 400 `empty_message`; the LLM failing is **not** an HTTP error (see below) |

`GET /api/portfolio`:
```json
{"cash": 8100.25, "total_value": 10012.4, "valuation_complete": true,
 "positions": [{"ticker":"AAPL","quantity":10,"avg_cost":189.97,"price":191.2,
                "market_value":1912.0,"unrealized_pnl":12.3,"pnl_percent":0.65}]}
```
`pnl_percent` = (price − avg_cost)/avg_cost × 100 (PLAN §13 #6). An unpriced position has `price`/`market_value`/`unrealized_pnl`/`pnl_percent` = null, and then `total_value` is null.

**ChatResponse** / **ChatMessage** (the same object is stored in `chat_messages`):
```json
{"id":"uuid","role":"assistant","content":"Placing an order for 1 AAPL.","created_at":"...",
 "actions":{"trades":[ TradeResult, ... ],
            "watchlist_changes":[{"ticker":"PYPL","action":"add"|"remove","status":"added"|"exists"|"removed"|"not_found"|"failed","error"?,"detail"?}],
            "error": null}}
```
- User messages are stored with `actions: null`. `POST /api/chat` returns only the assistant message (the frontend already shows the user's text).
- LLM failure (exception, malformed JSON, missing key with mock off): return 200 with a friendly `content`, empty `trades`/`watchlist_changes`, and `actions.error` = `"llm_unavailable"` | `"llm_bad_response"` | `"llm_not_configured"`. Store it the same way.
- No second LLM call (PLAN §13 #9a). The UI shows a success/fail chip per action. The prompt tells the model to phrase actions as intent.

**Live header value** is computed client-side as `cash + Σ qty × live SSE price` (PLAN §13 #16). The client refetches `/api/portfolio` after each trade or chat action.

## 4. LLM structured output and mock (llm-engineer; integration-tester relies on it)

The Pydantic schema sent as `response_format` makes every field required, with possibly empty arrays (PLAN §13 #11):
`{"message": str, "trades": [{"ticker": str, "side": "buy"|"sell", "quantity": float}], "watchlist_changes": [{"ticker": str, "action": "add"|"remove"}]}`.
History: the last 20 messages, with assistant `actions` summarised into the context.

**`LLM_MOCK=true` deterministic rules.** Match case-insensitively on the user message and apply the **first** rule that matches:

| Pattern | Mock LLM output |
|---|---|
| `buy <qty> <TICKER>` (e.g. "buy 2 AAPL") | message `"Placing a buy order for <qty> <TICKER>."`, trades `[{TICKER, buy, qty}]` |
| `sell <qty> <TICKER>` | message `"Placing a sell order for <qty> <TICKER>."`, trades `[{TICKER, sell, qty}]` |
| `add <TICKER>` | message `"Adding <TICKER> to your watchlist."`, watchlist_changes `[{TICKER, add}]` |
| `remove <TICKER>` | message `"Removing <TICKER> from your watchlist."`, watchlist_changes `[{TICKER, remove}]` |
| anything else | message `"Mock response: I can help you analyze your portfolio, place trades, and manage your watchlist."`, no actions |

The mock output is then executed by the **real** action path, exactly like a real LLM reply.

## 5. Frontend build and serving (frontend ↔ backend-api ↔ devops)

- Next.js `output: 'export'`, `trailingSlash: true`, `images: { unoptimized: true }`. The build output goes to `frontend/out/`.
- The backend serves static files from the dir in env `FINALLY_STATIC_DIR` (default `<repo>/frontend/out` locally, `/app/static` in Docker). Mount `StaticFiles(directory=..., html=True)` at `/` **after** all API routers, and only if the directory exists, so dev and tests work without a build.
- In local dev the frontend can run `next dev` on :3000 with `rewrites` proxying `/api/*` to `http://localhost:8000`. Rewrites are ignored by export builds, so that's fine.
- **Stable selectors for E2E** (frontend must provide; integration-tester uses only these):
  - `data-testid="header-total-value"`, `"header-cash"`, `"connection-status"` (with attribute `data-state="connected"|"reconnecting"|"disconnected"`)
  - `"watchlist"`, a row per ticker: `data-testid="watchlist-row-<TICKER>"` containing `"price-<TICKER>"`; `"watchlist-add-input"`, `"watchlist-add-button"`, `"watchlist-remove-<TICKER>"`
  - `"main-chart"`, `"selected-ticker"`
  - `"trade-ticker-input"`, `"trade-quantity-input"`, `"trade-buy-button"`, `"trade-sell-button"`, `"trade-message"` (shows the success/error text of the last trade)
  - `"positions-table"`, a row per position: `"position-row-<TICKER>"`
  - `"portfolio-heatmap"`, `"pnl-chart"`
  - `"chat-panel"`, `"chat-input"`, `"chat-send-button"`, `"chat-loading"`, each message `data-testid="chat-message"` with `data-role="user"|"assistant"`, and each action chip `data-testid="chat-action"` with `data-status="executed"|"failed"|"added"|...`

## 6. Runtime and env (devops ↔ everyone)

- `.env` at the repo root: `OPENROUTER_API_KEY`, `MASSIVE_API_KEY`, `LLM_MOCK`. Optional: `SIMULATOR_SEED`, `MASSIVE_POLL_INTERVAL`, `FINALLY_DB_PATH`, `FINALLY_STATIC_DIR`.
- The backend loads `.env` from the repo root if present (`python-dotenv`, `override=False`) so local `uv run` works. Docker passes it via `--env-file`.
- Run command: `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`, from `backend/`.
- Scripts: `scripts/start_mac.sh [--build] [--no-open]`, `scripts/stop_mac.sh`, plus `.ps1` equivalents. Container name `finally`, volume `finally-data`, image `finally`. If `.env` is missing, the start script copies `.env.example`.

## 7. Process

1. Unit tests come with your code. Run `cd backend && uv run pytest` (all backend tests must stay green) or `cd frontend && npm test`.
2. In this sandbox, `uv` needs `export UV_CACHE_DIR=$TMPDIR/uv-cache`. Network installs (pip/npm) may need the registry host allowed.
3. When your part is usable, message **integration-tester** and **lead** with a one-line status. Bugs found by integration-tester go to the owning member, who fixes them and replies "fixed: <summary>".
4. Don't commit; the lead commits.

## Changelog
- 2026-10-06 lead: initial contract.
- 2026-10-06 lead: backend-api notes, all compatible with the contract:
  - A failed `POST /api/portfolio/trade` returns 400 with `{"error","detail"}` plus the failed TradeResult fields.
  - Pydantic validation errors map to the field's contract code; any other bad request gives `invalid_request`.
  - `/api/portfolio/history` limit is clamped to 1–2000; `/api/chat/history` limit to 1–500.
- 2026-10-06 lead: llm-engineer: if an action raises unexpectedly, the chat reply reports it as a failed action with error `internal_error`.
