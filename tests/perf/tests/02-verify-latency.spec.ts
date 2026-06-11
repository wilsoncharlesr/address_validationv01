// Single-user latency distribution for POST /api/verify, split by the three
// code paths in AddressRepository.SearchAsync. Since the API caches results
// by normalized query, every sample here uses a UNIQUE query (varying house
// number) so the numbers measure the real database path, not the cache.
// Cache-hit latency is measured separately at the end. The miss numbers
// drive all capacity math:
//   required DB capacity ~= miss_rate * 10_000 req/s * (mean DB ms) / 1000 cores.

import { test, expect, request, APIRequestContext } from '@playwright/test';
import { summarize, formatReport, Shot, LoadReport } from '../helpers/metrics';
import { BASE_URL, envInt, fireVerify } from '../helpers/api';
import { ZIP_QUERIES, KNN_QUERIES, BAD_ZIP_QUERIES, uniqueQuery } from '../helpers/queries';

const N = envInt('VERIFY_LATENCY_N', 30);
// Defaults reflect measured reality on a dev laptop (4.86M-row table in
// dockerized Postgres): zip-path misses ~35ms p50 / ~100ms p95; a full
// trigram-KNN miss costs ~1.2s p50 — that is index-traversal CPU, the reason
// the verify cache and ZIP extraction are load-bearing. Tighten in CI.
const ZIP_P95_MS = envInt('VERIFY_ZIP_P95_MS', 200);
const KNN_P95_MS = envInt('VERIFY_KNN_P95_MS', 2000);
const BADZIP_P95_MS = envInt('VERIFY_BADZIP_P95_MS', 2000);
const HIT_P95_MS = envInt('VERIFY_CACHE_HIT_P95_MS', 50);

// Offset the seq per run so a rerun against the same server process doesn't
// accidentally hit entries cached by the previous run.
const SEQ_BASE = (Date.now() % 9000) * 1000;

async function measureMisses(label: string, queries: string[]): Promise<LoadReport> {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  const shots: Shot[] = [];
  const t0 = performance.now();
  try {
    // One unmeasured pass over the corpus shapes: warms DB pages, prepared
    // statements, and pool connections without polluting the percentiles.
    for (let i = 0; i < queries.length; i++) {
      await (await fireVerify(ctx, uniqueQuery(queries, SEQ_BASE + 900_000 + i))).body();
    }
    for (let i = 0; i < N; i++) {
      const q = uniqueQuery(queries, SEQ_BASE + i);
      const s0 = performance.now();
      const resp = await fireVerify(ctx, q);
      await resp.body();
      shots.push({ ok: resp.ok(), status: resp.status(), ms: performance.now() - s0 });
    }
  } finally {
    await ctx.dispose();
  }
  return summarize(label, shots, performance.now() - t0);
}

test.describe('verify latency by code path (cache misses)', () => {
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
    const r = await measureMisses('verify miss: zip fast path', ZIP_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-zip.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `zip-path p95 ${r.p95.toFixed(0)}ms > ${ZIP_P95_MS}ms`).toBeLessThan(ZIP_P95_MS);
  });

  test('KNN path (no ZIP — full trigram GiST scan)', async ({}, testInfo) => {
    const r = await measureMisses('verify miss: knn path', KNN_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-knn.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `knn-path p95 ${r.p95.toFixed(0)}ms > ${KNN_P95_MS}ms`).toBeLessThan(KNN_P95_MS);
  });

  test('bad-ZIP fallthrough (worst case: zip query + knn query)', async ({}, testInfo) => {
    const r = await measureMisses('verify miss: bad-zip fallthrough', BAD_ZIP_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-badzip.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `bad-zip p95 ${r.p95.toFixed(0)}ms > ${BADZIP_P95_MS}ms`).toBeLessThan(BADZIP_P95_MS);
  });

  test('cache hit latency (repeated query)', async ({}, testInfo) => {
    const ctx = await request.newContext({ baseURL: BASE_URL });
    const shots: Shot[] = [];
    const query = ZIP_QUERIES[0];
    const t0 = performance.now();
    try {
      await (await fireVerify(ctx, query)).body(); // populate the entry
      for (let i = 0; i < N; i++) {
        const s0 = performance.now();
        const resp = await fireVerify(ctx, query);
        await resp.body();
        shots.push({ ok: resp.ok(), status: resp.status(), ms: performance.now() - s0 });
      }
    } finally {
      await ctx.dispose();
    }
    const r = summarize('verify hit: cached query', shots, performance.now() - t0);
    console.log(formatReport(r));
    await testInfo.attach('verify-hit.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(
      r.p95,
      `cache-hit p95 ${r.p95.toFixed(1)}ms > ${HIT_P95_MS}ms — hits should cost no more than the HTTP stack itself`,
    ).toBeLessThan(HIT_P95_MS);
  });
});
