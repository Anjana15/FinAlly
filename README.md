# FinAlly — AI Trading Workstation

FinAlly (Finance Ally) is a Bloomberg-style trading terminal with an AI copilot. It streams live prices, runs a simulated $10,000 portfolio, and includes an LLM chat assistant that can analyze your positions, place trades and manage your watchlist.

> **Status:** greenfield. AI coding agents are building the app from the spec in [`planning/PLAN.md`](planning/PLAN.md). Commands below are the planned interface.

## Features

- Live price streaming over SSE, with green/red flash animations and sparklines
- Market orders with instant fills and fractional shares (no fees)
- Portfolio heatmap, P&L chart and positions table
- AI chat that executes trades and watchlist changes from natural language
- Built-in market simulator by default; real data via Massive (Polygon.io) when a key is set

## Architecture

The app runs as a single Docker container on port 8000:

| Layer    | Tech                                                        |
|----------|-------------------------------------------------------------|
| Frontend | Next.js + TypeScript + Tailwind, static export              |
| Backend  | FastAPI (Python 3.12, `uv`), serving `/api/*` and the frontend |
| Database | SQLite at `db/finally.db`, created and seeded on startup    |
| LLM      | LiteLLM → OpenRouter (`gpt-oss-120b` on Cerebras)            |

## Quick start

```bash
cp .env.example .env          # add your OPENROUTER_API_KEY
scripts/start_mac.sh          # or scripts/start_windows.ps1
# open http://localhost:8000
```

Or with Docker directly:

```bash
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

## Configuration (`.env`)

| Variable             | Purpose                                                |
|----------------------|--------------------------------------------------------|
| `OPENROUTER_API_KEY` | Enables the AI chat                                    |
| `MASSIVE_API_KEY`    | Optional. Uses real market data; empty means simulator |
| `LLM_MOCK`           | `true` returns deterministic LLM responses (tests/dev) |

## Development

```bash
cd backend && uv sync && uv run pytest                     # backend
cd frontend && npm install && npm run build                # frontend
docker compose -f test/docker-compose.test.yml up          # E2E (Playwright)
```

## Repository layout

```
backend/    FastAPI app, market data, LLM, DB schema/seed
frontend/   Next.js app
test/       Playwright E2E tests
db/         SQLite volume mount (runtime only)
scripts/    Start/stop scripts
planning/   Spec and agent coordination docs
```

## License

See [LICENSE](LICENSE).
