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

    [GeneratedRegex("^[A-Za-z_][A-Za-z0-9_]*$")]
    private static partial Regex IdentifierPattern();

    public AddressRepository(NpgsqlDataSource nad, NpgsqlDataSource nadSub, string table)
    {
        _nad = nad;
        _nadSub = nadSub;
        if (!IdentifierPattern().IsMatch(table))
            throw new ArgumentException($"Invalid table name: {table}");
        _table = table;
    }

    /// <summary>Return the top <paramref name="limit"/> closest addresses to the query string.</summary>
    /// <exception cref="QueryTooBroadException">No ZIP and no searchable components could be parsed.</exception>
    public async Task<List<AddressResult>> SearchAsync(string query, int limit = 3, CancellationToken ct = default)
    {
        var parsed = AddressParser.Parse(query.Trim());
        await using var conn = await _nad.OpenConnectionAsync(ct);

        // ZIP path — narrow to a few thousand rows, optionally filter by street + number.
        if (parsed.Zip is not null)
        {
            var byZip = await SearchByZipAsync(conn, parsed, limit, ct);
            if (byZip.Count > 0)
                return byZip;
        }

        // Street + house number (street-first for "555 Monroe").
        if (parsed.HouseNumber is not null && parsed.Street is not null)
        {
            var byStreet = await SearchByStreetAndNumberAsync(conn, parsed, limit, ct);

            if (parsed.AmbiguousStreetOrCity && parsed.CityCandidates.Count > 0)
            {
                var byCity = await SearchByLocalityAsync(conn, parsed, limit, ct);
                return MergeResults(byStreet, byCity, limit);
            }

            if (byStreet.Count > 0)
                return byStreet;
        }

        // Locality path: city (+ optional state, house number, street filter).
        if (parsed.CityCandidates.Count > 0)
            return await SearchByLocalityAsync(conn, parsed, limit, ct);

        if (parsed.State is not null && parsed.HouseNumber is not null)
            return await SearchByStreetAndNumberAsync(conn, parsed, limit, ct);

        throw new QueryTooBroadException(
            "Not enough to search on — include a ZIP code, or a city and state.");
    }

    private async Task<List<AddressResult>> SearchByZipAsync(
        NpgsqlConnection conn, ParsedAddress parsed, int limit, CancellationToken ct)
    {
        var where = new List<string> { "zip_code = @zip" };
        if (parsed.HouseNumber is not null)
            where.Add("add_number = @hn");
        if (parsed.Street is not null)
            where.Add($"({AddressScoring.StreetExpr} LIKE lower(@street) || '%' " +
                        $"OR similarity({AddressScoring.StreetExpr}, lower(@street)) > 0.2)");

        var sql = $@"
SELECT {AddressScoring.SelectColumns}
FROM {_table}
WHERE {string.Join(" AND ", where)}
ORDER BY score DESC
LIMIT @lim";

        await using var cmd = new NpgsqlCommand(sql, conn);
        BindScoreParameters(cmd, parsed);
        cmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));
        return await ReadResultsAsync(cmd, ct);
    }

    private async Task<List<AddressResult>> SearchByStreetAndNumberAsync(
        NpgsqlConnection conn, ParsedAddress parsed, int limit, CancellationToken ct)
    {
        var where = new List<string>
        {
            "add_number = @hn",
            $"({AddressScoring.StreetExpr} LIKE lower(@street) || '%' " +
            $"OR similarity({AddressScoring.StreetExpr}, lower(@street)) > 0.25)",
        };
        if (parsed.State is not null)
            where.Add("state = @st");
        if (parsed.Zip is not null)
            where.Add("zip_code = @zip");

        var sql = $@"
SELECT {AddressScoring.SelectColumns}
FROM {_table}
WHERE {string.Join(" AND ", where)}
ORDER BY score DESC
LIMIT @lim";

        await using var cmd = new NpgsqlCommand(sql, conn);
        BindScoreParameters(cmd, parsed);
        cmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));
        return await ReadResultsAsync(cmd, ct);
    }

    private async Task<List<AddressResult>> SearchByLocalityAsync(
        NpgsqlConnection conn, ParsedAddress parsed, int limit, CancellationToken ct)
    {
        var where = new List<string> { $"{AddressScoring.CityExpr} = ANY(@cities)" };
        if (parsed.HouseNumber is not null)
            where.Add("add_number = @hn");
        if (parsed.State is not null)
            where.Add("state = @st");
        if (parsed.Street is not null)
            where.Add($"({AddressScoring.StreetExpr} LIKE lower(@street) || '%' " +
                        $"OR similarity({AddressScoring.StreetExpr}, lower(@street)) > 0.2)");

        var sql = $@"
SELECT {AddressScoring.SelectColumns}
FROM {_table}
WHERE {string.Join(" AND ", where)}
ORDER BY score DESC
LIMIT @lim";

        await using var cmd = new NpgsqlCommand(sql, conn);
        BindScoreParameters(cmd, parsed);
        cmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));
        return await ReadResultsAsync(cmd, ct);
    }

    private static void BindScoreParameters(NpgsqlCommand cmd, ParsedAddress parsed)
    {
        cmd.Parameters.Add(new NpgsqlParameter<string>("q", parsed.Raw));
        cmd.Parameters.Add(Text("street", parsed.Street));
        cmd.Parameters.Add(parsed.HouseNumber is not null
            ? new NpgsqlParameter<long>("hn", parsed.HouseNumber.Value)
            : new NpgsqlParameter("hn", NpgsqlDbType.Bigint) { Value = DBNull.Value });
        cmd.Parameters.Add(new NpgsqlParameter<string[]>("cities",
            parsed.CityCandidates.Count > 0 ? parsed.CityCandidates.ToArray() : []));
        cmd.Parameters.Add(Text("st", parsed.State));
        cmd.Parameters.Add(Text("zip", parsed.Zip));
    }

    private static List<AddressResult> MergeResults(
        List<AddressResult> a, List<AddressResult> b, int limit)
    {
        return a.Concat(b)
            .GroupBy(r => r.Uuid ?? $"{r.Address}|{r.City}|{r.Zip}")
            .Select(g => g.OrderByDescending(r => r.Score).First())
            .OrderByDescending(r => r.Score)
            .Take(limit)
            .ToList();
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

    private static NpgsqlParameter Text(string name, string? value) =>
        new(name, NpgsqlDbType.Text) { Value = string.IsNullOrWhiteSpace(value) ? DBNull.Value : value };

    private static NpgsqlParameter Dbl(string name, double? value) =>
        new(name, NpgsqlDbType.Double) { Value = (object?)value ?? DBNull.Value };
}
