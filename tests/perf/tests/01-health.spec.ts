// Baseline: /api/health never touches Postgres, so its latency isolates the
// cost of the HTTP stack (Kestrel + routing + JSON) plus the network path.
// If this is slow, nothing downstream can be fast.

import { test, expect, request } from '@playwright/test';
import { summarize, formatReport, Shot } from '../helpers/metrics';
import { BASE_URL, envInt, fireHealth } from '../helpers/api';

const HEALTH_N = envInt('HEALTH_N', 200);
const HEALTH_P95_MS = envInt('HEALTH_P95_MS', 100);

test.describe('health baseline', () => {
  test('responds ok with expected shape', async ({ request: ctx }) => {
    const resp = await fireHealth(ctx);
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.status).toBe('ok');
    expect(typeof body.table).toBe('string');
  });

  test(`sequential latency baseline (${HEALTH_N} calls)`, async ({}, testInfo) => {
    const ctx = await request.newContext({ baseURL: BASE_URL });
    const shots: Shot[] = [];
    const t0 = performance.now();
    try {
      for (let i = 0; i < HEALTH_N; i++) {
        const s0 = performance.now();
        const resp = await fireHealth(ctx);
        await resp.body();
        shots.push({ ok: resp.ok(), status: resp.status(), ms: performance.now() - s0 });
      }
    } finally {
      await ctx.dispose();
    }
    const report = summarize('health sequential', shots, performance.now() - t0);
    console.log(formatReport(report));
    await testInfo.attach('health-baseline.json', {
      body: JSON.stringify(report, null, 2),
      contentType: 'application/json',
    });

    expect(report.errorRate).toBe(0);
    expect(
      report.p95,
      `health p95 ${report.p95.toFixed(1)}ms exceeds ${HEALTH_P95_MS}ms — the HTTP stack itself is slow; ` +
        'fix this before interpreting any DB-bound numbers',
    ).toBeLessThan(HEALTH_P95_MS);
  });
});
