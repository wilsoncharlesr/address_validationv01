// Single-user latency distribution for POST /api/verify, split by the three
// code paths in AddressRepository.SearchAsync. These are the per-request
// numbers that the capacity math for 10K req/s is built on:
//   required DB capacity ~= 10_000 req/s * (mean DB ms per request) / 1000 cores.

import { test, expect, request } from '@playwright/test';
import { summarize, formatReport, Shot, LoadReport } from '../helpers/metrics';
import { BASE_URL, envInt, fireVerify } from '../helpers/api';
import { ZIP_QUERIES, KNN_QUERIES, BAD_ZIP_QUERIES, pick } from '../helpers/queries';

const N = envInt('VERIFY_LATENCY_N', 30);
const ZIP_P95_MS = envInt('VERIFY_ZIP_P95_MS', 200);
const KNN_P95_MS = envInt('VERIFY_KNN_P95_MS', 800);
const BADZIP_P95_MS = envInt('VERIFY_BADZIP_P95_MS', 1200);

async function measure(label: string, queries: string[]): Promise<LoadReport> {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  const shots: Shot[] = [];
  const t0 = performance.now();
  try {
    // one un-measured warmup call so pool/index warm-up doesn't pollute p95
    await (await fireVerify(ctx, queries[0])).body();
    for (let i = 0; i < N; i++) {
      const s0 = performance.now();
      const resp = await fireVerify(ctx, pick(queries, i));
      await resp.body();
      shots.push({ ok: resp.ok(), status: resp.status(), ms: performance.now() - s0 });
    }
  } finally {
    await ctx.dispose();
  }
  return summarize(label, shots, performance.now() - t0);
}

test.describe('verify latency by code path', () => {
  test('response shape and ranking are correct', async ({ request: ctx }) => {
    const resp = await fireVerify(ctx, ZIP_QUERIES[0]);
    expect(resp.status()).toBe(200);
    const matches = await resp.json();
    expect(Array.isArray(matches)).toBe(true);
    expect(matches.length).toBeGreaterThan(0);
    expect(matches.length).toBeLessThanOrEqual(3);
    for (const m of matches) {
      expect(typeof m.address).toBe('string');
      expect(typeof m.score).toBe('number');
    }
    // results must be ranked best-first
    for (let i = 1; i < matches.length; i++) {
      expect(matches[i - 1].score).toBeGreaterThanOrEqual(matches[i].score);
    }
    // empty query is rejected, not searched
    const bad = await ctx.post('/api/verify', { data: { query: '   ' } });
    expect(bad.status()).toBe(400);
  });

  test('ZIP fast path (indexed zip filter)', async ({}, testInfo) => {
    const r = await measure('verify: zip fast path', ZIP_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-zip.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `zip-path p95 ${r.p95.toFixed(0)}ms > ${ZIP_P95_MS}ms`).toBeLessThan(ZIP_P95_MS);
  });

  test('KNN path (no ZIP — full trigram GiST scan)', async ({}, testInfo) => {
    const r = await measure('verify: knn path', KNN_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-knn.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `knn-path p95 ${r.p95.toFixed(0)}ms > ${KNN_P95_MS}ms`).toBeLessThan(KNN_P95_MS);
  });

  test('bad-ZIP fallthrough (worst case: zip query + knn query)', async ({}, testInfo) => {
    const r = await measure('verify: bad-zip fallthrough', BAD_ZIP_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-badzip.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `bad-zip p95 ${r.p95.toFixed(0)}ms > ${BADZIP_P95_MS}ms`).toBeLessThan(BADZIP_P95_MS);
  });
});
