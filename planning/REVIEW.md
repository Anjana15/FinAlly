# Review of FinAlly implementation plan

Reviewed: 2026-10-01

Scope: `planning/PLAN.md`, with repository context from `CLAUDE.md` and `.gitignore`. This is a specification review; there is no implemented application to validate. External provider capabilities and quotas have not been independently verified.

## Overall assessment

The single-container architecture, shared backend trade service, simulator default, and mock chat mode are a sensible scope for this capstone. The plan describes the intended experience clearly. It is not yet a complete implementation contract: §13 records useful questions and proposals, but leaves the original requirements unchanged and several decisions unresolved.

Resolve the high-priority items below before implementation. Fold accepted §13 proposals into the relevant sections so agents have one authoritative answer rather than choosing between the specification and its appended review.

## High-priority findings

### 1. Trade execution needs an atomic transaction and an explicit precision policy

**References:** §§7–9; §13 item 15.

Validation followed by separate balance, position, and history writes can overspend cash or oversell shares when manual orders, chat actions, or multiple browser tabs overlap. A failure midway can also leave cash and holdings inconsistent.

Specify one backend trade service that captures a valid quote, acquires a SQLite write transaction, reads current balances, validates, updates cash and holdings, records the trade and immediate snapshot, and commits together. Roll back all writes on failure. Define lock contention behavior and keep external LLM/provider calls outside the transaction.

The schema's `REAL` fields and the suggested independent rounding of cash and quantity do not define consistent accounting. Specify supported quantity precision, price precision, rounding mode, and treatment of tiny residual positions. Prefer decimal arithmetic with explicitly scaled storage. Define weighted average cost on buys, unchanged average cost on partial sells, and deletion of fully closed positions. Tests should verify conservation of cash plus holdings at the execution price, including repeated fractional trades.

### 2. Price availability and freshness must govern execution and valuation

**References:** §6, §8; §13 items 7–8 and 22.

The current cache contract permits an old price to look live indefinitely after a provider failure. Removing a held ticker from the watchlist can stop its updates. A portfolio snapshot could silently value an unpriced position at zero or use a stale quote without indicating it.

Define tracked symbols as watchlist ∪ open positions, with a policy for obtaining a quote for a newly requested trade. Removing a watchlist entry must not stop pricing an open holding. Specify source timestamp, receipt timestamp, quote status, and a source-appropriate execution freshness rule. Define how closed-market quotes are handled. Reject unavailable or unacceptable quotes with an actionable error; do not silently switch real-data trading to simulated prices.

Portfolio responses and snapshots need a policy for missing or stale marks. A reasonable default is to preserve the last known mark with an explicit stale status, and avoid presenting incomplete valuations as valid totals. Persist enough quote provenance to explain the price used for a fill.

### 3. Retries can duplicate trades and chat actions

**References:** §8–9.

A request may commit successfully while its response is lost. Retrying a manual order or chat request would then execute it again. A loading indicator or disabled button cannot protect against network retries or multiple clients.

Add a client-generated request identifier for mutation requests, especially trades and chat. Persist the identifier and outcome with execution, and return the saved result on retry. Define rejection of the same identifier with a different body. For chat, persist action identifiers and execution status so a retry cannot rerun a partially completed action list or trigger a second independent model decision.

### 4. Chat execution semantics and authority remain underspecified

**References:** §9; §13 items 3, 9–11.

Structured JSON validates shape; it does not establish that an action was requested. The instruction to suggest trades can produce action arrays during an analysis-only conversation. Multiple returned actions also need an ordering and failure policy: a sell followed by a buy may depend on proceeds, while an early failed action may invalidate later assumptions.

Keep the deliberate no-confirmation simulated-trading behavior, but explicitly require user intent before emitting trades. Analysis and suggestions should return empty trade arrays. Validate every model action through the same backend service as manual actions, reject non-finite or non-positive quantities, and bound response size and action count.

Choose deterministic action ordering and either independent per-action transactions or all-or-nothing batch execution. Return authoritative success/failure results for every action. Include actual execution outcomes in subsequent model context. The simpler intent-text plus result-chip approach in §13 item 9 is appropriate, provided the UI clearly distinguishes intent from execution.

### 5. Complete the API contract, including reload and live synchronization

**References:** §§8–10; §13 items 1–4 and 16.

Endpoint paths alone do not establish field names, numeric serialization, timestamps, errors, or state synchronization. Chat messages are persisted and the UI promises conversation history, but there is no endpoint to retrieve it after reload. Portfolio history is stored server-side, but the plan does not say how new snapshots reach the chart.

Publish request/response examples and shared schemas for all endpoints and SSE events. Define normalization, status codes, per-action errors, time format, and empty/loading states. Add a bounded chat-history read endpoint. Choose polling or an explicit portfolio/snapshot event for refreshing history and mutation state. Client-side mark-to-market totals still need authoritative cash and quantity refreshes after trades, chat actions, and reconnection, including changes from another tab.

