// True 10K req/s open-loop load test for POST /api/verify.
// Playwright cannot generate this volume from one process; k6 can (on decent
// hardware — run it from a machine that is NOT hosting the API/DB).
//
//   k6 run k6/verify-10k.js
//   k6 run -e BASE_URL=http://10.0.0.5:8081 -e RATE=10000 -e DURATION=2m k6/verify-10k.js
//
// Ramp up first (RATE=500, 1000, 2000, ...) to find the sustainable rate
// before attempting the full 10K.

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8081';
const RATE = parseInt(__ENV.RATE || '10000', 10);
const DURATION = __ENV.DURATION || '2m';

const QUERIES = [
  '1916 lombard ave berwyn il 60402',
  '233 s wacker dr chicago il 60606',
  '100 n western ave chicago il 60612',
  '500 e monroe st springfield il 62701',
  '1401 w green st urbana il 61801',
  '4800 n broadway chicago il 60640',
  '1916 lombard avenue berwyn illinois', // no ZIP -> full KNN path
  '233 south wacker drive chicago',
];

export const options = {
  scenarios: {
    verify: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.min(RATE, 2000),
      maxVUs: Math.min(RATE * 2, 10000),
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<300', 'p(99)<1000'],
    http_req_failed: ['rate<0.01'],
    dropped_iterations: ['count<100'], // schedule kept up = the target rate was actually offered
  },
};

export default function () {
  const query = QUERIES[Math.floor(Math.random() * QUERIES.length)];
  const res = http.post(`${BASE_URL}/api/verify`, JSON.stringify({ query }), {
    headers: { 'Content-Type': 'application/json' },
  });
  check(res, {
    'status 200': r => r.status === 200,
    'has matches': r => {
      try { return Array.isArray(r.json()); } catch { return false; }
    },
  });
}
