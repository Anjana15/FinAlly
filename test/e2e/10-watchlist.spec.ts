import { expect, test } from '@playwright/test';
import { apiEnsureNotWatched, openApp, tid, waitForPrice } from './helpers';

// Owns tickers: PYPL (UI add/remove), DIS (lowercase input normalisation).

test.describe('watchlist', () => {
  test('add PYPL via the UI, it streams a price, then remove it', async ({ page, request }) => {
    await apiEnsureNotWatched(request, 'PYPL');
    await openApp(page);
    await expect(tid(page, 'watchlist-row-PYPL')).toHaveCount(0);

    await tid(page, 'watchlist-add-input').fill('PYPL');
    await tid(page, 'watchlist-add-button').click();

    await expect(tid(page, 'watchlist-row-PYPL')).toBeVisible();
    // Newly added ticker must get a price from the stream.
    expect(await waitForPrice(page, 'PYPL')).toBeGreaterThan(0);

    // Persisted on the backend.
    const list = await (await request.get('/api/watchlist')).json();
    expect(list.tickers.map((t: { ticker: string }) => t.ticker)).toContain('PYPL');

    // Survives a reload.
    await page.reload();
    await expect(tid(page, 'watchlist-row-PYPL')).toBeVisible();

    await tid(page, 'watchlist-remove-PYPL').click();
    await expect(tid(page, 'watchlist-row-PYPL')).toHaveCount(0);

    const after = await (await request.get('/api/watchlist')).json();
    expect(after.tickers.map((t: { ticker: string }) => t.ticker)).not.toContain('PYPL');

    await page.reload();
    await expect(tid(page, 'watchlist')).toBeVisible();
    await expect(tid(page, 'watchlist-row-PYPL')).toHaveCount(0);
  });

  test('lowercase input is normalised to uppercase', async ({ page, request }) => {
    await apiEnsureNotWatched(request, 'DIS');
    await openApp(page);
    await tid(page, 'watchlist-add-input').fill('dis');
    await tid(page, 'watchlist-add-button').click();
    await expect(tid(page, 'watchlist-row-DIS')).toBeVisible();
    await tid(page, 'watchlist-remove-DIS').click();
    await expect(tid(page, 'watchlist-row-DIS')).toHaveCount(0);
  });

  test('watchlist API: add, duplicate, remove, remove-missing', async ({ request }) => {
    await apiEnsureNotWatched(request, 'PYPL');
    const add = await request.post('/api/watchlist', { data: { ticker: 'pypl' } });
    expect(add.status()).toBe(200);
    expect(await add.json()).toMatchObject({ ticker: 'PYPL', status: 'added' });

    const dup = await request.post('/api/watchlist', { data: { ticker: 'PYPL' } });
    expect(dup.status()).toBe(200);
    expect(await dup.json()).toMatchObject({ ticker: 'PYPL', status: 'exists' });

    const del = await request.delete('/api/watchlist/PYPL');
    expect(del.status()).toBe(200);
    expect(await del.json()).toMatchObject({ ticker: 'PYPL', status: 'removed' });

    const missing = await request.delete('/api/watchlist/PYPL');
    expect(missing.status()).toBe(404);
    expect(await missing.json()).toMatchObject({ error: 'not_found' });
  });
});
