// Closed-loop concurrency ramp on POST /api/verify: fixed pools of virtual
// users firing back-to-back, stepping up until throughput stops scaling.
//
// Two regimes, chosen by env:
//   default          — repeated corpus, mostly served from the API's verify
//                      cache. Measures the HTTP+cache ceiling. Expect this to
//                      saturate the LOAD GENERATOR (one Node process tops out
//                      around 1-2K rps), not the server.
//   UNIQUE_QUERIES=1 — every request is a distinct query (cache miss).
//                      Measures the real database-bound capacity.
//
// A saturated single-process closed-loop generator shows the same signature
// as a saturated server (flat RPS, climbing latency), so flat throughput is
// reported as a diagnosis, not a failure. Error-rate gates per step still
// fail hard. For authoritative numbers above ~1K rps use k6/verify-10k.js.

import { test, expect } from '@playwright/test';
import { closedLoop } from '../helpers/loadgen';
import { formatReport, LoadReport } from '../helpers/metrics';
import { BASE_URL, envInt, envIntList, envFloat, fireVerify } from '../helpers/api';
import { ALL_VERIFY_QUERIES, pick, uniqueQuery } from '../helpers/queries';

const STEPS = envIntList('CONCURRENCY_STEPS', [5, 10, 25, 50]);
const STEP_DURATION_S = envInt('STEP_DURATION_S', 10);
const ERROR_RATE_MAX = envFloat('ERROR_RATE_MAX', 0.01);
const TARGET_TOTAL_RPS = envInt('TARGET_TOTAL_RPS', 10_000);
const UNIQUE = process.env.UNIQUE_QUERIES === '1';
const SEQ_BASE = (Date.now() % 9000) * 100_000;

test.describe('verify throughput ramp', () => {
  test(`concurrency steps ${STEPS.join(', ')} @ ${STEP_DURATION_S}s each${UNIQUE ? ' (unique queries)' : ''}`, async ({}, testInfo) => {
    const reports: LoadReport[] = [];

    for (const workers of STEPS) {
      const r = await closedLoop({
        label: `verify @ ${workers} workers${UNIQUE ? ' (miss)' : ''}`,
        baseURL: BASE_URL,
        workers,
        durationMs: STEP_DURATION_S * 1000,
        fire: (ctx, seq) =>
          fireVerify(ctx, UNIQUE
            ? uniqueQuery(ALL_VERIFY_QUERIES, SEQ_BASE + seq)
            : pick(ALL_VERIFY_QUERIES, seq)),
      });
      reports.push(r);
      console.log(formatReport(r));

      expect(
        r.errorRate,
        `error rate ${(r.errorRate * 100).toFixed(2)}% at ${workers} workers exceeds ` +
          `${(ERROR_RATE_MAX * 100).toFixed(2)}% — look for Npgsql pool exhaustion ` +
          'or command timeouts in the API logs',
      ).toBeLessThanOrEqual(ERROR_RATE_MAX);
    }

    const best = reports.reduce((a, b) => (b.rps > a.rps ? b : a));
    const improved = reports.length > 1 && best.rps > reports[0].rps * 1.05;
    const verdict = improved
      ? 'throughput scaled with concurrency'
      : 'flat/declining RPS across steps: the single-process load generator is the ' +
        'likely limiter at this rate (its queuing also inflates the per-step latency ' +
        'numbers) — use k6/verify-10k.js from a separate machine for authoritative throughput';
    console.log(`best=${best.rps.toFixed(1)} rps (${best.label}); ${verdict}`);
    console.log(`~${Math.ceil(TARGET_TOTAL_RPS / Math.max(best.rps, 1))} instance(s) of this ` +
      `stack needed for ${TARGET_TOTAL_RPS} req/s (lower bound — see verdict above)`);

    await testInfo.attach('throughput-ramp.json', {
      body: JSON.stringify({
        uniqueQueries: UNIQUE,
        steps: reports,
        bestRps: best.rps,
        bestAt: best.label,
        improvedWithConcurrency: improved,
        verdict,
        target: TARGET_TOTAL_RPS,
        estimatedInstancesForTarget: Math.ceil(TARGET_TOTAL_RPS / Math.max(best.rps, 1)),
      }, null, 2),
      contentType: 'application/json',
    });
  });
});
