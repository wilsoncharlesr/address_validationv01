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

    // Display-city expression: NAD writes the literal placeholder
    // 'Not stated' for a missing postal city (18M rows), with the real city in
    // inc_muni. MUST stay identical to the expression the (city, add_number)
    // btree index is built on, otherwise the locality search path below
    // degrades to a sequential scan.
    private const string CityExpr =
        "upper(coalesce(nullif(nullif(post_city,''),'Not stated'), inc_muni))";

    // Columns returned by both search paths (the trailing similarity score is
    // only evaluated for the few rows that survive LIMIT).
    private static readonly string SelectColumns = $@"
        uuid, addno_full, stnam_full, unit,
        coalesce(nullif(nullif(post_city,''),'Not stated'), inc_muni) AS city,
        county, state, zip_code, latitude, longitude,
        similarity({FullExpr}, lower(@q)) AS score";

    [GeneratedRegex(@"\b(\d{5})\b")]
    private static partial Regex ZipPattern();

    [GeneratedRegex("^[A-Za-z_][A-Za-z0-9_]*$")]
    private static partial Regex IdentifierPattern();

    [GeneratedRegex("[,;.]+")]
    private static partial Regex SeparatorPattern();

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
    /// <exception cref="QueryTooBroadException">No ZIP and no city could be parsed from the query.</exception>
    public async Task<List<AddressResult>> SearchAsync(string query, int limit = 3, CancellationToken ct = default)
    {
        await using var conn = await _nad.OpenConnectionAsync(ct);

        // Fast path: a 5-digit ZIP narrows the table to a few thousand rows via
        // the zip_code index, which we then rank by similarity (~tens of ms).
        var zip = ExtractZip(query);
        if (zip is not null)
        {
            var byZip = $@"
SELECT {SelectColumns}
FROM {_table}
WHERE zip_code = @zip
ORDER BY score DESC
LIMIT @lim";
            await using var zipCmd = new NpgsqlCommand(byZip, conn);
            zipCmd.Parameters.Add(new NpgsqlParameter<string>("q", query));
            zipCmd.Parameters.Add(new NpgsqlParameter<string>("zip", zip));
            zipCmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));

            var zipResults = await ReadResultsAsync(zipCmd, ct);
            if (zipResults.Count > 0)
                return zipResults;   // otherwise the ZIP was bad — fall through
        }

        // Locality path: narrow to one city via the (city, add_number) btree,
        // then rank only those rows by similarity. A trigram KNN over the whole
        // 96.9M-row national table blows the 5s CommandTimeout (and, unbounded,
        // has OOM-killed Postgres), so a query we cannot narrow is refused with
        // a clear message instead of timing out.
        var (state, houseNumber, cities) = ParseLocality(query);
        if (cities.Count == 0)
            throw new QueryTooBroadException(
                "Not enough to search on — include a ZIP code, or a city and state.");

        var where = new List<string>(3) { $"{CityExpr} = ANY(@cities)" };
        if (houseNumber is not null) where.Add("add_number = @hn");
        if (state is not null) where.Add("state = @st");

        var byCity = $@"
