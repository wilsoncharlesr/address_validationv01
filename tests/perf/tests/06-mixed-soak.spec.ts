// Open-loop soak at a constant arrival rate with a production-like mix:
//   90% verify (70% zip-path / 20% knn / 10% bad-zip), 8% submit, 2% stats.
// Because arrivals are paced (not closed-loop), a saturated server cannot
// hide behind reduced offered load — it shows up as climbing latency, shed
// requests, and a low achievedRatio.
//
// Scale via env: TARGET_RPS=500 SOAK_S=60 npx playwright test tests/06-*
// (One Node process generates roughly 1-2K req/s at best; for a true
// 10K req/s test use a distributed generator — see README.)

import { test, expect, APIRequestContext, APIResponse } from '@playwright/test';
import { pacedLoop } from '../helpers/loadgen';
import { formatReport } from '../helpers/metrics';
import { BASE_URL, envInt, envFloat, fireVerify, fireSubmit, fireStats, mulberry32 } from '../helpers/api';
import { ZIP_QUERIES, KNN_QUERIES, BAD_ZIP_QUERIES, pick } from '../helpers/queries';

const TARGET_RPS = envInt('TARGET_RPS', 100);
const SOAK_S = envInt('SOAK_S', 30);
const ERROR_RATE_MAX = envFloat('ERROR_RATE_MAX', 0.02);
const MIN_ACHIEVED = envFloat('MIN_ACHIEVED_RATIO', 0.95);
const SEED = envInt('PERF_SEED', 42);

test.describe('mixed workload soak', () => {
  test(`${TARGET_RPS} req/s for ${SOAK_S}s (90/8/2 verify/submit/stats)`, async ({}, testInfo) => {
    const rand = mulberry32(SEED);

    const fire = (ctx: APIRequestContext, seq: number): Promise<APIResponse> => {
      const roll = rand();
      if (roll < 0.90) {
        const v = rand();
        if (v < 0.70) return fireVerify(ctx, pick(ZIP_QUERIES, seq));
        if (v < 0.90) return fireVerify(ctx, pick(KNN_QUERIES, seq));
        return fireVerify(ctx, pick(BAD_ZIP_QUERIES, seq));
      }
      if (roll < 0.98) return fireSubmit(ctx, seq);
      return fireStats(ctx);
    };

    const r = await pacedLoop({
      label: `mixed soak @ ${TARGET_RPS} rps`,
      baseURL: BASE_URL,
      targetRps: TARGET_RPS,
      durationMs: SOAK_S * 1000,
      fire,
    });

    console.log(formatReport(r));
    console.log(
      `offered=${r.offered} completed=${r.count} shed=${r.shed} ` +
        `achieved=${(r.achievedRatio * 100).toFixed(1)}% of schedule`,
    );
    await testInfo.attach('mixed-soak.json', { body: JSON.stringify(r, null, 2), contentType: 'application/json' });

    expect(
      r.achievedRatio,
      `only ${(r.achievedRatio * 100).toFixed(1)}% of the scheduled ${TARGET_RPS} req/s completed — ` +
        'either the server is saturated (check p99 and shed) or the load generator machine is; ' +
        'rerun with a lower TARGET_RPS to find the sustainable rate',
    ).toBeGreaterThanOrEqual(MIN_ACHIEVED);
    expect(r.errorRate, `error rate ${(r.errorRate * 100).toFixed(2)}% under mixed load`).toBeLessThanOrEqual(ERROR_RATE_MAX);

    console.log('NOTE: submit traffic inserted tagged rows — clean with: ' +
      "DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%'");
  });
});
