using AddressVerification;
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

var app = builder.Build();
app.UseCors();

// --- Endpoints ---
app.MapGet("/api/health", () => Results.Ok(new { status = "ok", table = nadTable }));

app.MapPost("/api/verify", async (VerifyRequest req, AddressRepository repo) =>
{
    if (string.IsNullOrWhiteSpace(req.Query))
        return Results.BadRequest(new { error = "query is required" });

    var matches = await repo.SearchAsync(req.Query.Trim(), limit: 3);
    return Results.Ok(matches);
});

app.MapPost("/api/submit", async (SubmitRequest req, AddressRepository repo) =>
{
    if (string.IsNullOrWhiteSpace(req.Address))
        return Results.BadRequest(new { error = "address is required" });

    var id = await repo.SubmitAsync(req);
    return Results.Ok(new { id, message = "Address submitted to nad_sub." });
});

app.MapGet("/api/stats", async (AddressRepository repo) => Results.Ok(await repo.StatsAsync()));

app.Run();
