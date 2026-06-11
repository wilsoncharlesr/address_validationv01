using System.Text.RegularExpressions;
using Npgsql;

namespace AddressVerification;

/// <summary>
/// All PostgreSQL access for the service. Talks to two databases on the same
/// server: <c>nad</c> (read-only NAD reference data) and <c>nad_sub</c> (the
/// addresses users confirm and submit).
/// </summary>
public sealed class AddressRepository
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

    private static readonly Regex ZipPattern = new(@"\b(\d{5})\b", RegexOptions.Compiled);

    public AddressRepository(NpgsqlDataSource nad, NpgsqlDataSource nadSub, string table)
    {
        _nad = nad;
        _nadSub = nadSub;
        // The table name comes from trusted config, but it is interpolated into
        // SQL, so reject anything that is not a plain identifier.
        if (!Regex.IsMatch(table, "^[A-Za-z_][A-Za-z0-9_]*$"))
            throw new ArgumentException($"Invalid table name: {table}");
        _table = table;
    }

    /// <summary>Return the top <paramref name="limit"/> closest addresses to the query string.</summary>
    public async Task<List<AddressResult>> SearchAsync(string query, int limit = 3)
    {
        await using var conn = await _nad.OpenConnectionAsync();

        // Fast path: a 5-digit ZIP narrows the table to a few thousand rows via
        // the zip_code index, which we then rank by similarity (~tens of ms).
        var zipMatch = ZipPattern.Match(query);
        if (zipMatch.Success)
        {
            var byZip = $@"
SELECT {SelectColumns}
FROM {_table}
WHERE zip_code = @zip
ORDER BY score DESC
LIMIT @lim";
            await using var zipCmd = new NpgsqlCommand(byZip, conn);
            zipCmd.Parameters.AddWithValue("q", query);
            zipCmd.Parameters.AddWithValue("zip", zipMatch.Groups[1].Value);
            zipCmd.Parameters.AddWithValue("lim", limit);

            var zipResults = await ReadResultsAsync(zipCmd);
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
        cmd.Parameters.AddWithValue("q", query);
        cmd.Parameters.AddWithValue("lim", limit);
        return await ReadResultsAsync(cmd);
    }

    private static async Task<List<AddressResult>> ReadResultsAsync(NpgsqlCommand cmd)
    {
        var results = new List<AddressResult>();
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
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
                Score = r.IsDBNull(10) ? 0 : Convert.ToDouble(r.GetValue(10)),
            });
        }
        return results;
    }

    /// <summary>Insert a confirmed address into nad_sub.submissions; return its id.</summary>
    public async Task<long> SubmitAsync(SubmitRequest s)
    {
        const string sql = @"
INSERT INTO submissions
  (query_text, source_uuid, address_line, unit, city, county, state, zip_code,
   latitude, longitude, match_score)
VALUES (@q, @uuid, @addr, @unit, @city, @county, @state, @zip, @lat, @lon, @score)
RETURNING id";

        await using var conn = await _nadSub.OpenConnectionAsync();
        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.Parameters.AddWithValue("q", Nz(s.Query));
        cmd.Parameters.AddWithValue("uuid", Nz(s.Uuid));
        cmd.Parameters.AddWithValue("addr", Nz(s.Address));
        cmd.Parameters.AddWithValue("unit", Nz(s.Unit));
        cmd.Parameters.AddWithValue("city", Nz(s.City));
        cmd.Parameters.AddWithValue("county", Nz(s.County));
        cmd.Parameters.AddWithValue("state", Nz(s.State));
        cmd.Parameters.AddWithValue("zip", Nz(s.Zip));
        cmd.Parameters.AddWithValue("lat", (object?)s.Latitude ?? DBNull.Value);
        cmd.Parameters.AddWithValue("lon", (object?)s.Longitude ?? DBNull.Value);
        cmd.Parameters.AddWithValue("score", s.Score);

        var id = await cmd.ExecuteScalarAsync();
        return Convert.ToInt64(id);
    }

    /// <summary>Per-county / per-state breakdowns for both databases.</summary>
    public async Task<StatsResponse> StatsAsync()
    {
        // Separate data sources, so the two scans can run concurrently.
        var nadTask = DbStatsAsync(_nad, _table);
        var nadSubTask = DbStatsAsync(_nadSub, "submissions");
        await Task.WhenAll(nadTask, nadSubTask);
        return new StatsResponse(await nadTask, await nadSubTask);
    }

    private static async Task<DbStats> DbStatsAsync(NpgsqlDataSource ds, string table)
    {
        await using var conn = await ds.OpenConnectionAsync();

        long total;
        await using (var c = new NpgsqlCommand($"SELECT count(*) FROM {table}", conn))
            total = Convert.ToInt64(await c.ExecuteScalarAsync());

        var byState = await BucketsAsync(conn,
            $@"SELECT coalesce(nullif(trim(state), ''), '(unknown)') AS name, count(*)
               FROM {table} GROUP BY 1 ORDER BY count(*) DESC, name");
        var byCounty = await BucketsAsync(conn,
            $@"SELECT coalesce(nullif(trim(county), ''), '(unknown)') AS name, count(*)
               FROM {table} GROUP BY 1 ORDER BY count(*) DESC, name");

        return new DbStats(total, byState, byCounty);
    }

    private static async Task<List<Bucket>> BucketsAsync(NpgsqlConnection conn, string sql)
    {
        await using var cmd = new NpgsqlCommand(sql, conn);
        var rows = new List<Bucket>();
        await using var r = await cmd.ExecuteReaderAsync();
        while (await r.ReadAsync())
            rows.Add(new Bucket(r.GetString(0), r.GetInt64(1)));
        return rows;
    }

    private static object Nz(string? s) => string.IsNullOrWhiteSpace(s) ? DBNull.Value : s;
}
