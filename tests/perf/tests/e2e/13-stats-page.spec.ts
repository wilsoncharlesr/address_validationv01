// Statistics page loads aggregates from both databases.

import { test, expect } from '@playwright/test';
import { selectors } from '../../helpers/ui';

test.describe('stats page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/stats.html');
  });

  test('loads NAD and nad_sub totals with breakdowns', async ({ page }) => {
    await expect(page.locator(selectors.nadTotal)).toContainText(/\d/, { timeout: 60_000 });

    await expect(page.locator(`${selectors.nadByState} .bar-row`).first())
      .toBeVisible({ timeout: 60_000 });
    await expect(page.locator(`${selectors.nadByCounty} .bar-row`).first())
      .toBeVisible({ timeout: 60_000 });

    await expect(page.locator(selectors.nadSubTotal)).toContainText(/\d/);
  });

  test('refresh reloads without error', async ({ page }) => {
    await expect(page.locator(selectors.nadTotal)).toContainText(/\d/, { timeout: 60_000 });
    await page.click(selectors.refreshBtn);
    await expect(page.locator(selectors.nadTotal)).toContainText(/\d/, { timeout: 60_000 });
    await expect(page.locator(`${selectors.message} .banner.error`)).toHaveCount(0);
  });
});
