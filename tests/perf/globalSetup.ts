/**
 * Fail fast if the stack is not running before any spec executes.
 * Writes stack-state.json for worker processes (env vars do not propagate).
 */

import { execSync } from 'child_process';
import { writeStackState } from './helpers/stack-state';

const API_BASE_URL = process.env.API_BASE_URL ?? 'http://localhost:8081';
const WEB_BASE_URL = process.env.WEB_BASE_URL ?? 'http://localhost:8088';
const PG_CONTAINER = process.env.PG_CONTAINER ?? 'address-verification-pg';

async function checkHealth(label: string, url: string): Promise<{ table: string }> {
  try {
    const resp = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const body = await resp.json();
    if (body.status !== 'ok') {
      throw new Error(`unexpected body: ${JSON.stringify(body)}`);
    }
    console.log(`[globalSetup] ${label} ok (table=${body.table})`);
    return { table: body.table as string };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `[globalSetup] ${label} failed at ${url}: ${msg}\n` +
        'Start the stack with: python3 app/start.py',
    );
  }
}

function streetIndexExists(table: string): boolean {
  try {
    const out = execSync(
      `docker exec ${PG_CONTAINER} psql -U postgres -d nad -t -A -c ` +
        `"SELECT 1 FROM pg_indexes WHERE tablename='${table}' ` +
        `AND indexname='idx_${table}_hn_street' LIMIT 1"`,
      { encoding: 'utf8' },
    ).trim();
    return out === '1';
  } catch {
    return false;
  }
}

export default async function globalSetup(): Promise<void> {
  const api = await checkHealth('API', `${API_BASE_URL}/api/health`);
  await checkHealth('Web', `${WEB_BASE_URL}/api/health`);

  const indexed = streetIndexExists(api.table);
  writeStackState({ skipUnindexed: !indexed, table: api.table });

  if (!indexed) {
    console.warn(
      `[globalSetup] Street indexes missing on '${api.table}' — ` +
        'skipping street/locality/fusion latency tests. Build with:\n' +
        `  python3 tools/load_all_addresses.py --index-only --table ${api.table}`,
    );
  }
}
