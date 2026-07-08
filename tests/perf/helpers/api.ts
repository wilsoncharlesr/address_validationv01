// Thin wrappers over the four API endpoints, plus the env-var knobs every
// spec shares. Defaults are deliberately lenient enough for a dev laptop;
// tighten them in CI via environment variables.

import { APIRequestContext, APIResponse } from '@playwright/test';

export const API_BASE_URL = process.env.API_BASE_URL ?? 'http://localhost:8081';
export const WEB_BASE_URL = process.env.WEB_BASE_URL ?? 'http://localhost:8088';

/** @deprecated use API_BASE_URL */
export const BASE_URL = API_BASE_URL;

export function envInt(name: string, def: number): number {
  const v = process.env[name];
  const n = v === undefined ? NaN : Number(v);
  return Number.isFinite(n) ? n : def;
}

export function envFloat(name: string, def: number): number {
  const v = process.env[name];
  const n = v === undefined ? NaN : Number(v);
  return Number.isFinite(n) ? n : def;
}

export function envIntList(name: string, def: number[]): number[] {
  const v = process.env[name];
  if (!v) return def;
  const parsed = v.split(',').map(s => Number(s.trim())).filter(n => Number.isFinite(n) && n > 0);
  return parsed.length > 0 ? parsed : def;
}

// Tag rows written by perf submit tests:
//   DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%';
export const RUN_ID = process.env.PERF_RUN_ID ?? `run-${Math.floor(performance.now())}`;
export const PERFTEST_PREFIX = 'PERFTEST::';

// Tag rows written by browser E2E submit tests:
//   DELETE FROM submissions WHERE query_text LIKE 'FUNCTEST::%';
export const FUNCTEST_PREFIX = 'FUNCTEST::';
export const FUNCTEST_RUN_ID = process.env.FUNCTEST_RUN_ID ?? `e2e-${Math.floor(performance.now())}`;

export function fireHealth(ctx: APIRequestContext): Promise<APIResponse> {
  return ctx.get('/api/health');
}

export function fireVerify(ctx: APIRequestContext, query: string): Promise<APIResponse> {
  return ctx.post('/api/verify', { data: { query } });
}

export function fireSubmit(ctx: APIRequestContext, seq: number): Promise<APIResponse> {
  return ctx.post('/api/submit', {
    data: {
      query: `${PERFTEST_PREFIX}${RUN_ID}::${seq}`,
      uuid: null,
      address: `${100 + (seq % 9000)} PERFTEST Avenue`,
      unit: null,
      city: 'Chicago',
      county: 'Cook',
      state: 'IL',
      zip: '60601',
      latitude: 41.8781,
      longitude: -87.6298,
      score: 0.99,
    },
  });
}

export function fireFunctestSubmit(ctx: APIRequestContext, query: string, match: {
  address: string;
  city?: string | null;
  county?: string | null;
  state?: string | null;
  zip?: string | null;
  unit?: string | null;
  uuid?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  score: number;
}): Promise<APIResponse> {
  return ctx.post('/api/submit', {
    data: {
      query: `${FUNCTEST_PREFIX}${FUNCTEST_RUN_ID}::${query}`,
      uuid: match.uuid ?? null,
      address: match.address,
      unit: match.unit ?? null,
      city: match.city ?? null,
      county: match.county ?? null,
      state: match.state ?? null,
      zip: match.zip ?? null,
      latitude: match.latitude ?? null,
      longitude: match.longitude ?? null,
      score: match.score,
    },
  });
}

export function fireStats(ctx: APIRequestContext): Promise<APIResponse> {
  return ctx.get('/api/stats');
}

/** Deterministic PRNG so mixed-workload runs are reproducible. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