SELECT {SelectColumns}
FROM {_table}
WHERE {string.Join(" AND ", where)}
ORDER BY score DESC
LIMIT @lim";
        await using var cmd = new NpgsqlCommand(byCity, conn);
        cmd.Parameters.Add(new NpgsqlParameter<string[]>("cities", cities.ToArray()));
        if (houseNumber is not null)
            cmd.Parameters.Add(new NpgsqlParameter<long>("hn", houseNumber.Value));
        if (state is not null)
            cmd.Parameters.Add(new NpgsqlParameter<string>("st", state));
        cmd.Parameters.Add(new NpgsqlParameter<string>("q", query));
        cmd.Parameters.Add(new NpgsqlParameter<int>("lim", limit));
        return await ReadResultsAsync(cmd, ct);
    }

    /// <summary>
    /// The ZIP to search, if the query contains one. Takes the last 5-digit
    /// token: a leading one ("12345 Ventura Blvd") is a house number, not a
    /// ZIP, unless it is all the user typed.
    /// </summary>
    private static string? ExtractZip(string query)
    {
        Match? last = null;
        foreach (Match m in ZipPattern().Matches(query))
            last = m;
        if (last is null || (last.Index == 0 && query.Trim().Length > 5))
            return null;
        return last.Groups[1].Value;
    }

    /// <summary>
    /// Best-effort parse of a freeform address into the parts the locality
    /// search can filter on: a USPS state code, a numeric house number, and
    /// candidate city names. The city is some suffix of the query ("... San
    /// Antonio"), so the last 1–3 tokens are all offered and the index simply
    /// rejects the wrong guesses.
    /// </summary>
    private static (string? State, long? HouseNumber, List<string> Cities) ParseLocality(string query)
    {
        var tokens = SeparatorPattern().Replace(query, " ")
            .Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .ToList();

        long? houseNumber = null;
        if (tokens.Count > 1 && tokens[0].All(char.IsAsciiDigit)
            && long.TryParse(tokens[0], out var hn))
        {
            houseNumber = hn;
            tokens.RemoveAt(0);
        }

        // ZIPs belong to the ZIP path; keep them out of the city candidates.
        tokens.RemoveAll(t => t.Length == 5 && t.All(char.IsAsciiDigit));

        string? state = null;
        for (var n = Math.Min(3, tokens.Count); n >= 1; n--)   // "district of columbia"
        {
            var tail = string.Join(' ', tokens.TakeLast(n));
            if (StateCodes.TryGetValue(tail, out var code))
            {
                state = code;
                tokens.RemoveRange(tokens.Count - n, n);
                break;
            }
        }

        var cities = new List<string>(4);
        for (var n = 1; n <= Math.Min(3, tokens.Count); n++)
            cities.Add(string.Join(' ', tokens.TakeLast(n)).ToUpperInvariant());

        // "washington dc" parses entirely as the state; the postal city is fixed.
        if (state == "DC")
            cities.Add("WASHINGTON");

        return (state, houseNumber, cities);
    }

    /// <summary>USPS state/territory codes keyed by both full name and code.</summary>
    private static readonly Dictionary<string, string> StateCodes = BuildStateCodes();

    private static Dictionary<string, string> BuildStateCodes()
    {
        var names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["alabama"] = "AL", ["alaska"] = "AK", ["arizona"] = "AZ", ["arkansas"] = "AR",
            ["california"] = "CA", ["colorado"] = "CO", ["connecticut"] = "CT", ["delaware"] = "DE",
            ["florida"] = "FL", ["georgia"] = "GA", ["hawaii"] = "HI", ["idaho"] = "ID",
            ["illinois"] = "IL", ["indiana"] = "IN", ["iowa"] = "IA", ["kansas"] = "KS",
            ["kentucky"] = "KY", ["louisiana"] = "LA", ["maine"] = "ME", ["maryland"] = "MD",
            ["massachusetts"] = "MA", ["michigan"] = "MI", ["minnesota"] = "MN", ["mississippi"] = "MS",
            ["missouri"] = "MO", ["montana"] = "MT", ["nebraska"] = "NE", ["nevada"] = "NV",
            ["new hampshire"] = "NH", ["new jersey"] = "NJ", ["new mexico"] = "NM", ["new york"] = "NY",
            ["north carolina"] = "NC", ["north dakota"] = "ND", ["ohio"] = "OH", ["oklahoma"] = "OK",
            ["oregon"] = "OR", ["pennsylvania"] = "PA", ["rhode island"] = "RI", ["south carolina"] = "SC",
            ["south dakota"] = "SD", ["tennessee"] = "TN", ["texas"] = "TX", ["utah"] = "UT",
            ["vermont"] = "VT", ["virginia"] = "VA", ["washington"] = "WA", ["west virginia"] = "WV",
            ["wisconsin"] = "WI", ["wyoming"] = "WY",
            ["district of columbia"] = "DC", ["washington dc"] = "DC",
            ["puerto rico"] = "PR", ["guam"] = "GU", ["american samoa"] = "AS",
            ["virgin islands"] = "VI", ["northern mariana islands"] = "MP",
        };
        foreach (var code in names.Values.Distinct().ToList())
            names[code] = code;
        return names;
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
