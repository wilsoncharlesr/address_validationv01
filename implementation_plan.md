# Implementation Plan — Performance Fixes for 10K req/s

Executes the findings in [performance_tune.md](performance_tune.md). Phases are
ordered so each one is independently shippable, verified by the suite in
[tests/perf/](tests/perf/README.md), and safe to roll back by reverting a
single commit.

**Files touched across all phases:**
`app/api/Program.cs`, `app/api/AddressRepository.cs`, `app/api/Models.cs`,
`app/web/nginx.conf`, `app/terraform/main.tf` (env only).
No database schema changes until Phase 7.

---

## Phase 0 — Baseline (do first, ~15 min)

No code changes. Numbers from this phase are the yardstick for every later
phase.

1. Start the stack (`python3 app/start.py` with Docker running).
2. Record baseline:
   ```bash
   cd tests/perf
   npx playwright test          # save the HTML report + JSON attachments
   ```
3. Commit the JSON attachments (or copy them) as `tests/perf/baselines/phase0/`.

**Expected today:** spec 05's interference test fails (stats traffic degrades
verify >3×) — that is the bug, not the test. Note the spec 03 best-RPS number;
it is the single-instance capacity before tuning.

---

## Phase 1 — Npgsql pool & prepare tuning (S, ~1 hour)

**Finding 1. File: `app/api/Program.cs:7-14`.**

Apply pool settings in code with `NpgsqlConnectionStringBuilder` so they hold
regardless of what the `NAD_CONNECTION` / `NADSUB_CONNECTION` env vars contain
(env-supplied values still win for host/db/credentials):

```csharp
static NpgsqlDataSource BuildDataSource(string connString)
{
    var csb = new NpgsqlConnectionStringBuilder(connString)
    {
        MaxPoolSize = 200,
        MinPoolSize = 20,
        MaxAutoPrepare = 10,
        AutoPrepareMinUsages = 2,
        Timeout = 5,            // seconds to acquire a pooled connection
        CommandTimeout = 5,     // seconds per query — fail fast under overload
        NoResetOnClose = true,
    };
    return new NpgsqlDataSourceBuilder(csb.ConnectionString).Build();
}

var nadDataSource    = BuildDataSource(nadConn);
var nadSubDataSource = BuildDataSource(nadSubConn);
```

Also set thread-pool floor for burst absorption (top of `Program.cs`):

```csharp
ThreadPool.SetMinThreads(workerThreads: 200, completionPortThreads: 200);
```

**Postgres side (no schema change):** ensure `max_connections` in the DB
container comfortably exceeds `2 × MaxPoolSize` (two data sources). Default
100 is too low → set `max_connections=500` in the db Dockerfile/start_db.py
command args.

**Verify:** spec 03 at `CONCURRENCY_STEPS=50,100,200` shows zero
transport-errors/timeouts; compare best RPS vs Phase 0.
**Rollback:** revert commit; settings are additive, no data impact.
**Deliberately deferred:** `Multiplexing=true` — measure it in Phase 7, it
changes failure semantics and deserves its own A/B.

---

## Phase 2 — Stats: cache + parallelize (S, ~1–2 hours)

**Finding 4. Files: `app/api/AddressRepository.cs:138-143`, `app/api/Program.cs:47`.**

2a. Run both databases concurrently in `StatsAsync`:

```csharp
public async Task<StatsResponse> StatsAsync(CancellationToken ct = default)
{
    var nadTask    = DbStatsAsync(_nad, _table, ct);
    var nadSubTask = DbStatsAsync(_nadSub, "submissions", ct);
    await Task.WhenAll(nadTask, nadSubTask);
    return new StatsResponse(await nadTask, await nadSubTask);
}
```

2b. Cache with a 30 s TTL and single-flight (one concurrent refresh; a
stampede of cold-cache callers must not launch N aggregate scans):

```csharp
builder.Services.AddMemoryCache();

app.MapGet("/api/stats", async (AddressRepository repo, IMemoryCache cache, CancellationToken ct) =>
{
    var stats = await cache.GetOrCreateAsync("stats", async entry =>
    {
        entry.AbsoluteExpirationRelativeToNow = TimeSpan.FromSeconds(30);
        return await repo.StatsAsync(ct);
    });
    return Results.Ok(stats);
});
```

(`GetOrCreateAsync` on `IMemoryCache` does not strictly single-flight; if the
stampede matters, guard with a `SemaphoreSlim(1,1)` around the miss path —
include this, it is five lines.)

