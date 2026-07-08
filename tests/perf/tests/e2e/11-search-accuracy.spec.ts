// Regression tests for the regex-based multi-path search parser.

import { test, expect } from '@playwright/test';
import { request } from '@playwright/test';
import { WEB_BASE_URL } from '../../helpers/api';
import { assertTopMatch } from '../../helpers/assertions';
import expectedMatches from '../../fixtures/expected-matches.json';
import {
  searchAddress,
  waitForResults,
  expectBanner,
  expectNoResults,
} from '../../helpers/ui';

interface ExpectedMatch {
  query: string;
  addressContains?: string;
  cityContains?: string;
  state?: string;
  minScore?: number;
  description?: string;
}

const fixtures = expectedMatches as ExpectedMatch[];

test.describe.configure({ mode: 'serial' });

test.describe('search accuracy', () => {
  for (const fixture of fixtures) {
    test(fixture.description ?? fixture.query, async ({ page }) => {
      await page.goto('/');
      const respPromise = page.waitForResponse(
        (r) => r.url().includes('/api/verify') && r.request().method() === 'POST',
      );
      await searchAddress(page, fixture.query);
      const resp = await respPromise;
      await waitForResults(page);

      const matches = await resp.json();
      assertTopMatch(matches, {
        addressContains: fixture.addressContains,
        cityContains: fixture.cityContains,
        state: fixture.state,
        minScore: fixture.minScore,
      });
    });
  }

  test('empty query shows inline error', async ({ page }) => {
    await page.goto('/');
    await page.click('#searchBtn');
    await expectBanner(page, 'error');
    await expectNoResults(page);
  });
});

test.describe('search accuracy (API via nginx)', () => {
  test('555 Monroe ranks Monroe street above city-only matches', async () => {
    const ctx = await request.newContext({ baseURL: WEB_BASE_URL });
    try {
      const resp = await ctx.post('/api/verify', { data: { query: '555 Monroe' } });
      expect(resp.status()).toBe(200);
      const matches = await resp.json();
      assertTopMatch(matches, { addressContains: 'Monroe', minScore: 0.5 });
    } finally {
      await ctx.dispose();
    }
  });
});
