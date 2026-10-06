import { expect, test } from '@playwright/test';
import { apiTrade, openApp, tid, waitForPrice } from './helpers';

// Owns ticker: META (held position for the heatmap).

test.describe('portfolio visualisation', () => {
  test('heatmap shows a cell for a held ticker', async ({ page, request }) => {
    const buy = await apiTrade(request, 'META', 'buy', 1);
    expect(buy.status(), await buy.text()).toBe(200);

    await openApp(page);
    await waitForPrice(page, 'META');
    const heatmap = tid(page, 'portfolio-heatmap');
    await expect(heatmap).toBeVisible();
    // A treemap cell is labelled with its ticker (SVG/DOM text).
    await expect(heatmap).toContainText('META');
    const box = await heatmap.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(50);
    expect(box?.height ?? 0).toBeGreaterThan(50);
  });

  test('P&L chart has data after a trade', async ({ page, request }) => {
    const buy = await apiTrade(request, 'META', 'buy', 1);
    expect(buy.status(), await buy.text()).toBe(200);

    // Every trade records a snapshot.
    const hist = await (await request.get('/api/portfolio/history')).json();
    expect(Array.isArray(hist.snapshots)).toBe(true);
    expect(hist.snapshots.length).toBeGreaterThan(0);
    const last = hist.snapshots[hist.snapshots.length - 1];
    expect(typeof last.total_value).toBe('number');
    expect(typeof last.recorded_at).toBe('string');

    await openApp(page);
    const chart = tid(page, 'pnl-chart');
    await expect(chart).toBeVisible();
    // Rendered with canvas (Lightweight Charts) or SVG (Recharts).
    await expect(chart.locator('canvas, svg').first()).toBeVisible();
  });

  test('positions table shows the held position with P&L fields', async ({ page }) => {
    await openApp(page);
    const row = tid(page, 'position-row-META');
    await expect(row).toBeVisible();
    await expect(row).toContainText('META');
    // Some numeric content (qty, avg cost, price, P&L).
    await expect(row).toContainText(/\d+\.\d{2}/);
  });
});
