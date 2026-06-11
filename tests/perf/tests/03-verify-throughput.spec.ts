// Closed-loop concurrency ramp on POST /api/verify: fixed pools of virtual
// users firing back-to-back, stepping up until throughput stops scaling.
// The step where RPS flattens while p95 climbs is the capacity of ONE API
// instance + this Postgres box; the attachment extrapolates how many such
// instances 10K req/s would take (assuming the DB tier scales with them,
// which is the actual hard part — see the suite README).

import { test, expect } from '@playwright/test';
import { closedLoop } from '../helpers/loadgen';
import { formatReport, LoadReport } from '../helpers/metrics';
import { BASE_URL, envInt, envIntList, envFloat, fireVerify } from '../helpers/api';
import { ALL_VERIFY_QUERIES, pick } from '../helpers/queries';

const STEPS = envIntList('CONCURRENCY_STEPS', [5, 10, 25, 50]);
const STEP_DURATION_S = envInt('STEP_DURATION_S', 10);
const ERROR_RATE_MAX = envFloat('ERROR_RATE_MAX', 0.01);
const TARGET_TOTAL_RPS = envInt('TARGET_TOTAL_RPS', 10_000);

test.describe('verify throughput ramp', () => {
  test(`concurrency steps ${STEPS.join(', ')} @ ${STEP_DURATION_S}s each`, async ({}, testInfo) => {
    const reports: LoadReport[] = [];

    for (const workers of STEPS) {
      const r = await closedLoop({
        label: `verify @ ${workers} workers`,
        baseURL: BASE_URL,
        workers,
        durationMs: STEP_DURATION_S * 1000,
        fire: (ctx, seq) => fireVerify(ctx, pick(ALL_VERIFY_QUERIES, seq)),
      });
      reports.push(r);
      console.log(formatReport(r));

      expect(
        r.errorRate,
        `error rate ${(r.errorRate * 100).toFixed(2)}% at ${workers} workers exceeds ` +
          `${(ERROR_RATE_MAX * 100).toFixed(2)}% — look for Npgsql pool exhaustion ` +
          '(default Max Pool Size is 100) or command timeouts in the API logs',
      ).toBeLessThanOrEqual(ERROR_RATE_MAX);
    }

    const best = reports.reduce((a, b) => (b.rps > a.rps ? b : a));
    const instancesFor10k = Math.ceil(TARGET_TOTAL_RPS / Math.max(best.rps, 1));
    const summary = {
      steps: reports,
      bestRps: best.rps,
      bestAt: best.label,
      target: TARGET_TOTAL_RPS,
      estimatedInstancesForTarget: instancesFor10k,
      note:
        'Extrapolation assumes linear scaling of API instances AND a database tier ' +
        'that scales with them (caching / replicas). A single Postgres doing trigram ' +
        'KNN over 4.86M rows will saturate long before 10K req/s.',
    };
    console.log(
      `best=${best.rps.toFixed(1)} rps (${best.label}); ` +
        `~${instancesFor10k} instance(s) of this stack needed for ${TARGET_TOTAL_RPS} req/s`,
    );
    await testInfo.attach('throughput-ramp.json', {
      body: JSON.stringify(summary, null, 2),
      contentType: 'application/json',
    });

    // Sanity: throughput should grow from the first step to the best step.
    // If the first step is already the best, the server is saturated by
    // STEPS[0] concurrent users — a red flag worth failing on.
    if (reports.length > 1) {
      expect(
        best.rps,
        `throughput never improved beyond the smallest pool (${reports[0].label}); ` +
          'the service saturates at trivially low concurrency',
      ).toBeGreaterThan(reports[0].rps * 1.05);
    }
  });
});
