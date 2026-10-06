import { expect, test, type Page } from '@playwright/test';
import { openApp, tid, waitForPrice } from './helpers';

const STREAM = '**/api/stream/prices';

async function expectPriceChanges(page: Page, ticker: string, timeout = 10_000) {
  const loc = tid(page, `price-${ticker}`);
  await expect(loc).toHaveText(/\d/, { timeout: 15_000 });
  const first = await loc.textContent();
  await expect.poll(async () => loc.textContent(), { timeout, message: `${ticker} price should change` }).not.toBe(first);
}

async function anyPriceChanges(page: Page, tickers: string[], timeout = 10_000) {
  const read = () => Promise.all(tickers.map(async (t) => (await tid(page, `price-${t}`).textContent()) ?? ''));
  const initial = await read();
  await expect
    .poll(async () => (await read()).some((t, i) => t !== initial[i]), { timeout, message: 'prices should resume' })
    .toBe(true);
}

const SOME = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN'];

test.describe('SSE resilience', () => {
  test('navigate away and back: reconnects and prices resume', async ({ page }) => {
    await openApp(page);
    await waitForPrice(page, 'AAPL');
    await page.goto('about:blank');
    await page.goBack();
    await expect(tid(page, 'connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 20_000 });
    await anyPriceChanges(page, SOME);
  });

  test('stream unavailable at load -> not connected; recovers once it is back', async ({ page }) => {
    // Block the stream with a network error before the page opens it.
    let failures = 0;
    page.on('requestfailed', (r) => {
      if (r.url().includes('/api/stream/prices')) failures++;
    });
    await page.route(STREAM, (route) => route.abort('connectionreset'));
    await page.goto('/');
    // Wait for two failed attempts (proves the client retries) before restoring the stream,
    // so the unroute can't race an in-flight intercepted request.
    await expect.poll(() => failures, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
    await expect(tid(page, 'connection-status')).toHaveAttribute('data-state', /reconnecting|disconnected/);

    await page.unroute(STREAM);
    // EventSource retries every ~3 s (or the app reconnects on its own).
    await expect(tid(page, 'connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 30_000 });
    await anyPriceChanges(page, SOME);
  });

  test('stream keeps dropping -> client reconnects repeatedly, then recovers', async ({ page }) => {
    // Chromium's setOffline() does not tear down an open EventSource, so we simulate a
    // server that ends each stream right after one frame: every response closes,
    // forcing the client's reconnect path.
    let streamRequests = 0;
    page.on('request', (r) => {
      if (r.url().includes('/api/stream/prices')) streamRequests++;
    });
    await page.route(STREAM, (route) =>
      route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
        body:
          'retry: 300\n\n' +
          'data: {"type":"prices","source":{"source":"simulator","state":"ok","message":null},"quotes":{}}\n\n',
      }),
    );
    await page.goto('/');
    await expect.poll(() => streamRequests, { timeout: 20_000, message: 'client should reconnect after drops' }).toBeGreaterThanOrEqual(3);

    await page.unroute(STREAM);
    await expect(tid(page, 'connection-status')).toHaveAttribute('data-state', 'connected', { timeout: 30_000 });
    await anyPriceChanges(page, SOME);
  });
});
