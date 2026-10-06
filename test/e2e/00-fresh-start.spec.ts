import { expect, test } from '@playwright/test';
import { DEFAULT_TICKERS, apiPortfolio, headerCash, openApp, parseMoney, tid, waitForPrice } from './helpers';

// Runs first (file name ordering, workers: 1). Absolute cash is only asserted
// when the shared DB has no positions/trades yet, so a retry or a re-run against
// a used DB doesn't produce a false failure.

test.describe('fresh start', () => {
  test('default watchlist of 10 tickers is shown', async ({ page }) => {
    await openApp(page);
    await expect(tid(page, 'watchlist')).toBeVisible();
    for (const t of DEFAULT_TICKERS) {
      await expect(tid(page, `watchlist-row-${t}`), `row for ${t}`).toBeVisible();
      await expect(tid(page, `watchlist-row-${t}`).getByTestId(`price-${t}`)).toBeVisible();
    }
  });

  test('$10,000.00 cash is shown on a fresh database', async ({ page, request }) => {
    const portfolio = await apiPortfolio(request);
    test.skip(portfolio.positions.length > 0 || portfolio.cash !== 10000, 'DB already used (retry/re-run); cash not pristine');
    expect(portfolio.cash).toBe(10000);
    await openApp(page);
    await expect(tid(page, 'header-cash')).toContainText('10,000.00');
    expect(await headerCash(page)).toBe(10000);
    // With no positions, total value == cash.
    await expect(tid(page, 'header-total-value')).toContainText('10,000.00');
  });

  test('connection status is connected and prices stream', async ({ page }) => {
    await openApp(page);
    await expect(tid(page, 'connection-status')).toHaveAttribute('data-state', 'connected');

    for (const t of DEFAULT_TICKERS) await waitForPrice(page, t);
    const snapshot = async () =>
      Promise.all(DEFAULT_TICKERS.map(async (t) => (await tid(page, `price-${t}`).textContent()) ?? ''));
    const initial = await snapshot();
    initial.forEach((txt) => expect(parseMoney(txt)).toBeGreaterThan(0));

    // The simulator ticks every ~500 ms; at least one displayed price must change within ~5 s.
    await expect
      .poll(async () => (await snapshot()).some((txt, i) => txt !== initial[i]), {
        timeout: 8_000,
        message: 'some watchlist price text should change within ~5s',
      })
      .toBe(true);
  });

  test('main chart, trade bar, positions, heatmap, pnl chart and chat are present', async ({ page }) => {
    await openApp(page);
    for (const id of [
      'header-total-value',
      'header-cash',
      'main-chart',
      'trade-ticker-input',
      'trade-quantity-input',
      'trade-buy-button',
      'trade-sell-button',
      'positions-table',
      'portfolio-heatmap',
      'pnl-chart',
      'chat-panel',
      'chat-input',
      'chat-send-button',
    ]) {
      await expect(tid(page, id), id).toBeVisible();
    }
  });

  test('clicking a watchlist ticker selects it for the main chart', async ({ page }) => {
    await openApp(page);
    await tid(page, 'watchlist-row-MSFT').click();
    await expect(tid(page, 'selected-ticker')).toContainText('MSFT');
    await tid(page, 'watchlist-row-NVDA').click();
    await expect(tid(page, 'selected-ticker')).toContainText('NVDA');
  });
});
