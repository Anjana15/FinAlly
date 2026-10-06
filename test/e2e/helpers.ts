import { expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/** Selectors come ONLY from TEAM_CONTRACT.md §5. */
export const tid = (page: Page, id: string): Locator => page.getByTestId(id);

export const DEFAULT_TICKERS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'NFLX'];

/** Parse a money/number string such as "$10,000.00", "Cash: $9,812.40", "-$12.30", "1.5". */
export function parseMoney(text: string | null | undefined): number {
  const raw = (text ?? '').replace(/−/g, '-'); // unicode minus
  const m = raw.match(/-?\$?\s*-?[\d,]+(?:\.\d+)?/g);
  if (!m || m.length === 0) throw new Error(`no number in "${text}"`);
  const token = m[m.length - 1];
  const negative = token.includes('-');
  const n = Number(token.replace(/[^\d.]/g, ''));
  if (!Number.isFinite(n)) throw new Error(`bad number in "${text}"`);
  return negative ? -n : n;
}

export async function readMoney(loc: Locator): Promise<number> {
  return parseMoney(await loc.textContent());
}

/** Load the app and wait for the SSE stream to be connected. */
export async function openApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(tid(page, 'connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 20_000 });
}

/** Wait until the header cash shows a parseable number and return it. */
export async function headerCash(page: Page): Promise<number> {
  const loc = tid(page, 'header-cash');
  await expect(loc).toHaveText(/\d/);
  return readMoney(loc);
}

/** Wait until a ticker's price cell shows a number (i.e. the stream has delivered a quote). */
export async function waitForPrice(page: Page, ticker: string): Promise<number> {
  const loc = tid(page, `price-${ticker}`);
  await expect(loc).toHaveText(/\d/, { timeout: 15_000 });
  return readMoney(loc);
}

// ---------- API helpers (contract §3) ----------

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  price: number | null;
}

export async function apiPortfolio(request: APIRequestContext): Promise<{ cash: number; positions: Position[]; total_value: number | null }> {
  const res = await request.get('/api/portfolio');
  expect(res.status()).toBe(200);
  return res.json();
}

export async function apiQty(request: APIRequestContext, ticker: string): Promise<number> {
  const p = await apiPortfolio(request);
  return p.positions.find((x) => x.ticker === ticker)?.quantity ?? 0;
}

export async function apiTrade(request: APIRequestContext, ticker: string, side: 'buy' | 'sell', quantity: number) {
  return request.post('/api/portfolio/trade', { data: { ticker, side, quantity } });
}

/** Make sure a ticker is NOT on the watchlist (ignores 404). */
export async function apiEnsureNotWatched(request: APIRequestContext, ticker: string): Promise<void> {
  const res = await request.delete(`/api/watchlist/${ticker}`);
  expect([200, 404]).toContain(res.status());
}

/** Sell any shares held of `ticker` so a test starts flat. */
export async function apiFlatten(request: APIRequestContext, ticker: string): Promise<void> {
  const qty = await apiQty(request, ticker);
  if (qty > 0) {
    const res = await apiTrade(request, ticker, 'sell', qty);
    expect(res.status(), await res.text()).toBe(200);
  }
}

// ---------- UI actions ----------

export async function uiTrade(page: Page, ticker: string, quantity: number | string, side: 'buy' | 'sell'): Promise<void> {
  await tid(page, 'trade-ticker-input').fill(ticker);
  await tid(page, 'trade-quantity-input').fill(String(quantity));
  await tid(page, side === 'buy' ? 'trade-buy-button' : 'trade-sell-button').click();
}

export interface ChatResponse {
  id: string;
  role: string;
  content: string;
  actions: {
    trades: Array<{ status: string; ticker: string; side: string; quantity: number; error?: string }>;
    watchlist_changes: Array<{ ticker: string; action: string; status: string }>;
    error: string | null;
  } | null;
}

/**
 * Send a chat message through the UI. Returns the POST /api/chat body and the
 * locator of the (last) assistant message, after it is rendered.
 * Chat history persists in the shared DB, so we key off the network response
 * rather than counting messages.
 */
export async function sendChat(page: Page, text: string): Promise<{ body: ChatResponse; message: Locator }> {
  // Let any history fetch settle before we start.
  await expect(tid(page, 'chat-input')).toBeEnabled();
  const responsePromise = page.waitForResponse(
    (r) => r.url().endsWith('/api/chat') && r.request().method() === 'POST',
    { timeout: 30_000 },
  );
  await tid(page, 'chat-input').fill(text);
  await tid(page, 'chat-send-button').click();
  const response = await responsePromise;
  expect(response.status(), 'POST /api/chat status').toBe(200);
  const body = (await response.json()) as ChatResponse;
  const message = page.locator('[data-testid="chat-message"][data-role="assistant"]').last();
  await expect(message).toContainText(body.content.slice(0, 40), { timeout: 10_000 });
  await expect(tid(page, 'chat-loading')).toBeHidden({ timeout: 10_000 });
  return { body, message };
}