On SSE connect/reconnect, send a complete current quote snapshot. Define whether subsequent events are snapshots or deltas, include heartbeat behavior, and bound slow-client buffering. Bound frontend price-history buffers as well; accumulating every tick indefinitely will grow memory in an app intended to remain open.

### 6. Provider polling requires a request budget, not just a timer

**References:** §6.

The statement “5 calls/min: poll every 15 seconds” works only if each polling cycle consumes one request. If the selected endpoint requires one call per ticker, the ten-symbol watchlist already makes that schedule incompatible with the stated budget.

Specify the endpoint, batching support, quote/delay semantics, and response fields, then calculate request consumption for watchlist ∪ positions. Verify these against current provider documentation before implementation. Define a global request budget, retry/backoff handling for rate limits, bounded network timeouts, and visible degraded state for invalid credentials or provider outages.

### 7. Lifecycle and persistence assumptions need to be explicit

**References:** §§3–4, 7, 11; §13 items 14 and 20.

An in-memory cache and in-process producers imply a single backend worker. Multiple workers would have separate caches and could each start simulation and snapshot tasks. Startup initialization must complete before these tasks or request handling begin.

Specify one Uvicorn worker, initialization through lifespan, idempotent seeding, background-task cancellation on shutdown, and health/readiness semantics. Seed only missing initial state; an intentionally emptied watchlist must remain empty after restart. Record an initial cash-only snapshot so a fresh chart does not depend on waiting 30 seconds.

Separate “no manual migration command” from “no schema evolution.” Track a schema version and define automatic upgrades or an explicit unsupported-version failure; table creation alone will not update an existing persistent volume after a schema change. Clarify named-volume storage versus a host bind mount: the example named volume does not map the repository's `db/` directory into the container.

### 8. The no-login deployment boundary should match the launch command

**References:** §§2–3, 11.

All callers share one portfolio and can invoke paid chat requests. The Docker example publishes port 8000 without limiting it to localhost, although the stated experience is a local single-user app.

Use `-p 127.0.0.1:8000:8000` in local launch commands and scripts. Define chat concurrency/request limits to bound accidental repeated model calls. Keep public cloud deployment outside the core acceptance criteria until access control and durable database storage are designed for that deployment.

## Refinements to the existing §13 review

- **Item 7:** tracking watchlist ∪ positions is sufficient. Automatically adding every holding to the watchlist or blocking removal is unnecessary if quote subscriptions are independent of display preferences.
- **Item 8:** generated simulator prices should be reproducible under a configured seed. Distinguish syntactically accepted simulated symbols from provider-validated real symbols; format validation does not establish existence.
- **Item 13:** migration logic and the absence of a manual migration step are compatible. Preserve automatic schema upgrade support rather than merely deleting the term.
- **Item 15:** quantity/cash rounding needs an accounting policy, not only display precision. Define consistent execution arithmetic before choosing decimal places or a dust threshold.
- **Item 24:** `.claude/skills/cerebras/SKILL.md` exists in this checkout, but that does not guarantee availability to every coding environment. Give the exact reference and document the provider contract without depending solely on a skill display name. Update `CLAUDE.md` alongside accepted plan decisions.
- **Item 25:** the ignore omissions are confirmed. Include SQLite journal/WAL/SHM artifacts as well as the database file and frontend build outputs.
- **Item 26:** an optional Compose convenience wrapper is compatible with a single-container runtime. Removing it is a scope choice, not an architectural necessity.
- **Item 32:** frontend CRUD component tests can meaningfully exercise loading, errors, and rollback with mocked APIs. Keep tests where they verify distinct behavior rather than excluding them categorically.

## Recommended delivery and acceptance sequence

1. **Freeze contracts:** resolve the above execution/state rules and §13 contract questions; publish schemas, deterministic mock rules, and sample fixtures.
2. **Build the core vertical slice:** startup/seed → simulator/cache → SSE → manual trade → portfolio/history → minimal UI → static export in Docker.
3. **Add chat:** mock first, then real provider integration; both use the established execution service and action-result contract.
4. **Add optional real data and visual polish:** integrate provider failure handling, charts, responsive layout, and platform scripts after the core slice works.

Extend §12 with targeted acceptance checks:

- Concurrent buys cannot overspend; concurrent sells cannot oversell; failed execution leaves no partial writes.
- Repeating the same request identifier creates exactly one execution, including after a lost response.
- Held symbols continue updating after watchlist removal; missing/stale quotes follow the stated policy.
- Reload and reconnect restore portfolio and chat state without repeating actions.
- A fresh volume seeds once; restart preserves trades, cash, and an intentionally empty watchlist.
- Chat action failures and dependent batches follow the chosen policy and are visibly reported.
- Fixed simulator seed, injected clock, and mock provider make tests reproducible; `LLM_MOCK=true` alone does not make market prices deterministic.
- The final image serves the exported frontend and `/api/*`, uses its persistent database volume, and starts without a chat key according to the documented fallback.

This would turn the plan into a buildable contract while preserving its strongest feature: a focused local trading demo with a fluid AI-assisted workflow.
