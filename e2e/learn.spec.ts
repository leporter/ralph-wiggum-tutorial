import { test, expect } from '@playwright/test';

/**
 * E2E coverage for the /learn codebase-learning flow.
 *
 * Uses the deterministic fake GitHub client (enabled via USE_FAKE_GITHUB_CLIENT
 * in playwright.config.ts) so the journey never depends on live GitHub. We
 * cover the smallest high-value student path: submit the fixture URL, see the
 * generated learning path (overview, key files, reading order, ≥1 blob link),
 * then revisit the saved-result URL and confirm it renders from initialAnalysis
 * without re-submitting.
 */
const FIXTURE_URL = 'https://github.com/python/cpython/tree/main/Lib/idlelib';

test.describe('Learn a Codebase', () => {
  test('generates and persists a learning path', async ({ page }) => {
    await page.goto('/learn');

    await expect(page.locator('[data-island="learn"]')).toBeVisible();

    // Capture the analyze response so we can revisit the saved-result URL.
    const responsePromise = page.waitForResponse(
      (r) => r.url().includes('/learn/analyze') && r.request().method() === 'POST',
    );

    await page.getByLabel('GitHub repository URL').fill(FIXTURE_URL);
    await page.getByRole('button', { name: /generate learning path/i }).click();

    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const body = await response.json();
    const analysisId = body.analysis.id as string;
    expect(analysisId).toBeTruthy();

    // Repository overview is shown.
    await expect(
      page.getByRole('heading', { name: 'python/cpython/Lib/idlelib' }),
    ).toBeVisible();

    // Reading order, key files, and at least one GitHub blob link are present.
    await expect(page.getByText(/Suggested reading order/i)).toBeVisible();
    await expect(page.getByText(/Step 1:/)).toBeVisible();

    const blobLink = page.locator('a[href*="/blob/"]').first();
    await expect(blobLink).toBeVisible();

    // Revisit the saved result URL: it must render from initialAnalysis.
    await page.goto(`/learn/${analysisId}`);
    await expect(
      page.getByRole('heading', { name: 'python/cpython/Lib/idlelib' }),
    ).toBeVisible();
    await expect(page.getByText(/Suggested reading order/i)).toBeVisible();
  });
});
