-- Prepare the existing `nad` database for fuzzy address verification.
--
-- Runs against the `nad` database (table `il_addresses`, ~4.86M Illinois rows
-- in the 60-column NAD schema). Safe to run repeatedly — every statement is
-- idempotent. The trigram GIN index is what makes the similarity search in the
-- C# API fast; building it the first time on ~4.86M rows takes a few minutes.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- GiST trigram index on the same normalized "full address" expression the API
-- searches against. The expression MUST match AddressRepository.FullExpr in the
-- C# service exactly. GiST (not GIN) so the `<->` distance operator can drive a
-- KNN "top-3 nearest" index scan that always returns matches and stops at LIMIT.
CREATE INDEX IF NOT EXISTS idx_il_addresses_fullgist
ON il_addresses
USING gist (
  (
    lower(
      coalesce(addno_full, '') || ' ' ||
      coalesce(stnam_full, '') || ' ' ||
      coalesce(post_city,  '') || ' ' ||
      coalesce(state,      '') || ' ' ||
      coalesce(zip_code,   '')
    )
  ) gist_trgm_ops
);

-- A plain GIN trigram index was used by an earlier design; drop it if present.
DROP INDEX IF EXISTS idx_il_addresses_fulltrgm;

-- Grouped-stats helpers (county / state already indexed by the loaders, but
-- make sure they exist for the statistics page aggregates).
CREATE INDEX IF NOT EXISTS idx_il_addresses_county ON il_addresses (county);
CREATE INDEX IF NOT EXISTS idx_il_addresses_state  ON il_addresses (state);

ANALYZE il_addresses;
