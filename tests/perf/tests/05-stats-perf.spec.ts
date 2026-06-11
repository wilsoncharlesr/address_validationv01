// GET /api/stats runs count(*) plus two GROUP BYs over the 4.86M-row NAD
// table AND the submissions table, sequentially, with no caching — by far the
// most expensive endpoint. This spec measures it alone, then proves (or
// disproves) that a trickle of stats traffic degrades /api/verify latency.

import { test, expect, request } from '@playwright/test';
import { closedLoop } from '../helpers/loadgen';
import { summarize, formatReport, Shot } from '../helpers/metrics';
import { BASE_URL, envInt, fireStats, fireVerify } from '../helpers/api';
import { ZIP_QUERIES, pick } from '../helpers/queries';

const STATS_N = envInt('STATS_N', 5);
const STATS_P95_MS = envInt('STATS_P95_MS', 5000);
const INTERFERENCE_TOLERANCE = envInt('STATS_INTERFERENCE_FACTOR', 3); // verify p95 may grow at most this much

test.describe('stats endpoint cost', () => {
  test('response shape is correct', async ({ request: ctx }) => {
    const resp = await fireStats(ctx);
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.nad.total).toBeGreaterThan(0);
    expect(Array.isArray(body.nad.byState)).toBe(true);
    expect(Array.isArray(body.nad.byCounty)).toBe(true);
    expect(body.nadSub.total).toBeGreaterThanOrEqual(0);
  });

  test(`sequential cost (${STATS_N} calls)`, async ({}, testInfo) => {
    const ctx = await request.newContext({ baseURL: BASE_URL });
    const shots: Shot[] = [];
    const t0 = performance.now();
    try {
      for (let i = 0; i < STATS_N; i++) {
        const s0 = performance.now();
        const resp = await fireStats(ctx);
        await resp.body();
        shots.push({ ok: resp.ok(), status: resp.status(), ms: performance.now() - s0 });
      }
    } finally {
      await ctx.dispose();
    }
    const r = summarize('stats sequential', shots, performance.now() - t0);
    console.log(formatReport(r));
    await testInfo.attach('stats-sequential.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });

    expect(r.errorRate).toBe(0);
    expect(r.p95, `stats p95 ${r.p95.toFixed(0)}ms — uncached full-table aggregates`).toBeLessThan(STATS_P95_MS);
  });

  test('stats traffic must not wreck verify latency', async ({}, testInfo) => {
    // Baseline: verify alone.
    const baseline = await closedLoop({
      label: 'verify alone',
      baseURL: BASE_URL,
      workers: 5,
      durationMs: 8000,
      fire: (ctx, seq) => fireVerify(ctx, pick(ZIP_QUERIES, seq)),
    });
    console.log(formatReport(baseline));

    // Same verify load with one stats client hammering in parallel.
    const statsCtx = await request.newContext({ baseURL: BASE_URL });
    let statsRunning = true;
    const statsLoop = (async () => {
      while (statsRunning) {
        try {
          const r = await fireStats(statsCtx);
          await r.body();
        } catch { /* server saturated — that is the point */ }
      }
    })();

    let contended;
    try {
      contended = await closedLoop({
        label: 'verify + stats contention',
        baseURL: BASE_URL,
        workers: 5,
        durationMs: 8000,
        fire: (ctx, seq) => fireVerify(ctx, pick(ZIP_QUERIES, seq)),
      });
    } finally {
      statsRunning = false;
      await statsLoop;
      await statsCtx.dispose();
    }
    console.log(formatReport(contended));

    const factor = contended.p95 / Math.max(baseline.p95, 1);
    await testInfo.attach('stats-interference.json', {
      body: JSON.stringify({ baseline, contended, degradationFactor: factor }, null, 2),
      contentType: 'application/json',
    });

    expect(
      factor,
      `verify p95 degraded ${factor.toFixed(1)}x (${baseline.p95.toFixed(0)}ms -> ${contended.p95.toFixed(0)}ms) ` +
        'while one client polled /api/stats — cache the stats aggregates (TTL) before going to production load',
    ).toBeLessThan(INTERFERENCE_TOLERANCE);
  });
});
