-- Schema for the `nad_sub` database: addresses a user confirmed and submitted.
--
-- Runs against the `nad_sub` database (created by start.py if it does not yet
-- exist). Each row is one address the user picked from the top-3 matches and
-- posted. The statistics page aggregates this table by county and by state.

CREATE TABLE IF NOT EXISTS submissions (
    id            BIGSERIAL PRIMARY KEY,
    query_text    TEXT,                 -- the raw address the user typed
    source_uuid   TEXT,                 -- NAD UUID of the chosen record
    address_line  TEXT,                 -- e.g. "1916 LOMBARD Avenue"
    unit          TEXT,
    city          TEXT,
    county        TEXT,
    state         TEXT,
    zip_code      TEXT,
    latitude      DOUBLE PRECISION,
    longitude     DOUBLE PRECISION,
    match_score   REAL,                 -- trigram similarity of the chosen match
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_submissions_county ON submissions (county);
CREATE INDEX IF NOT EXISTS idx_submissions_state  ON submissions (state);
