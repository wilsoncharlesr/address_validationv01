// Latency/throughput accounting shared by every perf spec.

export interface Shot {
  ok: boolean;      // 2xx
  status: number;   // 0 = transport error (conn refused/reset/timeout)
  ms: number;
}

export interface LoadReport {
  label: string;
  count: number;
  rps: number;          // achieved requests/sec over the measured window
  errorRate: number;    // non-2xx fraction, 0..1
  mean: number;
  min: number;
  p50: number;
  p90: number;
  p95: number;
  p99: number;
  max: number;
  statusCounts: Record<string, number>;
}

/** Nearest-rank percentile over an ascending-sorted array. */
export function percentile(sortedMs: number[], q: number): number {
  if (sortedMs.length === 0) return 0;
  const idx = Math.min(sortedMs.length - 1, Math.max(0, Math.ceil(q * sortedMs.length) - 1));
  return sortedMs[idx];
}

export function summarize(label: string, shots: Shot[], elapsedMs: number): LoadReport {
  const sorted = shots.map(s => s.ms).sort((a, b) => a - b);
  const errors = shots.filter(s => !s.ok).length;
  const statusCounts: Record<string, number> = {};
  for (const s of shots) {
    const key = s.status === 0 ? 'transport-error' : String(s.status);
    statusCounts[key] = (statusCounts[key] ?? 0) + 1;
  }
  const sum = sorted.reduce((a, b) => a + b, 0);
  return {
    label,
    count: shots.length,
    rps: elapsedMs > 0 ? (shots.length / elapsedMs) * 1000 : 0,
    errorRate: shots.length > 0 ? errors / shots.length : 0,
    mean: shots.length > 0 ? sum / shots.length : 0,
    min: sorted[0] ?? 0,
    p50: percentile(sorted, 0.50),
    p90: percentile(sorted, 0.90),
    p95: percentile(sorted, 0.95),
    p99: percentile(sorted, 0.99),
    max: sorted[sorted.length - 1] ?? 0,
    statusCounts,
  };
}

export function formatReport(r: LoadReport): string {
  const f = (n: number) => n.toFixed(1).padStart(8);
  return (
    `${r.label.padEnd(28)} n=${String(r.count).padStart(6)}  rps=${r.rps.toFixed(1).padStart(8)}  ` +
    `err=${(r.errorRate * 100).toFixed(2).padStart(6)}%  ` +
    `p50=${f(r.p50)}ms  p95=${f(r.p95)}ms  p99=${f(r.p99)}ms  max=${f(r.max)}ms  ` +
    `status=${JSON.stringify(r.statusCounts)}`
  );
}
