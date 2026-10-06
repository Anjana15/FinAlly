import { defineConfig, devices } from '@playwright/test';

/**
 * FinAlly E2E config.
 *
 * The app is expected to be already running (docker-compose.test.yml starts it as
 * `app` and sets BASE_URL=http://app:8000; locally, start uvicorn on :8000 with
 * LLM_MOCK=true). All specs share ONE backend database, so we run serially
 * (workers: 1) and specs assert relative changes on distinct tickers.
 * Files are numbered so the fresh-start spec runs first.
 */
const BASE_URL = process.env.BASE_URL || 'http://localhost:8000';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 1,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    viewport: { width: 1600, height: 1000 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 1000 } },
    },
  ],
});
