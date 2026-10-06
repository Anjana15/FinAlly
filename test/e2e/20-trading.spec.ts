import { expect, test } from '@playwright/test';
import { apiFlatten, apiQty, apiTrade, headerCash, openApp, tid, uiTrade, waitForPrice } from './helpers';

// Owns tickers: JPM (buy), V (sell to zero), GOOGL (partial sell), AMZN (insufficient shares).
// Cash is shared across specs, so we only assert relative changes.

test.describe('trading', () => {
  test('buy shares: cash decreases, position row appears', async ({ page, request }) => {
    await apiFlatten(request, 'JPM');
    await openApp(page);
    await waitForPrice(page, 'JPM');
    const cashBefore = await headerCash(page);
    await expect(tid(page, 'position-row-JPM')).toHaveCount(0);

    await uiTrade(page, 'JPM', 2, 'buy');

    await expect(tid(page, 'trade-message')).toHaveAttribute('data-status', 'executed');
    await expect(tid(page, 'positions-table').getByTestId('position-row-JPM')).toBeVisible();
    await expect(tid(page, 'position-row-JPM')).toContainText('JPM');
    await expect.poll(() => headerCash(page)).toBeLessThan(cashBefore);
    expect(await apiQty(request, 'JPM')).toBeCloseTo(2, 4);

    // Header cash reflects the backend cash exactly (to the cent).
    const portfolio = await (await request.get('/api/portfolio')).json();
    await expect.poll(() => headerCash(page)).toBeCloseTo(portfolio.cash, 2);
  });

  test('fractional quantity is accepted', async ({ page, request }) => {
    await apiFlatten(request, 'JPM');
    await openApp(page);
    await waitForPrice(page, 'JPM');
    await uiTrade(page, 'JPM', 0.5, 'buy');
    await expect(tid(page, 'position-row-JPM')).toBeVisible();
    expect(await apiQty(request, 'JPM')).toBeCloseTo(0.5, 4);
    await apiFlatten(request, 'JPM');
  });

  test('sell all shares: cash increases, position disappears', async ({ page, request }) => {
    await apiFlatten(request, 'V');
    const buy = await apiTrade(request, 'V', 'buy', 3);
    expect(buy.status(), await buy.text()).toBe(200);

    await openApp(page);
    await waitForPrice(page, 'V');
    await expect(tid(page, 'position-row-V')).toBeVisible();
    const cashBefore = await headerCash(page);

    await uiTrade(page, 'V', 3, 'sell');

    await expect(tid(page, 'trade-message')).toHaveAttribute('data-status', 'executed');
    await expect(tid(page, 'position-row-V')).toHaveCount(0);
    await expect.poll(() => headerCash(page)).toBeGreaterThan(cashBefore);
    expect(await apiQty(request, 'V')).toBe(0);
  });

  test('partial sell: position quantity is reduced', async ({ page, request }) => {
    await apiFlatten(request, 'GOOGL');
    const buy = await apiTrade(request, 'GOOGL', 'buy', 5);
    expect(buy.status(), await buy.text()).toBe(200);

    await openApp(page);
    await waitForPrice(page, 'GOOGL');
    const cashBefore = await headerCash(page);

    await uiTrade(page, 'GOOGL', 2, 'sell');

    await expect.poll(() => headerCash(page)).toBeGreaterThan(cashBefore);
    await expect(tid(page, 'position-row-GOOGL')).toBeVisible();
    await expect(tid(page, 'position-row-GOOGL')).toContainText('3');
    expect(await apiQty(request, 'GOOGL')).toBeCloseTo(3, 4);
    await apiFlatten(request, 'GOOGL');
  });

  test('selling more than held shows an error and changes nothing', async ({ page, request }) => {
    await apiFlatten(request, 'AMZN');
    await openApp(page);
    await waitForPrice(page, 'AMZN');
    const cashBefore = await headerCash(page);

    await uiTrade(page, 'AMZN', 5, 'sell');

    await expect(tid(page, 'trade-message')).toHaveAttribute('data-status', 'failed');
    await expect(tid(page, 'trade-message')).toContainText(/AMZN/);
    await expect(tid(page, 'position-row-AMZN')).toHaveCount(0);
    expect(await headerCash(page)).toBeCloseTo(cashBefore, 2);
  });

  test('buying with insufficient cash shows an error', async ({ page }) => {
    await openApp(page);
    await waitForPrice(page, 'AMZN');
    const cashBefore = await headerCash(page);

    await uiTrade(page, 'AMZN', 1_000_000, 'buy');

    await expect(tid(page, 'trade-message')).toHaveAttribute('data-status', 'failed');
    await expect(tid(page, 'trade-message')).toContainText(/AMZN/);
    await expect(tid(page, 'position-row-AMZN')).toHaveCount(0);
    expect(await headerCash(page)).toBeCloseTo(cashBefore, 2);
  });
});
