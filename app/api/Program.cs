using AddressVerification;
using Npgsql;

var builder = WebApplication.CreateBuilder(args);

// --- Configuration (env vars, with localhost defaults for running outside Docker) ---
string nadConn = Environment.GetEnvironmentVariable("NAD_CONNECTION")
    ?? "Host=localhost;Port=5433;Database=nad;Username=postgres";
string nadSubConn = Environment.GetEnvironmentVariable("NADSUB_CONNECTION")
    ?? "Host=localhost;Port=5433;Database=nad_sub;Username=postgres";
string nadTable = Environment.GetEnvironmentVariable("NAD_TABLE") ?? "il_addresses";

var nadDataSource = new NpgsqlDataSourceBuilder(nadConn).Build();
var nadSubDataSource = new NpgsqlDataSourceBuilder(nadSubConn).Build();

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
