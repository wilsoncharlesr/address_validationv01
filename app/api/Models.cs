namespace AddressVerification;

/// <summary>Body of POST /api/verify — the raw address the user typed.</summary>
public record VerifyRequest(string Query);

/// <summary>One candidate address returned by the similarity search.</summary>
public record AddressResult
{
    public string? Uuid { get; init; }
    public string Address { get; init; } = "";   // "1916 LOMBARD Avenue"
    public string? Unit { get; init; }
    public string? City { get; init; }
    public string? County { get; init; }
    public string? State { get; init; }
    public string? Zip { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public double Score { get; init; }           // trigram similarity 0..1
}

/// <summary>
/// Body of POST /api/submit — the candidate the user chose, plus the original
/// query. Mirrors <see cref="AddressResult"/> so the frontend can post a result
/// straight back.
/// </summary>
public record SubmitRequest
{
    public string? Query { get; init; }
    public string? Uuid { get; init; }
    public string Address { get; init; } = "";
    public string? Unit { get; init; }
    public string? City { get; init; }
    public string? County { get; init; }
    public string? State { get; init; }
    public string? Zip { get; init; }
    public double? Latitude { get; init; }
    public double? Longitude { get; init; }
    public double Score { get; init; }
}

/// <summary>A single (name, count) row in a statistics breakdown.</summary>
public record Bucket(string Name, long Count);

/// <summary>Counts for one database: total plus per-state and per-county.</summary>
public record DbStats(long Total, IReadOnlyList<Bucket> ByState, IReadOnlyList<Bucket> ByCounty);

/// <summary>Body of GET /api/stats — both databases side by side.</summary>
public record StatsResponse(DbStats Nad, DbStats NadSub);
