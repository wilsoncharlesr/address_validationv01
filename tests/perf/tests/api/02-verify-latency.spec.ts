// Single-user latency distribution for POST /api/verify, split by the search
// paths in AddressRepository.SearchAsync.

import { test, expect, request } from '@playwright/test';
import { summarize, formatReport, Shot, LoadReport } from '../../helpers/metrics';
import { API_BASE_URL, envInt, fireVerify } from '../../helpers/api';
import {
  ZIP_QUERIES,
  LOCALITY_QUERIES,
  STREET_QUERIES,
  FUSION_QUERIES,
  BAD_ZIP_QUERIES,
  pick,
} from '../../helpers/queries';
import { assertMatchShape, assertTopMatch } from '../../helpers/assertions';
import { readStackState } from '../../helpers/stack-state';

const N = envInt('VERIFY_LATENCY_N', 30);
const ZIP_P95_MS = envInt('VERIFY_ZIP_P95_MS', 200);
const LOCALITY_P95_MS = envInt('VERIFY_LOCALITY_P95_MS', envInt('VERIFY_KNN_P95_MS', 800));
const STREET_P95_MS = envInt('VERIFY_STREET_P95_MS', 500);
const FUSION_P95_MS = envInt('VERIFY_FUSION_P95_MS', 800);
const BADZIP_P95_MS = envInt('VERIFY_BADZIP_P95_MS', 1200);
const skipUnindexed = readStackState().skipUnindexed;

async function measure(label: string, queries: string[]): Promise<LoadReport> {
  const ctx = await request.newContext({ baseURL: API_BASE_URL });
  const shots: Shot[] = [];
  const t0 = performance.now();
  try {
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
  test('response shape, ranking, street-first accuracy, and broad-query 422', async ({ request: ctx }) => {
    const resp = await fireVerify(ctx, ZIP_QUERIES[0]);
    expect(resp.status()).toBe(200);
    const matches = await resp.json();
    assertMatchShape(matches);

    const streetResp = await fireVerify(ctx, '555 Monroe');
    expect(streetResp.status()).toBe(200);
    const streetMatches = await streetResp.json();
    assertTopMatch(streetMatches, { addressContains: 'Monroe', minScore: 0.5 });

    const broad = await fireVerify(ctx, 'TX');
    expect(broad.status()).toBe(422);

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

  test('locality path (city/state btree)', async ({}, testInfo) => {
    test.skip(skipUnindexed, 'street indexes not built on active NAD table');
    const r = await measure('verify: locality path', LOCALITY_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-locality.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `locality-path p95 ${r.p95.toFixed(0)}ms > ${LOCALITY_P95_MS}ms`).toBeLessThan(LOCALITY_P95_MS);
  });

  test('street-first path (house number + street prefix)', async ({}, testInfo) => {
    test.skip(skipUnindexed, 'street indexes not built on active NAD table');
    const r = await measure('verify: street-first path', STREET_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-street.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `street-path p95 ${r.p95.toFixed(0)}ms > ${STREET_P95_MS}ms`).toBeLessThan(STREET_P95_MS);
  });

  test('fusion path (ambiguous street-or-city merge)', async ({}, testInfo) => {
    test.skip(skipUnindexed, 'street indexes not built on active NAD table');
    const r = await measure('verify: fusion path', FUSION_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-fusion.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `fusion-path p95 ${r.p95.toFixed(0)}ms > ${FUSION_P95_MS}ms`).toBeLessThan(FUSION_P95_MS);
  });

  test('bad-ZIP fallthrough (zip miss + locality/street)', async ({}, testInfo) => {
    const r = await measure('verify: bad-zip fallthrough', BAD_ZIP_QUERIES);
    console.log(formatReport(r));
    await testInfo.attach('verify-badzip.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });
    expect(r.errorRate).toBe(0);
    expect(r.p95, `bad-zip p95 ${r.p95.toFixed(0)}ms > ${BADZIP_P95_MS}ms`).toBeLessThan(BADZIP_P95_MS);
  });
});
