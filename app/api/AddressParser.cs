using System.Text.RegularExpressions;

namespace AddressVerification;

/// <summary>Parsed components extracted from a freeform address query.</summary>
public sealed class ParsedAddress
{
    public string Raw { get; init; } = "";
    public string? Zip { get; init; }
    public string? State { get; init; }
    public long? HouseNumber { get; init; }
    /// <summary>Normalized street name for matching (suffix and directions kept).</summary>
    public string? Street { get; init; }
    public string? Unit { get; init; }
    /// <summary>Uppercase city candidates for the locality index path.</summary>
    public IReadOnlyList<string> CityCandidates { get; init; } = [];
    /// <summary>True when a lone token after the house number could be street or city.</summary>
    public bool AmbiguousStreetOrCity { get; init; }
}

/// <summary>
/// Regex-based USPS-oriented address parser. Extracts structured fields so
/// search can target specific btree indexes instead of whole-string trigrams.
/// </summary>
public static partial class AddressParser
{
    [GeneratedRegex(@"\b(\d{5})(?:-\d{4})?\b")]
    private static partial Regex ZipPattern();

    [GeneratedRegex(@"[,;.]+")]
    private static partial Regex SeparatorPattern();

    [GeneratedRegex(
        @"\b(?:#|apt\.?|apartment|unit|ste\.?|suite|bldg\.?|building|fl\.?|floor|rm\.?|room)\s*#?\s*([\w-]+)\b",
        RegexOptions.IgnoreCase)]
    private static partial Regex UnitPattern();

    private static readonly HashSet<string> StreetSuffixes = new(StringComparer.OrdinalIgnoreCase)
    {
        "st", "street", "ave", "avenue", "rd", "road", "blvd", "boulevard", "dr", "drive",
        "ln", "lane", "ct", "court", "cir", "circle", "way", "pl", "place", "pkwy", "parkway",
        "hwy", "highway", "ter", "terrace", "trl", "trail", "loop", "run", "pass", "path",
        "pike", "aly", "alley", "expy", "expressway", "fwy", "freeway", "sq", "square",
        "cv", "cove", "cr", "crossing", "xing",
    };

    private static readonly HashSet<string> Directions = new(StringComparer.OrdinalIgnoreCase)
    {
        "n", "s", "e", "w", "ne", "nw", "se", "sw",
        "north", "south", "east", "west",
        "northeast", "northwest", "southeast", "southwest",
    };

    /// <summary>USPS state/territory codes keyed by both full name and code.</summary>
    public static IReadOnlyDictionary<string, string> StateCodes { get; } = BuildStateCodes();

    public static ParsedAddress Parse(string query)
    {
        var raw = query.Trim();
        if (raw.Length == 0)
            return new ParsedAddress { Raw = raw };

        var working = SeparatorPattern().Replace(raw, " ");
        working = Regex.Replace(working, @"\s+", " ").Trim();

        string? unit = null;
        var unitMatch = UnitPattern().Match(working);
        if (unitMatch.Success)
        {
            unit = unitMatch.Groups[1].Value;
            working = working[..unitMatch.Index] + working[(unitMatch.Index + unitMatch.Length)..];
            working = Regex.Replace(working, @"\s+", " ").Trim();
        }

        var zip = ExtractZip(raw, working);

        var tokens = working.Split(' ', StringSplitOptions.RemoveEmptyEntries).ToList();
        if (zip is not null)
            tokens.RemoveAll(t => t.Length == 5 && t.All(char.IsAsciiDigit) && t == zip);

        long? houseNumber = null;
        if (tokens.Count > 0 && TryParseHouseNumber(tokens[0], out var hn))
        {
            houseNumber = hn;
            tokens.RemoveAt(0);
        }

        string? state = null;
        for (var n = Math.Min(3, tokens.Count); n >= 1; n--)
        {
            var tail = string.Join(' ', tokens.TakeLast(n));
            if (StateCodes.TryGetValue(tail, out var code))
            {
                state = code;
                tokens.RemoveRange(tokens.Count - n, n);
                break;
            }
        }

        string? street = null;
        var cityCandidates = new List<string>(4);
        var ambiguous = false;

        if (tokens.Count > 0)
        {
            var suffixIdx = FindStreetSuffixIndex(tokens);
            if (suffixIdx >= 0)
            {
                street = string.Join(' ', tokens.Take(suffixIdx + 1));
                var cityTokens = tokens.Skip(suffixIdx + 1).ToList();
                AddCityCandidates(cityCandidates, cityTokens);
            }
            else if (tokens.Count == 1)
            {
                // "555 Monroe" — prefer street interpretation; keep city for fusion.
                street = tokens[0];
                cityCandidates.Add(tokens[0].ToUpperInvariant());
                ambiguous = true;
            }
            else
            {
                // No suffix: last 1–3 tokens may be city, remainder is street.
                var cityTokenCount = Math.Min(3, tokens.Count - 1);
                if (cityTokenCount < 1) cityTokenCount = 1;

                for (var n = 1; n <= cityTokenCount; n++)
                    cityCandidates.Add(string.Join(' ', tokens.TakeLast(n)).ToUpperInvariant());

                var streetTokens = tokens.Take(tokens.Count - 1).ToList();
                if (streetTokens.Count > 0 && !IsAllDirections(streetTokens))
                    street = string.Join(' ', streetTokens);
                else if (tokens.Count >= 2)
                    ambiguous = true;
            }
        }

        if (state == "DC")
            cityCandidates.Add("WASHINGTON");

        return new ParsedAddress
        {
            Raw = raw,
            Zip = zip,
            State = state,
            HouseNumber = houseNumber,
            Street = NormalizeStreet(street),
            Unit = unit,
            CityCandidates = cityCandidates.Distinct().ToList(),
            AmbiguousStreetOrCity = ambiguous,
        };
    }

    private static string? ExtractZip(string raw, string working)
    {
        Match? last = null;
        foreach (Match m in ZipPattern().Matches(working))
            last = m;
        if (last is null)
        {
            foreach (Match m in ZipPattern().Matches(raw))
                last = m;
        }
        if (last is null || (last.Index == 0 && raw.Trim().Length > 5))
            return null;
        return last.Groups[1].Value;
    }

    private static bool TryParseHouseNumber(string token, out long value)
    {
        value = 0;
        var digits = token.TakeWhile(c => char.IsAsciiDigit(c)).ToArray();
        if (digits.Length == 0 || digits.Length != token.Length && token[digits.Length] is not ('A' or 'a' or 'B' or 'b' or 'C' or 'c' or 'D' or 'd'))
            return false;
        return long.TryParse(new string(digits), out value);
    }

    private static int FindStreetSuffixIndex(List<string> tokens)
    {
        for (var i = tokens.Count - 1; i >= 0; i--)
        {
            if (StreetSuffixes.Contains(tokens[i].TrimEnd('.')))
                return i;
        }
        return -1;
    }

    private static void AddCityCandidates(List<string> cities, List<string> cityTokens)
    {
        for (var n = 1; n <= Math.Min(3, cityTokens.Count); n++)
            cities.Add(string.Join(' ', cityTokens.TakeLast(n)).ToUpperInvariant());
    }

    private static bool IsAllDirections(List<string> tokens) =>
        tokens.All(t => Directions.Contains(t.TrimEnd('.')));

    private static string? NormalizeStreet(string? street)
    {
        if (string.IsNullOrWhiteSpace(street))
            return null;
        return street.Trim().ToLowerInvariant();
    }

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
}
