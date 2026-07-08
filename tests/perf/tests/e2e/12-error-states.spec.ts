// UI error handling and interaction edge cases.

import { test, expect } from '@playwright/test';
import {
  searchAddress,
  expectBanner,
  expectNoResults,
  selectors,
} from '../../helpers/ui';

test.describe('error states', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('query too broad shows API error message', async ({ page }) => {
    await searchAddress(page, 'TX');
    await expectBanner(page, 'error');
    await expect(page.locator(selectors.message)).toContainText(/ZIP|city|state/i);
    await expectNoResults(page);
  });

  test('no matches shows info message', async ({ page }) => {
    await searchAddress(page, 'main');
    await expectBanner(page, 'info');
    await expectNoResults(page);
  });

  test('submit stays disabled without a selection', async ({ page }) => {
    await searchAddress(page, '1916 lombard ave berwyn il 60402');
    await expect(page.locator(selectors.results)).toBeVisible();
    await expect(page.locator(selectors.submitBtn)).toBeDisabled();
  });

  test('Enter key in query field triggers search', async ({ page }) => {
    await page.fill(selectors.query, '500 e monroe st springfield il');
    await page.press(selectors.query, 'Enter');
    await expect(page.locator(selectors.results)).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(selectors.resultRow).first()).toBeVisible();
  });

  test('whitespace-only query shows validation error', async ({ page }) => {
    await page.fill(selectors.query, '   ');
    await page.click(selectors.searchBtn);
    await expectBanner(page, 'error');
    await expectNoResults(page);
  });
});
