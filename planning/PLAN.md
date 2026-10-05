# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, % change
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (volume-mounted)               │
│  Background task: market data polling/sim        │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, volume-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real data via Massive API if key provided

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no docker-compose for production, no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── db/                   # Schema definitions, seed data, migration logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # Volume mount target (SQLite file lives here at runtime)
│   └── .gitkeep              # Directory exists in repo; finally.db is gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── docker-compose.yml        # Optional convenience wrapper
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions and seed logic. The backend lazily initializes the database on first request — creating tables and seeding default data if the SQLite file doesn't exist or is empty.
- **`db/`** at the top level is the runtime volume mount point. The SQLite file (`db/finally.db`) is created here by the backend and persists across container restarts via Docker volume.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required: OpenRouter API key for LLM chat functionality
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Massive (Polygon.io) API key for real market data
# If not set, the built-in market simulator is used (recommended for most users)
MASSIVE_API_KEY=

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- The backend reads `.env` from the project root (mounted into the container or read via docker `--env-file`)

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface. The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., tech stocks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic seed prices (e.g., AAPL ~$190, GOOGL ~$175, etc.)
- Runs as an in-process background task — no external dependencies

### Massive API (Optional)

- REST API polling (not WebSocket) — simpler, works on all tiers
- Polls for the union of all watched tickers on a configurable interval
- Free tier (5 calls/min): poll every 15 seconds
- Paid tiers: poll every 2-15 seconds depending on tier
- Parses REST response into the same format as the simulator

### Shared Price Cache

- A single background task (simulator or Massive poller) writes to an in-memory price cache
- The cache holds the latest price, previous price, and timestamp for each ticker
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- Server pushes price updates for all tickers known to the system at a regular cadence (~500ms) — in the single-user model this is equivalent to the user's watchlist
- Each SSE event contains ticker, price, previous price, timestamp, and change direction
- Client handles reconnection automatically (EventSource has built-in retry)

**Implementation design:** `planning/MARKET_DATA_DESIGN.md` has the complete market-data design: module code, SSE wire format, Massive error handling and tests. Where it differs from this section's open questions, follow that doc.

---

## 7. Database

### SQLite with Lazy Initialization

The backend checks for the SQLite database on startup (or first request). If the file doesn't exist or tables are missing, it creates the schema and seeds default data. This means:

- No separate migration step
- No manual database setup
- Fresh Docker volumes start with a clean, seeded database automatically

### Schema

All tables include a `user_id` column defaulting to `"default"`. This is hardcoded for now (single-user) but enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded every 30 seconds by a background task, and immediately after each trade execution.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — trades executed, watchlist changes made; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

---

## 8. API Endpoints

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive complete JSON response (message + executed actions) |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) |

---

## 9. LLM Integration

When writing code to make calls to LLMs, use cerebras-inference skill to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads recent conversation history from the `chat_messages` table
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM via LiteLLM → OpenRouter, requesting structured output, using the cerebras-inference skill
5. Parses the complete structured JSON response
6. Auto-executes any trades or watchlist changes specified in the response
7. Stores the message and executed actions in `chat_messages`
8. Returns the complete JSON response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

### Structured Output Schema

The LLM is instructed to respond with JSON matching this schema:

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute. Each trade goes through the same validation as manual trades (sufficient cash for buys, sufficient shares for sells)
- `watchlist_changes` (optional): Array of watchlist modifications

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

If a trade fails validation (e.g., insufficient cash), the error is included in the chat response so the LLM can inform the user.

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling OpenRouter. This enables:
- Fast, free, reproducible E2E tests
- Development without an API key
- CI/CD pipelines

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), daily change %, and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, using data from `portfolio_snapshots`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, % change
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history, loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Canvas-based charting library preferred (Lightweight Charts or Recharts) for performance
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000.

### Docker Volume

The SQLite database persists via a named Docker volume:

