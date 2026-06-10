import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:5000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    headless: true,
  },

  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],

  webServer: {
    command: 'script/server',
    url: 'http://localhost:5000',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    // Force the deterministic fake GitHub client so the browser flow never
    // depends on live GitHub or unauthenticated API rate limits.
    env: {
      USE_FAKE_GITHUB_CLIENT: '1',
    },
  },
});
