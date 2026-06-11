// Write-path performance: POST /api/submit inserts one row into
// nad_sub.submissions per call. WARNING: this test writes real rows. Every
// row is tagged with query_text = 'PERFTEST::<run>::<seq>' so they can be
// removed afterwards:
//   psql -d nad_sub -c "DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%'"

import { test, expect } from '@playwright/test';
import { closedLoop } from '../helpers/loadgen';
import { formatReport } from '../helpers/metrics';
import { BASE_URL, envInt, envFloat, fireSubmit } from '../helpers/api';

const WORKERS = envInt('SUBMIT_WORKERS', 10);
const DURATION_S = envInt('SUBMIT_DURATION_S', 10);
const P95_MS = envInt('SUBMIT_P95_MS', 200);
const ERROR_RATE_MAX = envFloat('ERROR_RATE_MAX', 0.01);

test.describe('submit write path', () => {
  test('single submit returns an id', async ({ request: ctx }) => {
    const resp = await fireSubmit(ctx, 0);
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(typeof body.id).toBe('number');

    // missing address is rejected without touching the database
    const bad = await ctx.post('/api/submit', { data: { address: '' } });
    expect(bad.status()).toBe(400);
  });

  test(`sustained inserts @ ${WORKERS} workers for ${DURATION_S}s`, async ({}, testInfo) => {
    const r = await closedLoop({
      label: `submit @ ${WORKERS} workers`,
      baseURL: BASE_URL,
      workers: WORKERS,
      durationMs: DURATION_S * 1000,
      fire: (ctx, seq) => fireSubmit(ctx, seq),
    });
    console.log(formatReport(r));
    await testInfo.attach('submit-load.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });

    expect(r.errorRate, `submit error rate ${(r.errorRate * 100).toFixed(2)}%`).toBeLessThanOrEqual(ERROR_RATE_MAX);
    expect(r.p95, `submit p95 ${r.p95.toFixed(0)}ms > ${P95_MS}ms (single-row INSERT should be fast)`).toBeLessThan(P95_MS);
    console.log(`NOTE: this run inserted ~${r.count} tagged rows into nad_sub.submissions — see file header for cleanup SQL`);
  });
});