```bash
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

The `db/` directory in the project root maps to `/app/db` in the container. The backend writes `finally.db` to this path.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume mount, port mapping, and `.env` file
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

### Optional Cloud Deployment

The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory as a stretch goal, but is not part of the core build.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: simulator generates valid prices, GBM math is correct, Massive API response parsing works, both implementations conform to the abstract interface
- Portfolio: trade execution logic, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow
- API routes: correct status codes, response shapes, error handling

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image.

**Environment**: Tests run with `LLM_MOCK=true` by default for speed and determinism.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message, receive a response, trade execution appears inline
- SSE resilience: disconnect and verify reconnection
---

## 13. Review: Questions, Clarifications & Simplifications

*Added in doc review, 2026-09-30. Each item names the section it affects. The ones marked **[Contract]** block parallel work, because two agents have to agree on the answer. Settle those first.*

### 13.1 Gaps in the cross-agent contract (highest priority)

1. **[Contract] API request/response shapes are not defined (§8).** The endpoint table lists paths but no JSON bodies, status codes, or error format. Since the frontend and backend agents build at the same time, they need these defined up front. Suggestion: add a short example JSON for each endpoint, plus one error shape (e.g. `{"error": "insufficient_cash", "detail": "..."}` with HTTP 400) used by `/api/portfolio/trade`, `/api/watchlist`, and the per-action results in `/api/chat`.
2. **[Contract] The SSE event format is not defined (§6).** Questions to answer: is there one event per ticker per tick, or one batched event per tick? Is there a named event type? What are the exact field names, and how is the timestamp formatted? Suggestion: one unnamed `data:` event per tick carrying a JSON object keyed by ticker, e.g. `{"AAPL": {"price": 190.12, "prev": 190.05, "ts": "2026-09-30T12:00:00Z", "dir": "up"}}`. It is simpler to parse and cuts event count by 10×.
3. **[Contract] The `/api/chat` response shape is not defined (§9).** The frontend has to render executed actions inline, so it needs to know what each action result looks like. Suggestion: `{message, actions: {trades: [{ticker, side, quantity, price?, status: "executed"|"failed", error?}], watchlist_changes: [{ticker, action, status, error?}]}}`. Store the same object in `chat_messages.actions`.
4. **[Contract] Mock LLM behavior is not defined (§9, §12).** The E2E spec says "trade execution appears inline", so the mock has to produce a trade deterministically. Proposal: keyword rules. A message containing `buy` returns a buy of 1 AAPL, `sell` returns a sell of 1 AAPL, `add <TICKER>` adds to the watchlist, and anything else returns a fixed text reply with no actions. Write this down so the test agent and the backend agent build the same thing.

### 13.2 Ambiguities and internal inconsistencies

5. **"Daily change %" has no reference point (§10).** The simulator has no trading day, and Massive may be polled outside market hours. Is the change measured from the seed price, from the price at page load, or from the previous close (Massive only)? Suggestion: measure change since the backend started (the simulator's seed price, or the first Massive quote), carry it in the price cache, and rename the label to "Change %".
6. **"% change" in the positions table (§2, §10) is ambiguous.** It could mean unrealized P&L % relative to avg cost, or the price change. Presumably it is `(price − avg_cost) / avg_cost`. Please say so. - Yes
7. **Positions and the watchlist are decoupled, but only the watchlist gets prices.**
   - Massive polls "the union of all watched tickers" (§6), and SSE pushes "tickers known to the system". What happens if the user holds TSLA and then removes it from the watchlist? Its price stops updating and P&L goes stale.
   - Can a user trade a ticker that isn't on the watchlist?
   - Suggestion: tracked tickers = watchlist ∪ open positions. Either auto-add a ticker to the watchlist on buy, or block removing a ticker while a position is held. - auto-add a ticker to the watchlist on buy
8. **Unknown or new tickers.**
   - When a ticker is added (e.g. `PYPL`), where does the simulator get its seed price? Suggestion: use a hardcoded table for known symbols, and a random $50–$300 otherwise.
   - Is ticker input validated? Suggestion: format only, `^[A-Z.]{1,6}$`, uppercased. In Massive mode, what happens with a symbol that doesn't exist?
   - What happens with a trade on a ticker that has no cached price yet? Suggestion: reject it with `no_price`.
9. **The chat flow can't report failures accurately.** The LLM writes `message` *before* the backend executes trades, so it may say "Bought 10 AAPL" when the trade actually failed. §9 says "the error is included in the chat response so the LLM can inform the user", but there is no second LLM call. Pick one:
   - (a) **Simpler, recommended:** make no second call. The frontend shows per-action success/failure chips next to the message, and the system prompt tells the LLM to phrase actions as intent ("Placing an order for…").
   - (b) Make a second LLM call with the execution results. This doubles latency and complexity. - option a
10. **How much chat history is "recent" (§9)?** Suggestion: the last 20 messages. Should `actions` results be included in the history sent to the LLM? That would help it remember what actually executed. - agreed.
11. **Structured output: "optional" arrays.** Strict JSON-schema modes usually require every field to be present. Making `trades` and `watchlist_changes` **required arrays that may be empty** is simpler to validate and to parse.
12. **`users_profile` breaks the "all tables include `user_id`" rule (§7).** It uses `id` as the user key, which is reasonable, but the text says otherwise. Either reword the rule or rename the column to `user_id`.
13. **"Migration logic" in `backend/db/` (§4) contradicts "no migration step" (§7).** Drop the word "migration".
14. **Lazy init "on startup (or first request)" (§4, §7).** Pick **startup** (FastAPI lifespan). The 30s snapshot task and the market data task need the DB and the watchlist before any request arrives anyway.
15. **Trade math details that aren't specified:**
    - Is the buy avg cost a weighted average? (Presumably yes.)
    - A sell leaves avg cost unchanged. Is that right? yes
    - When quantity reaches 0, is the `positions` row deleted?
    - What is the minimum quantity (> 0)?
    - How are fractional quantities and cash rounded? Floating-point residue like `0.0000000001` shares will show up. Suggestion: round quantity to 4 dp and cash to 2 dp, and treat |qty| < 1e-6 as zero.
    - Realized P&L is not stored anywhere. Is that intentional? It is still recoverable from `trades` if it's needed later.
16. **Header total value "updating live" (§10).** Is this computed client-side (cash + Σ qty × live SSE price), or by polling `/api/portfolio`? Client-side is smoother and avoids polling. Please state which.
17. **`OPENROUTER_API_KEY` is labelled "Required" (§5), but `LLM_MOCK` allows running without it.** Clarify the behavior when the key is missing and `LLM_MOCK=false`. Suggestion: the app runs normally, and `/api/chat` returns a friendly "chat not configured" message instead of a 500 error.
18. **How `.env` reaches the backend (§5).** It says it is "mounted into the container or read via `--env-file`". Pick `--env-file` only. The start scripts should create `.env` from `.env.example` if it is missing, or fail with a clear message, because `docker run --env-file` errors on a missing file.
19. **`/api/portfolio/history` has no limits.** At one snapshot every 30s, that's about 2,900 rows per day. Should the endpoint accept a `?since=` / limit, or downsample? Fine for a demo, but define the default.
20. **Snapshots during the 30s loop with no positions.** Record them anyway (the value is just cash)? Presumably yes, so the P&L chart shows data from first launch. The E2E test "P&L chart has data points" depends on this.
21. **Static file serving.** Mount `StaticFiles(html=True)` at `/` **after** the API routers, so `/api/*` is never shadowed. Also, the Next export needs `trailingSlash`/`images.unoptimized` settings. The frontend agent should know this.
22. **Massive cadence vs. SSE cadence.** With 15s polls, the SSE stream sends the same price 30 times between updates. The frontend should flash only when the price actually changes, and the 30s snapshots will look flat. That's fine, but worth stating so it isn't reported as a bug.

### 13.3 Factual corrections

23. **Recharts is SVG-based, not canvas-based (§10, CLAUDE.md).** Lightweight Charts *is* canvas, but it has no treemap. Suggestion: Lightweight Charts for the price and P&L line charts, plus a simple Recharts `Treemap` or a hand-rolled CSS-grid/SVG treemap for the heatmap. At this data size, SVG performs fine.
24. **The skill name is wrong.** The spec says "cerebras-inference skill", but the installed skill is `.claude/skills/cerebras` (display name "Cerebras Inference"). Update §9 and CLAUDE.md so agents can find it.
25. **`.gitignore` is missing entries this plan relies on.** It ignores `db.sqlite3` but not `db/finally.db` (or `db/*.db`), and it has no Node entries (`node_modules/`, `frontend/.next/`, `frontend/out/`). `db/.gitkeep` from §4 also doesn't exist yet.

### 13.4 Opportunities to simplify

26. **Drop `docker-compose.yml` (§4).** It is described as optional and conflicts with the "no docker-compose for production" rationale (§3). The start scripts already cover convenience.
27. **Drop the cloud deployment / Terraform stretch goal (§11)** from this plan, or move it to a separate `planning/` doc, so no agent spends time on it.
28. **Merge the start/stop scripts per platform, or rename them.** `start_mac.sh` also serves Linux. Suggestion: `scripts/start.sh` / `scripts/stop.sh` plus `.ps1` equivalents. Decide "optionally opens the browser" one way (e.g. open unless `--no-open`).
29. **Batch the SSE payload per tick** (see item 2). There's less framing overhead, and the client applies one state update per tick instead of 10.
30. **Skip the second LLM call** (see item 9, option a).
31. **Consider dropping `id` UUIDs where a natural key exists.** `watchlist` and `positions` already have `UNIQUE(user_id, ticker)`, so `PRIMARY KEY (user_id, ticker)` removes a column and a UUID dependency. This one is optional and a matter of taste.
32. **Scope of frontend unit tests (§12).** "Watchlist CRUD operations" is really E2E territory. Keep frontend unit tests to pure logic: price-flash direction, P&L/weight calculations, SSE payload parsing. Leave CRUD flows to Playwright.
33. **Correlated GBM (§6).** A simple sector-factor model is enough, e.g. `shock = β·sector_shock + √(1−β²)·idio_shock` with 2–3 sectors. There's no need for a full covariance/Cholesky setup. State this so the market data agent doesn't over-engineer it.
