# E2E Report (integration-tester)

## Suite

`test/` — Playwright `@playwright/test` 1.62.1 (matches `mcr.microsoft.com/playwright:v1.62.1-noble`), chromium only, `workers: 1`, `retries: 1`, trace on first retry. `package-lock.json` present for `npm ci`.

| File | Scenario | Tickers it owns |
|---|---|---|
| `e2e/00-fresh-start.spec.ts` | 10 default tickers, $10,000.00 cash (skipped if DB is already used), prices stream, connection=connected, all panels present, click selects ticker | read-only |
| `e2e/10-watchlist.spec.ts` | add/remove PYPL via UI (+reload persistence), lowercase normalisation (DIS), watchlist API | PYPL, DIS |
| `e2e/20-trading.spec.ts` | buy (cash down, row appears, header == backend cash), fractional, sell-all (row disappears), partial sell, insufficient shares/cash errors | JPM, V, GOOGL, AMZN |
| `e2e/30-portfolio-viz.spec.ts` | heatmap contains a held ticker's cell, pnl-chart renders canvas/svg after a trade (history has snapshots), positions row | META |
| `e2e/40-chat.spec.ts` | mock "buy 1 AAPL" → executed chip + position; "hello" → mock text, no chips; "sell 1000 NFLX" → failed chip; add/remove SHOP; history persists; empty message → 400 | AAPL, NFLX, SHOP |
| `e2e/50-api.spec.ts` | health, watchlist/portfolio shapes, trade success + every 400 code, chat mock via API, SSE first frame (`retry: 3000`, `type: prices`) | TSLA, NVDA, AMZN (never held), MSFT |
| `e2e/60-sse-resilience.spec.ts` | navigate away/back; stream blocked at load (2 failed attempts) → reconnecting → recovers after unroute; stream that keeps ending after one frame → client reconnects ≥3 times → recovers | read-only |

Selectors: only the contract §5 `data-testid`s (plus `trade-message[data-status]`, which frontend added).

## Runs

### Run 1 — 2026-10-06, backend only (frontend build failing: `Can't resolve '@/components/Terminal'` — still in progress)
Local: uvicorn with `LLM_MOCK=true SIMULATOR_SEED=42`, fresh DB, no static dir.
- API-level tests: **16/16 passed** (50-api.spec.ts 14 incl. chat-mock and SSE frame, watchlist API 1, chat empty-message 1). No backend bugs found.
- UI specs: not run yet (waiting on the frontend).

Note for local runs inside the Claude sandbox: the backend must be started in the **same** shell command as `npx playwright test` (background processes don't survive between sandboxed commands). `PLAYWRIGHT_BROWSERS_PATH=$TMPDIR/pw-browsers`, `npm_config_cache=$TMPDIR/npm-cache` are needed; the chromium download needs `storage.googleapis.com` and `cdn.playwright.dev`.

### Run 2 — 2026-10-06, full stack (backend on :8013 serving `frontend/out`, fresh DB)
Port 8000 is held by an unrelated container, so the local wrapper now uses `PORT` (default 8013) and sets `BASE_URL` to match.
- First pass: 36/40. All 4 failures were **test bugs** and are now fixed:
  - Trade error tests matched message wording; they now assert `trade-message[data-status=failed]`.
  - The "hello" test counted chat chips before history finished loading (race); it now asserts no chips on the new message.
  - The `context.setOffline()` test is gone. Chromium doesn't tear down an open EventSource when offline. It's replaced by a "stream keeps ending" route test.
  - The "stream blocked at load" test raced `unroute` against an in-flight intercepted request. It now waits for 2 failed attempts first.
- After the fixes: **40/40 passed** on two consecutive full runs (`--retries 0`, and with the default `retries: 1`: 0 flaky). Runtime about 29 s.

### Run 3: official Docker path, 2026-10-06
`docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright`. The app image is built from the Dockerfile and served on `app:8000`, with LLM_MOCK=true and a fresh DB. Playwright ran in the v1.62.1-noble image.
- **40/40 passed** (27.3 s), exit code 0, and nothing failed only under Docker. The stack was torn down with `down` afterwards.

## Issues

| id | scenario | expected vs actual | evidence | owner | severity |
|---|---|---|---|---|---|
| E2E-001 | trade error message (UI trade bar shows backend `detail`) | Expected a readable quantity. Actual: large quantities render in exponent form, e.g. `buying 1e+06 AMZN costs $183,950,000.00 but only $10,000.64 is available` | `backend/app/db/trades.py:83,90` use `{qty:g}`. Suggest fixed-point formatting with trailing zeros stripped | db-engineer | low (cosmetic). **RESOLVED** 2026-10-06: `_fmt_qty` added. Verified via API: `buying 1000000 AMZN costs …`, `cannot sell 1234567.5 AMZN; only 0 held` |

No open issues. No functional app bugs found: every PLAN §12 scenario passes end-to-end.
