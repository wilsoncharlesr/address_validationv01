using AddressVerification;
using Microsoft.Extensions.Caching.Memory;
using Npgsql;

// Burst absorption: pre-grow the thread pool so traffic spikes don't stall on
// the default one-thread-per-250ms injection rate.
ThreadPool.SetMinThreads(workerThreads: 200, completionPortThreads: 200);

var builder = WebApplication.CreateBuilder(args);

// --- Configuration (env vars, with localhost defaults for running outside Docker) ---
string nadConn = Environment.GetEnvironmentVariable("NAD_CONNECTION")
    ?? "Host=localhost;Port=5433;Database=nad;Username=postgres";
string nadSubConn = Environment.GetEnvironmentVariable("NADSUB_CONNECTION")
    ?? "Host=localhost;Port=5433;Database=nad_sub;Username=postgres";
string nadTable = Environment.GetEnvironmentVariable("NAD_TABLE") ?? "il_addresses";

// Pool/prepare settings applied in code so they hold no matter what the env
// vars contain; host/db/credentials from the env still win.
static NpgsqlDataSource BuildDataSource(string connString)
{
    var csb = new NpgsqlConnectionStringBuilder(connString)
    {
        MaxPoolSize = 200,
        MinPoolSize = 20,
        MaxAutoPrepare = 10,        // skip re-parse/re-plan for the hot queries
        AutoPrepareMinUsages = 2,
        Timeout = 5,                // seconds to acquire a pooled connection
        CommandTimeout = 5,         // fail fast under overload, don't queue 30s
        NoResetOnClose = true,      // skip DISCARD ALL on pooled-connection reuse
    };
    return new NpgsqlDataSourceBuilder(csb.ConnectionString).Build();
}

var nadDataSource = BuildDataSource(nadConn);
var nadSubDataSource = BuildDataSource(nadSubConn);

builder.Services.AddSingleton(nadDataSource);
builder.Services.AddSingleton(nadSubDataSource);
builder.Services.AddSingleton(new AddressRepository(nadDataSource, nadSubDataSource, nadTable));

builder.Services.AddCors(o => o.AddDefaultPolicy(p =>
    p.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod()));

builder.Services.ConfigureHttpJsonOptions(o =>
    o.SerializerOptions.TypeInfoResolverChain.Insert(0, AppJsonContext.Default));

// SizeLimit counts entries (every Set specifies Size = 1): ~100K cached
// top-3 result lists is roughly 60 MB worst case. NAD reference data only
// changes via bulk reload + restart, which clears this cache by definition.
builder.Services.AddMemoryCache(o => o.SizeLimit = 100_000);
builder.Services.AddSingleton<CacheMetrics>();

var app = builder.Build();

// In production nginx proxies /api/ same-origin, so CORS is dev-only
// (e.g. opening the static HTML directly against `dotnet run`).
if (app.Environment.IsDevelopment())
    app.UseCors();

// --- Endpoints ---
app.MapGet("/api/health", (CacheMetrics metrics) =>
    Results.Ok(new HealthResponse("ok", nadTable, metrics.Hits, metrics.Misses)));

// CancellationToken binds to HttpContext.RequestAborted: when the client
// disconnects, Npgsql sends a CANCEL to Postgres so abandoned queries stop
// burning DB CPU. 499 = client closed request (nobody reads it; it exists so
// the cancellation doesn't surface as an error-level unhandled exception).
app.MapPost("/api/verify", async (VerifyRequest req, AddressRepository repo,
    IMemoryCache cache, CacheMetrics metrics, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(req.Query))
        return Results.BadRequest(new ErrorResponse("query is required"));

    // NAD is read-only reference data: identical queries always produce
    // identical results, so cache hits never go stale within a deploy.
    var key = CacheKeys.Verify(req.Query);
    if (cache.TryGetValue(key, out List<AddressResult>? cached) && cached is not null)
    {
        metrics.Hit();
        return Results.Ok(cached);
    }

    try
    {
        metrics.Miss();
        var matches = await repo.SearchAsync(req.Query.Trim(), limit: 3, ct);
        cache.Set(key, matches, new MemoryCacheEntryOptions
        {
            Size = 1,
            // Misses (empty results) repeat too, but expire them sooner so a
            // typo fixed by a data reload isn't pinned for an hour.
            AbsoluteExpirationRelativeToNow =
                matches.Count > 0 ? TimeSpan.FromHours(1) : TimeSpan.FromMinutes(5),
        });
        return Results.Ok(matches);
    }
    catch (OperationCanceledException) when (ct.IsCancellationRequested)
    {
        return Results.StatusCode(499);
    }
    // Plain Results.Json (no explicit JsonTypeInfo) so the camelCase web
    // defaults apply, matching every other ErrorResponse on the wire.
    catch (QueryTooBroadException e)
    {
        return Results.Json(new ErrorResponse(e.Message),
            statusCode: StatusCodes.Status422UnprocessableEntity);
    }
    catch (NpgsqlException e) when (e.InnerException is TimeoutException)
    {
        // The 5s CommandTimeout is the guard against searches the indexes
        // can't carry; tell the user how to narrow instead of a bare 500.
        return Results.Json(
            new ErrorResponse("Search took too long — add a ZIP code, or a city and state."),
            statusCode: StatusCodes.Status504GatewayTimeout);
    }
});

app.MapPost("/api/submit", async (SubmitRequest req, AddressRepository repo, CancellationToken ct) =>
{
    if (string.IsNullOrWhiteSpace(req.Address))
        return Results.BadRequest(new ErrorResponse("address is required"));

    try
    {
        var id = await repo.SubmitAsync(req, ct);
        return Results.Ok(new SubmitResponse(id, "Address submitted to nad_sub."));
    }
    catch (OperationCanceledException) when (ct.IsCancellationRequested)
    {
        return Results.StatusCode(499);
    }
});

// The stats aggregates scan 4.86M rows; uncached they are a self-DoS. One
// refresh at a time (single-flight) and a 30s TTL keep the cost bounded no
// matter how hard the endpoint is polled.
var statsRefreshLock = new SemaphoreSlim(1, 1);

app.MapGet("/api/stats", async (AddressRepository repo, IMemoryCache cache, CancellationToken ct) =>
{
    if (cache.TryGetValue(CacheKeys.Stats, out StatsResponse? cached) && cached is not null)
        return Results.Ok(cached);

    await statsRefreshLock.WaitAsync(ct);
    try
    {
        if (cache.TryGetValue(CacheKeys.Stats, out cached) && cached is not null)
            return Results.Ok(cached);

        // Deliberately NOT cancelled by this caller: the refresh is shared
        // work whose result every queued caller (and the next 30s of traffic)
        // will reuse — one impatient client must not poison it.
        var stats = await repo.StatsAsync();
        cache.Set(CacheKeys.Stats, stats, new MemoryCacheEntryOptions
        {
            Size = 1,
            AbsoluteExpirationRelativeToNow = TimeSpan.FromSeconds(30),
        });
        return Results.Ok(stats);
    }
    finally
    {
        statsRefreshLock.Release();
    }
});

app.Run();
