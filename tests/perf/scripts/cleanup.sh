#!/usr/bin/env bash
# Remove rows inserted by perf and E2E test suites.
set -euo pipefail
CONTAINER="${PG_CONTAINER:-address-verification-pg}"
docker exec "$CONTAINER" psql -U postgres -d nad_sub -c \
  "DELETE FROM submissions WHERE query_text LIKE 'PERFTEST::%' OR query_text LIKE 'FUNCTEST::%';"
