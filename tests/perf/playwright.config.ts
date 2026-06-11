import { defineConfig } from '@playwright/test';

// All load generation happens *inside* each test (worker pools over
// APIRequestContext). Playwright's own parallelism must stay at 1 so two
// load tests never run at once and skew each other's numbers.
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 10 * 60 * 1000, // load steps run for tens of seconds each
  expect: { timeout: 30_000 },
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['json', { outputFile: 'results/perf-results.json' }],
  ],
  use: {
    // 8081 is the API container published directly on the host (terraform
    // api_port default). Point at 8088/api to measure through nginx instead.
    baseURL: process.env.API_BASE_URL ?? 'http://localhost:8081',
  },
});
