// Open-loop soak at a constant arrival rate with a production-like mix:
//   90% verify (40% zip / 30% locality / 20% street / 10% fusion+bad-zip),
//   8% submit, 2% stats.

import { test, expect, APIRequestContext, APIResponse } from '@playwright/test';
import { pacedLoop } from '../../helpers/loadgen';
import { formatReport } from '../../helpers/metrics';
import { BASE_URL, envInt, envFloat, fireVerify, fireSubmit, fireStats, mulberry32 } from '../../helpers/api';
import { pickWeightedVerifyQuery, pickFullPathVerifyQuery } from '../../helpers/queries';

const pickLoadQuery = process.env.USE_FULL_PATH_MIX === '1'
  ? pickFullPathVerifyQuery
  : pickWeightedVerifyQuery;

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
      if (roll < 0.90) return fireVerify(ctx, pickLoadQuery(seq));
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
      `only ${(r.achievedRatio * 100).toFixed(1)}% of the scheduled ${TARGET_RPS} req/s completed`,
    ).toBeGreaterThanOrEqual(MIN_ACHIEVED);
    expect(r.errorRate, `error rate ${(r.errorRate * 100).toFixed(2)}% under mixed load`).toBeLessThanOrEqual(ERROR_RATE_MAX);

    console.log('NOTE: submit traffic inserted tagged rows — clean with: ' +
      "DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%'");
  });
});
