// End-to-end verify flow through nginx: search -> pick -> submit.

import { test, expect } from '@playwright/test';
import {
  searchAddress,
  waitForResults,
  selectResult,
  submitSelection,
  expectBanner,
  resultCount,
  selectors,
} from '../../helpers/ui';
import { FUNCTEST_PREFIX, FUNCTEST_RUN_ID } from '../../helpers/api';

const FLOW_QUERY = '1916 lombard ave berwyn il 60402';

test.describe('verify flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/submit', async (route) => {
      const post = route.request().postDataJSON();
      post.query = `${FUNCTEST_PREFIX}${FUNCTEST_RUN_ID}::${post.query ?? FLOW_QUERY}`;
      await route.continue({ postData: JSON.stringify(post) });
    });
    await page.goto('/');
  });

  test('search, select a match, and submit to nad_sub', async ({ page }) => {
    await searchAddress(page, FLOW_QUERY);
    await waitForResults(page);

    const count = await resultCount(page).count();
    expect(count).toBeGreaterThan(0);
    expect(count).toBeLessThanOrEqual(3);

    await expect(page.locator(`${selectors.resultRow} .score`).first()).toBeVisible();

    await selectResult(page, 0);
    await submitSelection(page);

    await expectBanner(page, 'success');
    await expect(page.locator(selectors.message)).toContainText('nad_sub');
    await expect(page.locator(selectors.results)).toBeHidden();
    await expect(page.locator(selectors.query)).toHaveValue('');
  });
});