**Verify:** spec 05 — sequential stats p95 collapses to ~1 cached call per
30 s window; the interference test ("stats traffic must not wreck verify
latency") flips from fail to pass.
**Rollback:** revert; worst case is stale-by-30s stats, which the UI tolerates.

---

## Phase 3 — Cancellation propagation (S, ~1 hour)

**Finding 3. Files: `app/api/AddressRepository.cs` (all public methods), `app/api/Program.cs` (all endpoints).**

- Add `CancellationToken ct = default` to `SearchAsync`, `SubmitAsync`,
  `StatsAsync`, `DbStatsAsync`, `BucketsAsync`, `ReadResultsAsync`.
- Flow it into every `OpenConnectionAsync(ct)`, `ExecuteReaderAsync(ct)`,
  `ReadAsync(ct)`, `ExecuteScalarAsync(ct)`.
- Endpoints: add a `CancellationToken ct` parameter (minimal APIs bind it from
  `HttpContext.RequestAborted` automatically) and pass it through.
- Npgsql translates token cancellation into a Postgres `CANCEL` request, so
  abandoned queries stop consuming DB CPU.

**Verify:** functional — all specs still green. Behavioral —
`curl -m 0.05 -X POST .../api/verify ...` then check
`SELECT count(*) FROM pg_stat_activity WHERE state='active'` settles to ~0;
API log shows `OperationCanceledException` (expected, not an error — swallow it
in the endpoint or via an exception handler returning 499-style no-op).
**Rollback:** revert; tokens are additive.

---

## Phase 4 — nginx upstream keepalive (S, ~30 min)

**Finding 5. File: `app/web/nginx.conf`.**

```nginx
upstream api_backend {
    server api:8080;
    keepalive 256;
}

server {
    listen 80;
    ...
    location /api/ {
        proxy_pass http://api_backend/api/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        # keep existing Host / X-Real-IP / X-Forwarded-* lines
        proxy_read_timeout 60s;
    }
}
```

**Verify:** `API_BASE_URL=http://localhost:8088 npx playwright test tests/03-*`
— compare vs the same run on 8081 (direct). Through-proxy RPS should now be
within a few percent of direct. On the host:
`docker exec <web> sh -c "ss -tan | grep -c TIME-WAIT"` stays flat under load.
**Rollback:** revert nginx.conf, `docker restart <web>`.

---

## Phase 5 — Verify-result cache (M, ~half day) — the 10K req/s enabler

**Capacity-math fix. Files: `app/api/Program.cs`, new `app/api/CachedSearch.cs` (or inline).**

NAD reference data is read-only between bulk reloads, so identical queries
always produce identical results. Cache at the repository boundary:

- **Key:** normalized query — `lower(query.Trim())` with internal whitespace
  collapsed (`Regex.Replace(q, @"\s+", " ")`). Must match what `SearchAsync`
  actually receives so hit rate is honest.
- **Store:** `IMemoryCache` with `SizeLimit` (e.g. 100_000 entries, each entry
  `Size = 1`), TTL 1 hour sliding. A top-3 result list is ~600 bytes → worst
  case ~60 MB, fine for the container.
- **Negative caching:** cache empty results too (bad queries repeat as well),
  shorter TTL (5 min).
- **Invalidation:** NAD reloads happen via out-of-band bulk loads + app
  restart, which clears the in-memory cache automatically. Document this in
  the loader README. If reloads ever become online, bump a cache "generation"
  prefix instead.
- **Observability:** count hits/misses with two `Interlocked` longs; expose on
  `/api/health` (`cacheHits`, `cacheMisses`). Capacity planning needs the
  real-traffic hit rate.

```csharp
app.MapPost("/api/verify", async (VerifyRequest req, AddressRepository repo,
    IMemoryCache cache, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(req.Query))
        return Results.BadRequest(new { error = "query is required" });

    var key = "v:" + Regex.Replace(req.Query.Trim().ToLowerInvariant(), @"\s+", " ");
    var matches = await cache.GetOrCreateAsync(key, async entry =>
    {
        var results = await repo.SearchAsync(req.Query.Trim(), 3, ct);
        entry.Size = 1;
        entry.AbsoluteExpirationRelativeToNow =
            results.Count > 0 ? TimeSpan.FromHours(1) : TimeSpan.FromMinutes(5);
        return results;
    });
    return Results.Ok(matches);
});
```

**Scale-out note:** in-process cache is per-instance. That is correct for this
phase — N instances each warm their own cache. Move to Redis only if instance
count grows large enough that per-instance warm-up hurts (Phase 7 decision).

**Verify:** spec 03 rerun — the 25-query corpus becomes ~100% cache hits after
warm-up, so best-RPS should jump to multiple thousands (now bounded by the load
generator, not the DB). To measure the *miss* path honestly, run spec 02 with a
restart between runs, or add `?nocache` only if genuinely needed (avoid
shipping test backdoors). `pg_stat_activity` during spec 03 should be near
idle after warm-up.
**Rollback:** revert; endpoint returns to direct repo call.

---## Phase 6 — JSON source-gen + micro-optimizations (S, ~2 hours)

**Finding 6. Files: `app/api/Program.cs`, `app/api/Models.cs`, `app/api/AddressRepository.cs`.**

- Source-generated serialization:

```csharp
[JsonSerializable(typeof(List<AddressResult>))]
[JsonSerializable(typeof(StatsResponse))]
[JsonSerializable(typeof(VerifyRequest))]
[JsonSerializable(typeof(SubmitRequest))]
internal partial class AppJsonContext : JsonSerializerContext { }

builder.Services.ConfigureHttpJsonOptions(o =>
    o.SerializerOptions.TypeInfoResolverChain.Insert(0, AppJsonContext.Default));
```

  (The anonymous objects in `/api/health`, `/api/submit`, and error responses
  must become small records so they serialize through the context.)
- `AddressRepository.cs:103`: `Convert.ToDouble(r.GetValue(10))` →
  `r.GetFloat(10)` (similarity() returns `real`).
- Replace `AddWithValue` with typed parameters
  (`cmd.Parameters.Add(new NpgsqlParameter<string>("q", query))` etc.).
- Gate CORS to development only (`if (app.Environment.IsDevelopment())`);
  nginx makes production same-origin.
- Optional: `[GeneratedRegex]` for `ZipPattern` and the whitespace-collapse
  regex.

**Verify:** `dotnet build -c Release` clean; full suite green; response bodies
byte-identical for a sample of each endpoint (field casing can silently change
when switching resolvers — diff them).
**Rollback:** revert.

---

## Phase 7 — Scale-out (L, conditional — only if needed after Phase 5)

Decision gate: after Phase 5 soaks under real traffic, check the
`/api/health` hit rate. If **miss volume × per-miss DB cost** still exceeds
~60% of one Postgres box at projected peak, proceed; otherwise stop here.

7a. **A/B `Multiplexing=true`** (connection string, one line): run spec 03 and
    the k6 ramp with it on and off; keep it only if it wins. Note it is
    incompatible with `NoResetOnClose` semantics concerns — read the Npgsql
    docs for the current caveat list before enabling.
7b. **Horizontal API instances:** terraform `count` on the api container +
    nginx `upstream` with multiple servers. Stateless API + per-instance cache
    means no coordination needed.
7c. **Postgres read replicas:** streaming replication in the db setup;
    connection string lists all hosts; `NpgsqlMultiHostDataSource` with
    `Target Session Attributes=prefer-standby` and `Load Balance Hosts=true`
    for `_nad` (reads). `_nadSub` (writes) stays pinned to the primary.
7d. **Optional ZIP-path single-round-trip:** merge the zip query and KNN
    fallback into one statement so bad ZIPs cost one round trip:
    zip-filtered subquery `UNION ALL` KNN subquery with an outer
    `ORDER BY score DESC LIMIT 3` — only worth it if Phase 5 metrics show
    bad-ZIP misses are material.

**Verify:** k6 from a separate machine: `k6 run -e RATE=2000 ...` stepping
2K→5K→10K; thresholds in `tests/perf/k6/verify-10k.js` (p95<300ms,
errors<1%, dropped<100) all green at 10K.

---

## Sequencing & effort summary

| Phase | Scope | Effort | Risk | Gate to next |
|---|---|---|---|---|
| 0 Baseline | run suite | 15 min | none | numbers recorded |
| 1 Pool tuning | Program.cs + db max_connections | 1 h | low | spec 03 @ 200 workers, 0 errors |
| 2 Stats cache | Program.cs, AddressRepository.cs | 1–2 h | low | spec 05 interference passes |
| 3 Cancellation | all endpoints/repo methods | 1 h | low | suite green + pg_stat_activity check |
| 4 nginx keepalive | nginx.conf | 30 min | low | proxy RPS ≈ direct RPS |
| 5 Verify cache | Program.cs (+helper) | ½ day | medium (staleness) | spec 03 RPS jump; hit-rate metric live |
| 6 JSON + micro | Models/Program/Repo | 2 h | low (response-shape diff) | byte-identical responses |
| 7 Scale-out | terraform, db, conn strings | days | medium | k6 @ 10K green |

Phases 1–4 are a single afternoon and remove every self-inflicted ceiling.
Phase 5 is the one that changes the capacity class of the system. Phase 7 is
infrastructure and only happens if real-traffic hit rates say it must.

One commit per phase, each ending with the full perf suite run and the JSON
attachments saved to `tests/perf/baselines/phase<N>/` so regressions between
phases are attributable.
