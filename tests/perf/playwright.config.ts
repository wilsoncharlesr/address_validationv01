import { defineConfig, devices } from '@playwright/test';

const API_BASE_URL = process.env.API_BASE_URL ?? 'http://localhost:8081';
const WEB_BASE_URL = process.env.WEB_BASE_URL ?? 'http://localhost:8088';

export default defineConfig({
  globalSetup: './globalSetup.ts',
  fullyParallel: false,
  timeout: 10 * 60 * 1000,
  expect: { timeout: 30_000 },
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['json', { outputFile: 'results/perf-results.json' }],
  ],
  projects: [
    {
      name: 'api-perf',
      testDir: './tests/api',
      workers: 1,
      use: {
        baseURL: API_BASE_URL,
      },
    },
    {
      name: 'ui-e2e',
      testDir: './tests/e2e',
      workers: 2,
      fullyParallel: true,
      use: {
        ...devices['Desktop Chrome'],
        baseURL: WEB_BASE_URL,
      },
    },
  ],
});
