using System.Text.RegularExpressions;

namespace AddressVerification;

/// <summary>Cache key constants/builders shared by the endpoints.</summary>
public static partial class CacheKeys
{
    public const string Stats = "stats";

    /// <summary>
    /// Key for a verify lookup: lowercased, trimmed, internal whitespace
    /// collapsed — so "123  Main St" and "123 main st " share an entry.
    /// </summary>
    public static string Verify(string query) =>
        "v:" + Whitespace().Replace(query.Trim().ToLowerInvariant(), " ");

    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();
}

/// <summary>
/// Hit/miss counters for the verify cache, exposed on /api/health. Capacity
/// planning (how much DB the cache absorbs at peak) depends on the real
/// traffic hit rate, so it must be observable.
/// </summary>
public sealed class CacheMetrics
{
    private long _hits;
    private long _misses;

    public void Hit() => Interlocked.Increment(ref _hits);
    public void Miss() => Interlocked.Increment(ref _misses);

    public long Hits => Interlocked.Read(ref _hits);
    public long Misses => Interlocked.Read(ref _misses);
}
