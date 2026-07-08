namespace AddressVerification;

/// <summary>
/// Component-weighted ranking SQL shared by every search path. Field-level
/// trigram similarity on the street name stops whole-string matches like
/// "Montrose" beating "Monroe" when the user typed a street.
/// </summary>
internal static class AddressScoring
{
    // Normalized street expression — keep in sync with search indexes in
    // app/db/01_init_nad.sql and tools/load_all_addresses.py.
    internal const string StreetExpr = "lower(coalesce(stnam_full,''))";

    internal const string CityExpr =
        "upper(coalesce(nullif(nullif(post_city,''),'Not stated'), inc_muni))";

    internal const string FullExpr =
        "lower(coalesce(addno_full,'')||' '||coalesce(stnam_full,'')||' '||" +
        "coalesce(post_city,'')||' '||coalesce(state,'')||' '||coalesce(zip_code,''))";

  /// <summary>SQL expression aliased as <c>score</c> (0..1-ish).</summary>
    internal static string ScoreExpression => $@"
(
  CASE WHEN @street IS NOT NULL AND length(@street) > 0
       THEN similarity({StreetExpr}, lower(@street)) * 0.35
            + CASE WHEN {StreetExpr} LIKE lower(@street) || '%' THEN 0.20 ELSE 0 END
       ELSE 0 END
  + CASE WHEN @hn IS NOT NULL AND add_number = @hn THEN 0.25 ELSE 0 END
  + CASE WHEN @cities IS NOT NULL AND cardinality(@cities) > 0
              AND {CityExpr} = ANY(@cities) THEN 0.15 ELSE 0 END
  + CASE WHEN @st IS NOT NULL AND length(@st) > 0 AND state = @st THEN 0.10 ELSE 0 END
  + CASE WHEN @zip IS NOT NULL AND length(@zip) > 0 AND zip_code = @zip THEN 0.10 ELSE 0 END
  + similarity({FullExpr}, lower(@q)) * 0.05
)";

    internal static string SelectColumns => $@"
        uuid, addno_full, stnam_full, unit,
        coalesce(nullif(nullif(post_city,''),'Not stated'), inc_muni) AS city,
        county, state, zip_code, latitude, longitude,
        {ScoreExpression} AS score";
}
