# Playwright Test Suite — Address Verification

Playwright tests for the address-verification stack: **API performance** (direct
`:8081`) and **browser E2E** (nginx `:8088`).

## Projects

| Project | Target | What it tests |
|---------|--------|---------------|
| `api-perf` | `http://localhost:8081` | Latency, throughput, soak, submit/stats cost |
| `ui-e2e` | `http://localhost:8088` | Verify flow, search accuracy, errors, stats UI, perceived latency |

`globalSetup` checks `/api/health` on both URLs before any spec runs.

## API performance specs (`tests/api/`)

| Spec | What it measures |
|------|------------------|
| `01-health.spec.ts` | HTTP stack baseline (no DB) |
| `02-verify-latency.spec.ts` | Per-path verify latency: ZIP, locality, street-first, fusion, bad-ZIP |
| `03-verify-throughput.spec.ts` | Closed-loop concurrency ramp |
| `04-submit-perf.spec.ts` | Write path (INSERT into nad_sub) |
| `05-stats-perf.spec.ts` | Stats aggregates + verify interference |
| `06-mixed-soak.spec.ts` | Open-loop mixed workload soak |

Search paths match `AddressRepository.SearchAsync`: ZIP, locality, street+number,
fusion (ambiguous `NUMBER WORD`), and bad-ZIP fallthrough. The old full-table KNN
path is no longer tested.

## Browser E2E specs (`tests/e2e/`)

| Spec | What it covers |
|------|----------------|
| `10-verify-flow.spec.ts` | Search → select → submit happy path |
| `11-search-accuracy.spec.ts` | Golden queries from `fixtures/expected-matches.json` |
| `12-error-states.spec.ts` | 422 broad query, disabled submit, Enter key |
| `13-stats-page.spec.ts` | Stats page load + refresh |
| `14-ui-latency.spec.ts` | Perceived search/submit timing through nginx |

## Setup

```bash
python3 app/start.py          # stack must be running
cd tests/perf
npm install
npx playwright install chromium
```

Optional: build street indexes on the active table:

```bash
python3 tools/load_all_addresses.py --index-only --table nad_addresses
```

Without street indexes, `globalSetup` skips street/locality/fusion latency tests
and uses a ZIP-heavy load mix for throughput/soak. Set `USE_FULL_PATH_MIX=1`
after indexes are built to exercise all search paths under load.

## Run

```bash
npm test                 # both projects (api-perf then ui-e2e)
npm run test:api         # API performance only
npm run test:e2e         # browser functional + UI latency
npm run test:latency     # verify latency by path
npm run test:throughput  # concurrency ramp
npm run test:soak        # mixed workload soak
npm run test:cleanup     # delete PERFTEST:: and FUNCTEST:: rows
npm run report           # open HTML report
```

Through nginx for API perf (optional):

```bash
API_BASE_URL=http://localhost:8088 npm run test:api
```

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `API_BASE_URL` | `http://localhost:8081` | API perf target |
| `WEB_BASE_URL` | `http://localhost:8088` | Browser E2E target |
| `VERIFY_LATENCY_N` | `30` | Samples per path in spec 02 |
| `VERIFY_ZIP_P95_MS` | `200` | ZIP path p95 budget |
| `VERIFY_LOCALITY_P95_MS` | `800` | Locality path p95 budget |
| `VERIFY_STREET_P95_MS` | `500` | Street-first path p95 budget |
| `VERIFY_FUSION_P95_MS` | `800` | Fusion path p95 budget |
| `VERIFY_BADZIP_P95_MS` | `1200` | Bad-ZIP fallthrough p95 budget |
| `USE_FULL_PATH_MIX` | unset | Set to `1` for throughput/soak to include street/fusion queries |
| `PG_CONTAINER` | `address-verification-pg` | Container name for index detection in globalSetup |
| `UI_LATENCY_N` | `10` | UI latency samples |
| `UI_SEARCH_P95_MS` | `2000` | Search → results visible p95 |
| `UI_SUBMIT_P95_MS` | `500` | Submit → success banner p95 |
| `CONCURRENCY_STEPS` | `5,10,25,50` | Throughput ramp steps |
| `TARGET_RPS` / `SOAK_S` | `100` / `30` | Soak arrival rate / duration |
| `PERF_SEED` | `42` | PRNG seed for mixed workload |

## Accuracy fixtures

Edit [`fixtures/expected-matches.json`](fixtures/expected-matches.json) to add
regression cases. Each entry supports:

- `query` — search string
- `addressContains` — substring in top result address
- `cityContains` / `state` — location checks
- `minScore` — minimum match score (0..1)

## Cleanup after submit tests

Perf and E2E submit tests tag rows for easy removal:

```bash
npm run test:cleanup
# or manually:
docker exec -it address-verification-pg psql -U postgres -d nad_sub \
  -c "DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%' OR query_text LIKE 'FUNCTEST::%';"
```

## 10K req/s target

Playwright tops out around 1–2K req/s per process. Use this suite for latency
SLOs, regression detection, and finding the single-instance saturation knee.
For true 10K req/s load generation, use [`k6/verify-10k.js`](k6/verify-10k.js).
