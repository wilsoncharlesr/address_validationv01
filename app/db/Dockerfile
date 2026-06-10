# PostgreSQL image for the address-verification stack (local development).
#
# Base: postgres:16 with trust auth (NO password — local dev only) and the
# `nad` database created on first start.
#
# On a FRESH data volume the bundled bootstrap also creates the `nad_sub`
# database + submissions schema and enables pg_trgm in `nad`. On an existing
# volume (e.g. the pre-loaded ~4.86M-row `il_addresses` data) PostgreSQL skips
# the bootstrap, and start.py performs the same init idempotently instead — so
# this image is a drop-in for the container the rest of the stack expects.
#
# Build and run it with the companion script:  python3 start_db.py
FROM postgres:16

ENV POSTGRES_HOST_AUTH_METHOD=trust
ENV POSTGRES_DB=nad

# Submissions schema, kept in a subdirectory so PostgreSQL's entrypoint does
# NOT auto-run it against the default database — the bootstrap applies it to
# `nad_sub` explicitly.
COPY 02_init_nad_sub.sql /docker-entrypoint-initdb.d/sql/02_init_nad_sub.sql

# First-init bootstrap (runs once, only when the data directory is empty).
COPY initdb/10-bootstrap.sh /docker-entrypoint-initdb.d/10-bootstrap.sh
RUN chmod +x /docker-entrypoint-initdb.d/10-bootstrap.sh

EXPOSE 5432
