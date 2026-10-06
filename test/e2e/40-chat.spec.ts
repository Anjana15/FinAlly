import { expect, test } from '@playwright/test';
import { apiEnsureNotWatched, apiFlatten, apiQty, openApp, sendChat, tid, waitForPrice } from './helpers';

// Relies on LLM_MOCK=true and the deterministic rules in TEAM_CONTRACT §4.
// Owns tickers: AAPL (chat buy), NFLX (chat failing sell), SHOP (chat watchlist add/remove).

const MOCK_DEFAULT = 'Mock response: I can help you analyze your portfolio, place trades, and manage your watchlist.';

test.describe('AI chat (LLM_MOCK)', () => {
  test('"buy 1 AAPL" executes a trade shown inline', async ({ page, request }) => {
    const qtyBefore = await apiQty(request, 'AAPL');
    await openApp(page);
    await waitForPrice(page, 'AAPL');

    const { body, message } = await sendChat(page, 'buy 1 AAPL');

    expect(body.role).toBe('assistant');
    expect(body.content).toBe('Placing a buy order for 1 AAPL.');
    expect(body.actions?.trades).toHaveLength(1);
    expect(body.actions?.trades[0]).toMatchObject({ status: 'executed', ticker: 'AAPL', side: 'buy' });

    // User message echoed in the panel.
    await expect(page.locator('[data-testid="chat-message"][data-role="user"]').last()).toContainText('buy 1 AAPL');
    await expect(message).toContainText('Placing a buy order for 1 AAPL.');

    const chip = tid(page, 'chat-panel').getByTestId('chat-action').last();
    await expect(chip).toHaveAttribute('data-status', 'executed');
    await expect(chip).toContainText('AAPL');

    await expect(tid(page, 'position-row-AAPL')).toBeVisible();
    expect(await apiQty(request, 'AAPL')).toBeCloseTo(qtyBefore + 1, 4);
  });

  test('"hello" returns the mock text and no actions', async ({ page }) => {
    await openApp(page);
    const { body, message } = await sendChat(page, 'hello');

    expect(body.content).toBe(MOCK_DEFAULT);
    expect(body.actions?.trades ?? []).toHaveLength(0);
    expect(body.actions?.watchlist_changes ?? []).toHaveLength(0);
    await expect(message).toContainText('Mock response');
    await expect(message.getByTestId('chat-action')).toHaveCount(0);
  });

  test('"sell 1000 NFLX" fails validation and is reported as failed', async ({ page, request }) => {
    await apiFlatten(request, 'NFLX');
    await openApp(page);

    const { body } = await sendChat(page, 'sell 1000 NFLX');

    expect(body.content).toBe('Placing a sell order for 1000 NFLX.');
    expect(body.actions?.trades[0]).toMatchObject({ status: 'failed', ticker: 'NFLX', error: 'insufficient_shares' });

    const chip = tid(page, 'chat-panel').getByTestId('chat-action').last();
    await expect(chip).toHaveAttribute('data-status', 'failed');
    await expect(tid(page, 'position-row-NFLX')).toHaveCount(0);
  });

  test('"add SHOP" / "remove SHOP" manage the watchlist', async ({ page, request }) => {
    await apiEnsureNotWatched(request, 'SHOP');
    await openApp(page);

    const added = await sendChat(page, 'add SHOP');
    expect(added.body.actions?.watchlist_changes[0]).toMatchObject({ ticker: 'SHOP', action: 'add', status: 'added' });
    await expect(tid(page, 'chat-panel').getByTestId('chat-action').last()).toHaveAttribute('data-status', 'added');
    await expect(tid(page, 'watchlist-row-SHOP')).toBeVisible();

    const removed = await sendChat(page, 'remove SHOP');
    expect(removed.body.actions?.watchlist_changes[0]).toMatchObject({ ticker: 'SHOP', action: 'remove', status: 'removed' });
    await expect(tid(page, 'chat-panel').getByTestId('chat-action').last()).toHaveAttribute('data-status', 'removed');
    await expect(tid(page, 'watchlist-row-SHOP')).toHaveCount(0);
  });

  test('chat history persists across reloads', async ({ page, request }) => {
    await openApp(page);
    const marker = `hello history ${Date.now()}`;
    await sendChat(page, marker);

    const hist = await (await request.get('/api/chat/history')).json();
    const contents = hist.messages.map((m: { content: string }) => m.content);
    expect(contents).toContain(marker);

    await page.reload();
    await expect(tid(page, 'chat-panel')).toContainText(marker);
  });

  test('empty message is rejected by the API', async ({ request }) => {
    const res = await request.post('/api/chat', { data: { message: '   ' } });
    expect(res.status()).toBe(400);
    expect(await res.json()).toMatchObject({ error: 'empty_message' });
  });
});
