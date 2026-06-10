#!/usr/bin/env bash
# First-init bootstrap for the address-verification PostgreSQL container.
#
# PostgreSQL's official entrypoint runs this ONCE, the first time the data
# volume is initialized (i.e. when the data directory is empty). It is skipped
# entirely on an existing volume — so the pre-loaded il_addresses data is never
# touched. Every statement is idempotent, so re-running it by hand is safe too.
set -euo pipefail

DB_USER="${POSTGRES_USER:-postgres}"
SQL_DIR="/docker-entrypoint-initdb.d/sql"

echo "[bootstrap] creating the nad_sub database (if absent)..."
if ! psql -U "$DB_USER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='nad_sub'" | grep -q 1; then
  psql -U "$DB_USER" -d postgres -c 'CREATE DATABASE nad_sub'
fi

echo "[bootstrap] applying the nad_sub submissions schema..."
psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d nad_sub -f "$SQL_DIR/02_init_nad_sub.sql"

echo "[bootstrap] enabling pg_trgm in nad..."
psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d nad -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm'

echo "[bootstrap] done. The trigram search index on il_addresses is built"
echo "[bootstrap] after the address data is loaded (see db/01_init_nad.sql)."
