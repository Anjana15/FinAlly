# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

FinAlly (Finance Ally) is an AI-powered trading workstation: live streaming prices, a simulated portfolio, and an LLM chat assistant that can execute trades. **The v1 build is complete:** backend (`backend/app/{market,db,services,api,llm}`), frontend (`frontend/`), Docker and scripts, and the Playwright E2E suite (`test/`). The spec is `planning/PLAN.md`. The binding cross-team contract (file ownership, Python interfaces, HTTP shapes, mock-LLM rules, E2E `data-testid`s) is `planning/TEAM_CONTRACT.md`. Read both before changing anything that crosses a boundary, and update them when a decision changes the contract.

## Architecture (as specified)

Single Docker container, single port (8000):

- **Backend** (`backend/`): FastAPI, managed as a `uv` project with its own `pyproject.toml`. Owns everything server-side: API routes (`/api/*`), SSE (`/api/stream/prices`), market data, LLM integration, DB init, and serving the static frontend build.
- **Frontend** (`frontend/`): Next.js + TypeScript + Tailwind, built with `output: 'export'` and served by FastAPI as static files. Knows nothing about Python; talks only to same-origin `/api/*` (no CORS).
- **Database**: SQLite at `db/finally.db` (top-level `db/` is the Docker volume mount → `/app/db`; the `.db` file is gitignored). Schema/seed logic lives in `backend/db/`. **Lazy init**: the backend creates tables and seeds data if the file is missing or empty — there is no migration step.
- **Tests**: backend unit tests (pytest) in `backend/`, frontend unit tests in `frontend/`, Playwright E2E in `test/` with its own `docker-compose.test.yml`.

### Key cross-cutting designs

- **Market data abstraction**: a simulator (GBM, ~500ms ticks, correlated moves, random 2–5% events) and a Massive (Polygon.io) REST poller implement one abstract interface. Selection: `MASSIVE_API_KEY` non-empty → Massive; otherwise simulator. One background task writes to an **in-memory price cache** (latest price, previous price, timestamp per ticker); SSE reads only from that cache, so downstream code is source-agnostic.
- **Single-user, multi-user-ready**: every table has `user_id` defaulting to `"default"`. Keep it that way.
- **Trades**: market orders only, instant fill at cached price, fractional shares allowed. Manual trades (`POST /api/portfolio/trade`) and LLM trades must go through the **same validation path** (cash for buys, shares for sells). Record a `portfolio_snapshots` row after every trade and every 30s via background task.
- **Chat flow** (`POST /api/chat`, non-streaming): load portfolio + watchlist + recent `chat_messages` → call LLM with structured output `{message, trades[], watchlist_changes[]}` → auto-execute actions (no confirmation) → store message with `actions` JSON → return. Validation failures are reported back in the response, not raised.
- **LLM**: LiteLLM → OpenRouter, model `openrouter/openai/gpt-oss-120b` with Cerebras as provider; use the `cerebras` skill when writing LLM code. `LLM_MOCK=true` must return deterministic responses (used by E2E tests and development without a key).

## Environment

`.env` at the project root (gitignored; commit `.env.example`):

- `OPENROUTER_API_KEY` — required for real chat
- `MASSIVE_API_KEY` — optional; empty means simulator
- `LLM_MOCK` — `true` for deterministic mock LLM

## Commands

```bash
# Backend (in this sandbox, first: export UV_CACHE_DIR=$TMPDIR/uv-cache)
cd backend && uv sync
cd backend && uv run pytest                                   # all tests
cd backend && uv run pytest path/to/test_file.py::test_name   # single test
cd backend && LLM_MOCK=true uv run uvicorn app.main:app --port 8000   # dev server (serves frontend/out if built)
cd backend && uv run python market_demo.py [--serve]           # market data only

# Frontend
cd frontend && npm install && npm run build   # static export -> frontend/out
cd frontend && npm test                       # Vitest unit tests
cd frontend && npm run dev                    # :3000, proxies /api to :8000

# Full app (Docker)
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
scripts/start_mac.sh [--build] [--no-open]   # / scripts/stop_mac.sh (Windows: .ps1); FINALLY_PORT overrides 8000

# E2E (LLM_MOCK=true, fresh DB each run)
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down
```

The Dockerfile is multi-stage. Node 20 slim builds the frontend. Python 3.12 slim then runs `uv sync`, copies the export to `/app/static`, and starts uvicorn on 8000 with a single worker, because the price cache lives in the process. Env vars: `FINALLY_DB_PATH` and `FINALLY_STATIC_DIR` override the paths, and `SIMULATOR_SEED` makes simulator prices reproducible.

## UI conventions

Dark terminal aesthetic (backgrounds ~`#0d1117`/`#1a1a2e`, never pure black). Accent yellow `#ecad0a`, primary blue `#209dd7`, purple `#753991` for submit buttons. Price flashes green/red fading over ~500ms via CSS transitions; header shows a connection dot (green/yellow/red). Sparklines are accumulated client-side from the SSE stream since page load. Prefer canvas-based charts (Lightweight Charts or Recharts).
