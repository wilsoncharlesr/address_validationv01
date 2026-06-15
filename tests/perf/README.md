# Performance test suite — AddressVerification API

Playwright-based performance tests for the C# minimal API in `app/api/`.

## What each spec measures

| Spec | What it tells you |
|---|---|
| `tests/01-health.spec.ts` | HTTP-stack baseline (no DB). If this is slow, nothing else matters. |
| `tests/02-verify-latency.spec.ts` | Single-user latency per code path: ZIP fast path, full trigram KNN, and the bad-ZIP double-query fallthrough. These numbers drive all capacity math. |
| `tests/03-verify-throughput.spec.ts` | Closed-loop concurrency ramp (5→50 workers). Finds the knee of the curve and extrapolates instances needed for the 10K req/s target. |
| `tests/04-submit-perf.spec.ts` | Write path (INSERT into nad_sub). **Writes tagged rows — see cleanup below.** |
| `tests/05-stats-perf.spec.ts` | Cost of the uncached full-table aggregates, and whether stats traffic degrades verify latency (it will, until stats is cached). |
| `tests/06-mixed-soak.spec.ts` | Open-loop constant-arrival-rate soak with a 90/8/2 verify/submit/stats mix. Saturation shows up as shed requests, not silently lower throughput. |

## Setup

```bash
cd tests/perf
npm install
npx playwright install   # installs the bundled browser deps (not used, but keeps PW happy)
```

The stack must be running (`python3 app/start.py` or terraform). By default
tests hit the API container directly at `http://localhost:8081`.

## Run

```bash
npx playwright test                    # full suite, sequential (~4 min with defaults)
npx playwright test tests/03-*        # just the throughput ramp
API_BASE_URL=http://localhost:8088 npx playwright test   # through nginx instead
npx playwright show-report             # HTML report; JSON attachments per test
```

## Knobs (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `API_BASE_URL` | `http://localhost:8081` | Target base URL |
| `VERIFY_LATENCY_N` | `30` | Samples per code path in spec 02 |
| `VERIFY_ZIP_P95_MS` / `VERIFY_KNN_P95_MS` / `VERIFY_BADZIP_P95_MS` | `200` / `2000` / `2000` | p95 budgets per miss path (defaults match measured dev-laptop reality: KNN misses cost ~1.2s of DB CPU) |
| `VERIFY_CACHE_HIT_P95_MS` | `50` | p95 budget for cached repeats |
| `UNIQUE_QUERIES` | unset | `1` makes spec 03 fire all-miss traffic (DB-bound throughput) |
| `CONCURRENCY_STEPS` | `5,10,25,50` | Closed-loop ramp steps |
| `STEP_DURATION_S` | `10` | Seconds per ramp step |
| `ERROR_RATE_MAX` | `0.01` (`0.02` soak) | Max tolerated non-2xx fraction |
| `TARGET_TOTAL_RPS` | `10000` | Fleet-level target used for extrapolation |
| `SUBMIT_WORKERS` / `SUBMIT_DURATION_S` / `SUBMIT_P95_MS` | `10` / `10` / `200` | Write-path load |
| `STATS_N` / `STATS_P95_MS` / `STATS_INTERFERENCE_FACTOR` | `5` / `5000` / `3` | Stats cost + allowed verify degradation |
| `TARGET_RPS` / `SOAK_S` / `MIN_ACHIEVED_RATIO` | `100` / `30` / `0.95` | Soak arrival rate / duration / completion floor |
| `PERF_SEED` | `42` | PRNG seed for the reproducible workload mix |

## Cleanup after submit/soak tests

Specs 04 and 06 insert real rows into `nad_sub.submissions`, tagged so they
are easy to remove:

```bash
docker exec -it <db-container> psql -U postgres -d nad_sub \
  -c "DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%'"
```

## About the 10K req/s target — read this before trusting any number

1. **One Node/Playwright process cannot generate 10K req/s.** Playwright's
   `APIRequestContext` is built for functional API testing; a single process
   tops out around 1–2K req/s even against a no-op endpoint. This suite is for
   *latency SLOs, regression detection, and finding the saturation knee of one
   instance*. The spec-03 attachment extrapolates from single-instance
   capacity to the fleet size needed for 10K req/s.
2. **For a true 10K req/s test, use a purpose-built open-loop generator** run
   from one or more machines that are not the machine under test.
   `k6/verify-10k.js` in this directory is ready to run:
   ```bash
   k6 run k6/verify-10k.js                          # 10K req/s for 2 minutes
   k6 run -e RATE=2000 -e DURATION=5m k6/verify-10k.js
   ```
3. **The database is the real constraint, not Kestrel.** Capacity math:
   at ~20 ms of Postgres CPU per trigram search, 10 000 req/s × 0.02 s =
   200 CPU-seconds per second — i.e. ~200 Postgres cores — unless most
   requests are served from a cache. Measure spec 02's per-path latency,
   multiply, and size the cache/replica strategy accordingly.
