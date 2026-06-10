-- Look up 507 Leavett Street, Jerseyville, IL.
-- Run with:
--   docker exec -i address-verification-pg psql -U postgres -d nad -f - < tools/query_507_leavett.sql
-- or from a client connected to localhost:5433.

SELECT addno_full   AS house_number,
       stnam_full   AS street,
       unit,
       post_city    AS city,
       county,
       state,
       zip_code,
       latitude,
       longitude,
       addr_type,
       dateupdate   AS last_updated
FROM il_addresses
WHERE add_number = 507
  AND stnam_full ILIKE '%leavett%'      -- uses the trigram index
  AND post_city ILIKE '%jerseyville%';
