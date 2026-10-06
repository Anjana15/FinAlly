import { expect, test } from '@playwright/test';
import { apiFlatten, apiTrade } from './helpers';

// Pure API checks against TEAM_CONTRACT §3. Owns ticker: TSLA (trade shape), AMZN for failures (never held).

test.describe('HTTP API', () => {
  test('GET /api/health', async ({ request }) => {
    const res = await request.get('/api/health');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('ok');
    expect(body.market).toHaveProperty('source');
    expect(body.market).toHaveProperty('state');
    expect(body.market).toHaveProperty('message');
  });

  test('GET /api/watchlist returns quotes', async ({ request }) => {
    const body = await (await request.get('/api/watchlist')).json();
    expect(Array.isArray(body.tickers)).toBe(true);
    const aapl = body.tickers.find((t: { ticker: string }) => t.ticker === 'AAPL');
    expect(aapl).toBeTruthy();
    expect(aapl.quote).toMatchObject({ ticker: 'AAPL' });
    for (const k of ['price', 'previous_price', 'reference_price', 'change', 'change_percent', 'direction', 'timestamp']) {
      expect(aapl.quote).toHaveProperty(k);
    }
  });

  test('GET /api/portfolio shape', async ({ request }) => {
    const body = await (await request.get('/api/portfolio')).json();
    expect(typeof body.cash).toBe('number');
    expect(body).toHaveProperty('total_value');
    expect(body).toHaveProperty('valuation_complete');
    expect(Array.isArray(body.positions)).toBe(true);
  });

  test('POST /api/portfolio/trade success returns a TradeResult', async ({ request }) => {
    await apiFlatten(request, 'TSLA');
    const res = await apiTrade(request, 'TSLA', 'buy', 1.25);
    expect(res.status(), await res.text()).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ status: 'executed', ticker: 'TSLA', side: 'buy', quantity: 1.25 });
    expect(typeof body.price).toBe('number');
    expect(typeof body.cash_balance).toBe('number');
    expect(typeof body.executed_at).toBe('string');

    const portfolio = await (await request.get('/api/portfolio')).json();
    const pos = portfolio.positions.find((p: { ticker: string }) => p.ticker === 'TSLA');
    expect(pos.quantity).toBeCloseTo(1.25, 4);
    expect(portfolio.cash).toBeCloseTo(body.cash_balance, 2);

    const sell = await apiTrade(request, 'TSLA', 'sell', 1.25);
    expect(sell.status()).toBe(200);
  });

  test('insufficient_cash -> 400 {"error":"insufficient_cash"}', async ({ request }) => {
    const before = (await (await request.get('/api/portfolio')).json()).cash;
    const res = await apiTrade(request, 'AMZN', 'buy', 1_000_000);
    expect(res.status()).toBe(400);
    const body = await res.json();
    expect(body.error).toBe('insufficient_cash');
    expect(typeof body.detail).toBe('string');
    // Error body is top-level, not nested under "detail".
    expect(body).not.toHaveProperty('detail.error');
    const after = (await (await request.get('/api/portfolio')).json()).cash;
    expect(after).toBe(before);
  });

  for (const [name, data, code] of [
    ['insufficient_shares', { ticker: 'AMZN', side: 'sell', quantity: 1_000 }, 'insufficient_shares'],
    ['invalid_quantity (zero)', { ticker: 'AMZN', side: 'buy', quantity: 0 }, 'invalid_quantity'],
    ['invalid_quantity (negative)', { ticker: 'AMZN', side: 'buy', quantity: -1 }, 'invalid_quantity'],
    ['invalid_side', { ticker: 'AMZN', side: 'short', quantity: 1 }, 'invalid_side'],
    ['invalid_ticker', { ticker: '???', side: 'buy', quantity: 1 }, 'invalid_ticker'],
  ] as const) {
    test(`trade error: ${name}`, async ({ request }) => {
      const res = await request.post('/api/portfolio/trade', { data });
      expect(res.status(), await res.text()).toBe(400);
      expect((await res.json()).error).toBe(code);
    });
  }

  test('POST /api/watchlist invalid ticker -> 400', async ({ request }) => {
    const res = await request.post('/api/watchlist', { data: { ticker: 'not a ticker!' } });
    expect(res.status()).toBe(400);
    expect((await res.json()).error).toBe('invalid_ticker');
  });

  test('GET /api/portfolio/history and /api/chat/history shapes', async ({ request }) => {
    const hist = await (await request.get('/api/portfolio/history?limit=10')).json();
    expect(Array.isArray(hist.snapshots)).toBe(true);
    expect(hist.snapshots.length).toBeLessThanOrEqual(10);
    const chat = await (await request.get('/api/chat/history?limit=5')).json();
    expect(Array.isArray(chat.messages)).toBe(true);
    expect(chat.messages.length).toBeLessThanOrEqual(5);
  });

  test('POST /api/chat (LLM_MOCK): buy, failing sell, plain text', async ({ request }) => {
    const buy = await request.post('/api/chat', { data: { message: 'buy 1 NVDA' } });
    expect(buy.status()).toBe(200);
    const b = await buy.json();
    expect(b).toMatchObject({ role: 'assistant', content: 'Placing a buy order for 1 NVDA.' });
    expect(b.actions.trades[0]).toMatchObject({ status: 'executed', ticker: 'NVDA', side: 'buy', quantity: 1 });
    expect(b.actions.error).toBeNull();

    const sell = await request.post('/api/chat', { data: { message: 'SELL 100000 MSFT' } });
    expect(sell.status()).toBe(200);
    expect((await sell.json()).actions.trades[0]).toMatchObject({ status: 'failed', error: 'insufficient_shares' });

    const hello = await request.post('/api/chat', { data: { message: 'what do you think?' } });
    const h = await hello.json();
    expect(h.content).toContain('Mock response');
    expect(h.actions.trades).toEqual([]);
    expect(h.actions.watchlist_changes).toEqual([]);

    const hist = await (await request.get('/api/chat/history?limit=6')).json();
    const roles = hist.messages.map((m: { role: string }) => m.role);
    expect(roles.slice(-2)).toEqual(['user', 'assistant']);
    expect(hist.messages[hist.messages.length - 2].actions).toBeNull();
  });

  test('SSE /api/stream/prices sends a full prices snapshot', async ({ page }) => {
    await page.goto('/api/health');
    const frame = await page.evaluate(async () => {
      const ctrl = new AbortController();
      const res = await fetch('/api/stream/prices', { signal: ctrl.signal });
      const ct = res.headers.get('content-type');
      const reader = res.body!.getReader();
      const dec = new TextDecoder();
      let buf = '';
      const deadline = Date.now() + 10_000;
      while (Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const m = buf.match(/^data: (.*)$/m);
        if (m && buf.includes('\n\n', buf.indexOf('data: '))) {
          ctrl.abort();
          return { ct, raw: buf, data: JSON.parse(m[1]) };
        }
      }
      ctrl.abort();
      return { ct, raw: buf, data: null };
    });
    expect(frame.ct).toContain('text/event-stream');
    expect(frame.raw).toContain('retry: 3000');
    expect(frame.data).not.toBeNull();
    expect(frame.data.type).toBe('prices');
    expect(frame.data.source).toHaveProperty('state');
    expect(frame.data.quotes).toHaveProperty('AAPL');
    expect(frame.data.quotes.AAPL.price).toBeGreaterThan(0);
  });
});
