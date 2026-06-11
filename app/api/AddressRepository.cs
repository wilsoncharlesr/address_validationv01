using System.Text.RegularExpressions;
using Npgsql;
using NpgsqlTypes;

namespace AddressVerification;

/// <summary>
/// All PostgreSQL access for the service. Talks to two databases on the same
/// server: <c>nad</c> (read-only NAD reference data) and <c>nad_sub</c> (the
/// addresses users confirm and submit).
/// </summary>
public sealed partial class AddressRepository
{
    private readonly NpgsqlDataSource _nad;
    private readonly NpgsqlDataSource _nadSub;
    private readonly string _table;

    // Normalized "full address" expression. MUST stay identical to the
    // expression the GiST trigram index is built on in db/01_init_nad.sql,
    // otherwise the `<->` KNN search below will not use the index.
    private const string FullExpr =
        "lower(coalesce(addno_full,'')||' '||coalesce(stnam_full,'')||' '||" +
        "coalesce(post_city,'')||' '||coalesce(state,'')||' '||coalesce(zip_code,''))";

    // Columns returned by both search paths (the trailing similarity score is
    // only evaluated for the few rows that survive LIMIT).
    private static readonly string SelectColumns = $@"
        uuid, addno_full, stnam_full, unit,
        coalesce(nullif(post_city, ''), inc_muni) AS city,
        county, state, zip_code, latitude, longitude,
        similarity({FullExpr}, lower(@q)) AS score";

    [GeneratedRegex(@"\b(\d{5})\b")]
    private static partial Regex ZipPattern();

    [GeneratedRegex("^[A-Za-z_][A-Za-z0-9_]*$")]
    private static partial Regex IdentifierPattern();

    public AddressRepository(NpgsqlDataSource nad, NpgsqlDataSource nadSub, string table)
    {
        _nad = nad;
        _nadSub = nadSub;
        // The table name comes from trusted config, but it is interpolated into
        // SQL, so reject anything that is not a plain identifier.
        if (!IdentifierPattern().IsMatch(table))
            throw new ArgumentException($"Invalid table name: {table}");
        _table = table;
    }

    /// <summary>
    /// Page the trigram GiST index into cache before the service takes
    /// traffic. On a cold PostgreSQL the first KNN search faults in the upper
    /// index levels from disk and can blow past the 5s fail-fast command
    /// timeout (surfacing as 500s) — so this runs one deliberately slow
    /// warmup search with a generous timeout at startup instead.
    /// </summary>
    public async Task WarmupAsync()
    {
        await using var conn = await _nad.OpenConnectionAsync();
        var sql = $@"
SELECT count(*) FROM (
    SELECT uuid FROM {_table}
    ORDER BY {FullExpr} <-> lower(@q)
    LIMIT 100
) warm";
        await using var cmd = new NpgsqlCommand(sql, conn) { CommandTimeout = 300 };
        cmd.Parameters.Add(new NpgsqlParameter<string>("q", "100 main street springfield il 62701"));
        await cmd.ExecuteScalarAsync();
    }

    /// <summary>Return the top <paramref name="limit"/> closest addresses to the query string.</summary>
    public async Task<List<AddressResult>> SearchAsync(string query, int limit = 3, CancellationToken ct = default)
    {
        await using var conn = await _nad.OpenConnectionAsync(ct);

        // Fast path: a 5-digit ZIP narrows the table to a few thousand rows via
        // the zip_code index, which we then rank by similarity (~tens of ms).
        var zipMatch = ZipPattern().Match(query);
        if (zipMatch.Success)
        {
            var byZip = $@"
SELECT {SelectColumns}
FROM {_table}
WHERE zip_code = @zip
ORDER BY score DESC
LIMIT @lim";
            await using var zipCmd = new NpgsqlCommand(byZip, conn);
            zipCmd.Parameters.Add(new NpgsqlParameter<string>("q", query));
            zipCmd.Parameters.Add(new NpgsqlParameter<string>("zip", zipMatch.Groups[1].Value));
            zipCmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));

            var zipResults = await ReadResultsAsync(zipCmd, ct);
            if (zipResults.Count > 0)
                return zipResults;   // otherwise the ZIP was bad — fall through
        }

        // General path: GiST KNN over the whole table. The `<->` ordering walks
        // the trigram index in nearest-first order and always returns matches.
        var knn = $@"
