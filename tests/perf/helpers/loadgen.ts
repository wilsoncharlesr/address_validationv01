// Two load models over Playwright's APIRequestContext:
//
//  - closedLoop: N virtual users, each firing back-to-back. Concurrency is
//    fixed; throughput is whatever the server delivers. Good for finding the
//    knee of the latency/throughput curve.
//  - pacedLoop: open-loop constant arrival rate (like k6's
//    constant-arrival-rate). Requests launch on a fixed schedule regardless of
//    responses, so a saturated server shows up as climbing latency and shed
//    requests instead of silently lowered throughput.

import { request, APIRequestContext, APIResponse } from '@playwright/test';
import { Shot, LoadReport, summarize } from './metrics';

export type FireFn = (ctx: APIRequestContext, seq: number) => Promise<APIResponse>;

const sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));

async function record(shots: Shot[], fire: FireFn, ctx: APIRequestContext, seq: number, measureFrom: number) {
  const t0 = performance.now();
  let status = 0;
  try {
    const resp = await fire(ctx, seq);
    status = resp.status();
    await resp.body(); // drain so keep-alive connections are reusable
  } catch {
    status = 0;
  }
  const ms = performance.now() - t0;
  if (t0 >= measureFrom) {
    shots.push({ ok: status >= 200 && status < 300, status, ms });
  }
}

export interface ClosedLoopOptions {
  label: string;
  baseURL: string;
  workers: number;
  durationMs: number;
  warmupMs?: number; // shots started during warmup are excluded from the report
  fire: FireFn;
}

export async function closedLoop(opts: ClosedLoopOptions): Promise<LoadReport> {
  const { label, baseURL, workers, durationMs, warmupMs = 2000, fire } = opts;
  const contexts: APIRequestContext[] = [];
  for (let i = 0; i < workers; i++) {
    contexts.push(await request.newContext({ baseURL }));
  }

  const shots: Shot[] = [];
  let seq = 0;
  const start = performance.now();
  const measureFrom = start + warmupMs;
  const deadline = measureFrom + durationMs;

  try {
    await Promise.all(
      contexts.map(async ctx => {
        while (performance.now() < deadline) {
          await record(shots, fire, ctx, seq++, measureFrom);
        }
      }),
    );
  } finally {
    await Promise.all(contexts.map(c => c.dispose().catch(() => {})));
  }
  return summarize(label, shots, durationMs);
}

export interface PacedLoopOptions {
  label: string;
  baseURL: string;
  targetRps: number;
  durationMs: number;
  maxInFlight?: number; // shed (count, don't launch) beyond this to protect the load generator
  fire: FireFn;
}

export interface PacedReport extends LoadReport {
  offered: number;   // requests the schedule called for
  shed: number;      // skipped because maxInFlight was reached (server saturated)
  achievedRatio: number; // count / offered
}

export async function pacedLoop(opts: PacedLoopOptions): Promise<PacedReport> {
  const { label, baseURL, targetRps, durationMs, maxInFlight = 512, fire } = opts;
  const ctx = await request.newContext({ baseURL });
  const shots: Shot[] = [];
  const inFlight = new Set<Promise<void>>();
  const intervalMs = 1000 / targetRps;

  let offered = 0;
  let shed = 0;
  let seq = 0;
  const start = performance.now();
  const deadline = start + durationMs;
  let next = start;

  try {
    while (next < deadline) {
      const now = performance.now();
      if (now < next) await sleep(next - now);
      next += intervalMs;
      offered++;
      if (inFlight.size >= maxInFlight) {
        shed++;
        continue;
      }
      const p: Promise<void> = record(shots, fire, ctx, seq++, start).finally(() => {
        inFlight.delete(p);
      });
      inFlight.add(p);
    }
    await Promise.allSettled([...inFlight]);
  } finally {
    await ctx.dispose().catch(() => {});
  }

  const base = summarize(label, shots, durationMs);
  return { ...base, offered, shed, achievedRatio: offered > 0 ? base.count / offered : 0 };
}
