# Performance Tuning — AddressVerification API (10K req/s target)

Performance review of the C# minimal API in `app/api/` against a target of
**10,000 API calls per second**. Companion load-test suite: [`tests/perf/`](tests/perf/README.md).

## Verdict

The C# code itself is fine for 10K req/s — ASP.NET Core minimal APIs handle that
volume easily. The system as currently configured will fall over roughly two
orders of magnitude short, because every request runs an **uncached trigram
search against a single Postgres instance**, through a connection pool capped
at 100. The fixes that matter are configuration and architecture, not rewrites.

## Capacity math (read this first)

**Measured** (dev laptop, dockerized Postgres, 4.86M rows, after all fixes
below — see `tests/perf` spec 02):

| Path | p50 | p95 |
|---|---|---|
| Cache hit | 2 ms | 4 ms |
| ZIP fast path, cache miss | 34 ms | 100 ms |
| Full trigram KNN, cache miss | **1,174 ms** | 1,522 ms |

The KNN miss cost is index-traversal CPU (raising `shared_buffers`
128MB→2GB did not move it). At ~1.2 s of DB CPU per uncached KNN search:

```
10,000 req/s × 1.2 s DB CPU = 12,000 Postgres cores  → impossible uncached
10,000 req/s × 0.034 s (zip path) = 340 cores        → still cluster-scale
10,000 req/s × 90% cache hit rate × 0.034 s = 34 cores of misses → feasible
```

No C# change fixes that. The two levers that do:

1. **Cache verify results.** The NAD table is read-only reference data —
   identical queries always return identical results. An in-memory LRU
   (`IMemoryCache`) or Redis layer keyed on the normalized query absorbs most
   real-world traffic (address lookups repeat heavily).
2. **Read replicas** for the cache-miss remainder. Npgsql's
   `NpgsqlMultiHostDataSource` load-balances across standbys with no
   application-code changes beyond the connection string.

---

## Findings, ranked by impact

### 1. Npgsql pool defaults will collapse under load

`app/api/Program.cs:13-14` builds both data sources with default settings:

- Default `Maximum Pool Size` is **100**. By Little's law, 10K req/s at even
  10 ms/query needs 100 concurrent connections at *perfect* efficiency. Any
  latency spike exhausts the pool; requests then queue up to 30 s before
  throwing `NpgsqlException`.
- No `Max Auto Prepare` — every query is re-parsed and re-planned by Postgres
  on every single request.
- Default 30 s timeouts mean the service stacks deep queues under overload
  instead of failing fast.

**Fix — connection string (both `NAD_CONNECTION` and `NADSUB_CONNECTION`):**

```
Host=...;Database=nad;Username=postgres;
Maximum Pool Size=200;Minimum Pool Size=20;
Max Auto Prepare=10;Auto Prepare Min Usages=2;
Timeout=5;Command Timeout=5;
No Reset On Close=true
```

Seriously evaluate **`Multiplexing=true`** as well: it interleaves many
commands over few physical connections and is Npgsql's single biggest
throughput lever for short queries. (Test it — it changes failure semantics
slightly and is incompatible with some session-state features.)

### 2. ZIP "fast path" computes similarity() for every row in the ZIP

`app/api/AddressRepository.cs:55-64` — the ZIP query:

```sql
SELECT ..., similarity(<full_expr>, lower(@q)) AS score
FROM il_addresses
WHERE zip_code = @zip
ORDER BY score DESC
LIMIT @lim
```

`ORDER BY score DESC` cannot use any index, so Postgres evaluates the trigram
similarity on the full concatenated expression for **all** rows in that ZIP
(thousands) on every request. The comment in the code claiming the score "is
only evaluated for the few rows that survive LIMIT" is true only for the KNN
path, not here.

Also, a query containing a 5-digit number that matches no `zip_code` costs
**two full round-trips** (ZIP query returns nothing → fall through to full KNN
at `AddressRepository.cs:68`).

Acceptable per request; expensive × 10K/s — another argument for the cache in
front of `SearchAsync`.

### 3. No cancellation propagation

`AddressRepository.SearchAsync` (`app/api/AddressRepository.cs:46`) takes no
`CancellationToken`, so when a client disconnects or times out, the Postgres
query keeps burning DB CPU on work nobody will read. Under overload with
client retries this is an amplification loop: dead queries slow the DB, which
causes more timeouts, which causes more retries.