SELECT {SelectColumns}
FROM {_table}
ORDER BY {FullExpr} <-> lower(@q)
LIMIT @lim";
        await using var cmd = new NpgsqlCommand(knn, conn);
        cmd.Parameters.Add(new NpgsqlParameter<string>("q", query));
        cmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));
        return await ReadResultsAsync(cmd, ct);
    }

    private static async Task<List<AddressResult>> ReadResultsAsync(NpgsqlCommand cmd, CancellationToken ct)
    {
        var results = new List<AddressResult>();
        await using var r = await cmd.ExecuteReaderAsync(ct);
        while (await r.ReadAsync(ct))
        {
            var house = r.IsDBNull(1) ? "" : r.GetString(1);
            var street = r.IsDBNull(2) ? "" : r.GetString(2);
            results.Add(new AddressResult
            {
                Uuid = r.IsDBNull(0) ? null : r.GetString(0),
                Address = $"{house} {street}".Trim(),
                Unit = r.IsDBNull(3) ? null : r.GetString(3),
                City = r.IsDBNull(4) ? null : r.GetString(4),
                County = r.IsDBNull(5) ? null : r.GetString(5),
                State = r.IsDBNull(6) ? null : r.GetString(6),
                Zip = r.IsDBNull(7) ? null : r.GetString(7),
                Latitude = r.IsDBNull(8) ? null : r.GetDouble(8),
                Longitude = r.IsDBNull(9) ? null : r.GetDouble(9),
                // similarity() returns float4 — read it directly, no boxing
                Score = r.IsDBNull(10) ? 0 : r.GetFloat(10),
            });
        }
        return results;
    }

    /// <summary>Insert a confirmed address into nad_sub.submissions; return its id.</summary>
    public async Task<long> SubmitAsync(SubmitRequest s, CancellationToken ct = default)
    {
        const string sql = @"
INSERT INTO submissions
  (query_text, source_uuid, address_line, unit, city, county, state, zip_code,
   latitude, longitude, match_score)
VALUES (@q, @uuid, @addr, @unit, @city, @county, @state, @zip, @lat, @lon, @score)
RETURNING id";

        await using var conn = await _nadSub.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.Parameters.Add(Text("q", s.Query));
        cmd.Parameters.Add(Text("uuid", s.Uuid));
        cmd.Parameters.Add(Text("addr", s.Address));
        cmd.Parameters.Add(Text("unit", s.Unit));
        cmd.Parameters.Add(Text("city", s.City));
        cmd.Parameters.Add(Text("county", s.County));
        cmd.Parameters.Add(Text("state", s.State));
        cmd.Parameters.Add(Text("zip", s.Zip));
        cmd.Parameters.Add(Dbl("lat", s.Latitude));
        cmd.Parameters.Add(Dbl("lon", s.Longitude));
        cmd.Parameters.Add(new NpgsqlParameter<float>("score", (float)s.Score));

        var id = await cmd.ExecuteScalarAsync(ct);
        return Convert.ToInt64(id);
    }

    /// <summary>Per-county / per-state breakdowns for both databases.</summary>
    public async Task<StatsResponse> StatsAsync(CancellationToken ct = default)
    {
        // Separate data sources, so the two scans can run concurrently.
        var nadTask = DbStatsAsync(_nad, _table, ct);
        var nadSubTask = DbStatsAsync(_nadSub, "submissions", ct);
        await Task.WhenAll(nadTask, nadSubTask);
        return new StatsResponse(await nadTask, await nadSubTask);
    }

    private static async Task<DbStats> DbStatsAsync(NpgsqlDataSource ds, string table, CancellationToken ct)
    {
        await using var conn = await ds.OpenConnectionAsync(ct);

        long total;
        await using (var c = new NpgsqlCommand($"SELECT count(*) FROM {table}", conn))
            total = Convert.ToInt64(await c.ExecuteScalarAsync(ct));

        var byState = await BucketsAsync(conn,
            $@"SELECT coalesce(nullif(trim(state), ''), '(unknown)') AS name, count(*)
               FROM {table} GROUP BY 1 ORDER BY count(*) DESC, name", ct);
        var byCounty = await BucketsAsync(conn,
            $@"SELECT coalesce(nullif(trim(county), ''), '(unknown)') AS name, count(*)
               FROM {table} GROUP BY 1 ORDER BY count(*) DESC, name", ct);

        return new DbStats(total, byState, byCounty);
    }

    private static async Task<List<Bucket>> BucketsAsync(NpgsqlConnection conn, string sql, CancellationToken ct)
    {
        await using var cmd = new NpgsqlCommand(sql, conn);
        var rows = new List<Bucket>();
        await using var r = await cmd.ExecuteReaderAsync(ct);
        while (await r.ReadAsync(ct))
            rows.Add(new Bucket(r.GetString(0), r.GetInt64(1)));
        return rows;
    }

    // Explicitly typed parameters: no per-call type inference, and stable
    // parameter types keep auto-prepared statements reusable.
    private static NpgsqlParameter Text(string name, string? value) =>
        new(name, NpgsqlDbType.Text) { Value = string.IsNullOrWhiteSpace(value) ? DBNull.Value : value };

    private static NpgsqlParameter Dbl(string name, double? value) =>
        new(name, NpgsqlDbType.Double) { Value = (object?)value ?? DBNull.Value };
}
