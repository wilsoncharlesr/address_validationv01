-- List all counties in the Illinois address table with address counts.
-- Run with:
--   docker exec address-verification-pg psql -U postgres -d nad -f - < tools/list_counties.sql
-- or from a client connected to localhost:5433.

SELECT county,
       count(*) AS addresses
FROM il_addresses
GROUP BY county
ORDER BY county;