**Fix:** minimal APIs bind `CancellationToken` automatically from
`HttpContext.RequestAborted`:

```csharp
app.MapPost("/api/verify", async (VerifyRequest req, AddressRepository repo, CancellationToken ct) =>
{
    ...
    var matches = await repo.SearchAsync(req.Query.Trim(), limit: 3, ct);
    ...
});
```

Flow `ct` through `OpenConnectionAsync(ct)`, `ExecuteReaderAsync(ct)`,
`ReadAsync(ct)`.

### 4. /api/stats is a denial-of-service button

`app/api/AddressRepository.cs:138-158` — every call runs `count(*)` over 4.86M
rows plus two GROUP BYs, on **both** databases, **sequentially**, with no
caching. A handful of stats requests per second starves all verify traffic
(test `tests/perf/tests/05-stats-perf.spec.ts` demonstrates this empirically).

**Fix:**
- Cache the `StatsResponse` with a 30–60 s TTL (`IMemoryCache`).
- Run the two databases concurrently:

```csharp
public async Task<StatsResponse> StatsAsync()
{
    var nadTask    = DbStatsAsync(_nad, _table);
    var nadSubTask = DbStatsAsync(_nadSub, "submissions");
    await Task.WhenAll(nadTask, nadSubTask);
    return new StatsResponse(nadTask.Result, nadSubTask.Result);
}
```

- Longer term: maintain a rollup table instead of aggregating 4.86M rows live.

### 5. nginx opens a new TCP connection to Kestrel per request

`app/web/nginx.conf:15-22` — `proxy_pass` defaults to HTTP/1.0 with
`Connection: close`. At 10K req/s that is 10K TCP handshakes per second and
eventual ephemeral-port exhaustion on the proxy.

**Fix:**

```nginx
upstream api_backend {
    server api:8080;
    keepalive 256;
}

server {
    ...
    location /api/ {
        proxy_pass http://api_backend/api/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        # existing X-Forwarded-* headers unchanged
    }
}
```

### 6. Smaller, free wins

| Where | Issue | Fix |
|---|---|---|
| `Program.cs` (JSON) | Reflection-based `System.Text.Json` serialization allocates more than needed at this volume | Source-generated `JsonSerializerContext` for `List<AddressResult>`, `StatsResponse`, etc., registered via `ConfigureHttpJsonOptions` |
| `AddressRepository.cs:103` | `Convert.ToDouble(r.GetValue(10))` boxes on every row | `r.GetFloat(10)` — `similarity()` returns Postgres `real` |
| `AddressRepository.cs` (all commands) | `AddWithValue` forces parameter type inference per call | Typed `NpgsqlParameter<T>` with explicit `NpgsqlDbType` |
| `Program.cs:20-21, 24` | `AllowAnyOrigin` CORS middleware runs per request | Unnecessary in production — nginx makes everything same-origin; gate it to development |
| Startup | Burst traffic hits thread-pool ramp-up | `ThreadPool.SetMinThreads` (or `DOTNET_ThreadPool_MinThreads`) sized to expected concurrency |

None of these move the needle like findings 1–2, but each is a one-line change.

---

## Recommended order of work

1. Connection-string tuning (finding 1) — minutes, biggest config win.
2. Stats caching + `Task.WhenAll` (finding 4) — removes the self-DoS.
3. Cancellation tokens (finding 3) — overload resilience.
4. nginx keepalive (finding 5) — required before any proxied load test.
5. Verify-result cache (capacity math) — the only path to 10K req/s on
   realistic hardware.
6. Read replicas / `NpgsqlMultiHostDataSource` — when cache-miss volume
   exceeds one Postgres box.
7. Free wins (finding 6) — fold into the next touch of each file.

## Measuring

```bash
cd tests/perf
npm install
npx playwright test          # latency SLOs, saturation knee, interference tests
k6 run k6/verify-10k.js      # true 10K req/s open-loop test (run from a separate machine)
```

- `tests/perf/tests/02-verify-latency.spec.ts` gives the per-path latency
  numbers that drive the capacity math above.
- `tests/perf/tests/03-verify-throughput.spec.ts` finds the saturation knee of
  one instance and extrapolates the fleet size for 10K req/s.
- `tests/perf/tests/05-stats-perf.spec.ts` fails today by design — it encodes
  finding 4.
- A single Playwright/Node process tops out around 1–2K req/s; use the k6
  script for the literal 10K test.
