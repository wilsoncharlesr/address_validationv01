// Perceived UI latency: time from user action to visible feedback.

import { test, expect } from '@playwright/test';
import { summarize, formatReport, Shot } from '../../helpers/metrics';
import { envInt } from '../../helpers/api';
import {
  searchAddress,
  waitForResults,
  selectResult,
  submitSelection,
  expectBanner,
  selectors,
} from '../../helpers/ui';
import { FUNCTEST_PREFIX, FUNCTEST_RUN_ID } from '../../helpers/api';

const N = envInt('UI_LATENCY_N', 10);
const SEARCH_P95_MS = envInt('UI_SEARCH_P95_MS', 2000);
const SUBMIT_P95_MS = envInt('UI_SUBMIT_P95_MS', 500);

const FLOW_QUERY = '1916 lombard ave berwyn il 60402';

test.describe('UI perceived latency', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/submit', async (route) => {
      const post = route.request().postDataJSON();
      post.query = `${FUNCTEST_PREFIX}${FUNCTEST_RUN_ID}::ui-latency`;
      await route.continue({ postData: JSON.stringify(post) });
    });
  });

  test(`search to results visible (p95 < ${SEARCH_P95_MS}ms, n=${N})`, async ({ page }, testInfo) => {
    const shots: Shot[] = [];
    await page.goto('/');

    for (let i = 0; i < N; i++) {
      await page.fill(selectors.query, FLOW_QUERY);
      const t0 = performance.now();
      await page.click(selectors.searchBtn);
      await waitForResults(page);
      shots.push({ ok: true, status: 200, ms: performance.now() - t0 });
      await page.reload();
    }

    const report = summarize('ui: search -> results', shots, shots.reduce((a, s) => a + s.ms, 0));
    console.log(formatReport(report));
    await testInfo.attach('ui-search-latency.json', {
      body: JSON.stringify(report, null, 2),
      contentType: 'application/json',
    });
    expect(report.p95, `search p95 ${report.p95.toFixed(0)}ms`).toBeLessThan(SEARCH_P95_MS);
  });

  test(`submit to success banner (p95 < ${SUBMIT_P95_MS}ms, n=${N})`, async ({ page }, testInfo) => {
    const shots: Shot[] = [];

    for (let i = 0; i < N; i++) {
      await page.goto('/');
      await searchAddress(page, FLOW_QUERY);
      await waitForResults(page);
      await selectResult(page, 0);

      const t0 = performance.now();
      await submitSelection(page);
      await expectBanner(page, 'success');
      shots.push({ ok: true, status: 200, ms: performance.now() - t0 });
    }

    const report = summarize('ui: submit -> success', shots, shots.reduce((a, s) => a + s.ms, 0));
    console.log(formatReport(report));
    await testInfo.attach('ui-submit-latency.json', {
      body: JSON.stringify(report, null, 2),
      contentType: 'application/json',
    });
    expect(report.p95, `submit p95 ${report.p95.toFixed(0)}ms`).toBeLessThan(SUBMIT_P95_MS);
  });
});
