#!/usr/bin/env python3
"""
Load ALL address data under data/TXT into PostgreSQL, ready for the
address-verification API.

Wraps the proven COPY pipeline in load_nad_postgres.py (same container, same
60-column NAD schema) and finishes the job the API needs:

  1. stream every data/TXT/**/*.txt into the target table with COPY
     (currently the ~38 GB, ~74M-row national NAD_r22.txt)
  2. b-tree indexes on state, zip_code, county   (API fast path + stats)
  3. pg_trgm GiST expression index               (API similarity search —
     the expression MUST match AddressRepository.FullExpr exactly)
  4. ANALYZE

  5. switch the app over: persist nad_table in app/terraform/terraform.tfvars,
     re-apply terraform (recreates the api container with the new NAD_TABLE),
     and verify /api/health reports the new table

USAGE
  python3 load_all_addresses.py --limit 100000    # quick sample, no indexes, no switch
  python3 load_all_addresses.py                   # full load + switch the app
  python3 load_all_addresses.py --no-switch       # full load, leave the app alone
  python3 load_all_addresses.py --recreate        # drop table, then full load + switch
  python3 load_all_addresses.py --index-only      # (re)build indexes on existing rows
  python3 load_all_addresses.py --switch-only     # just point the app at --table
  python3 load_all_addresses.py --count           # row count and exit
  python3 load_all_addresses.py --drop-table      # drop the table and exit

The DB container must be running (python3 app/db/start_db.py). The switch step
refuses to point the app at a table that is empty or missing the trigram
index, and the api container's startup warmup pages the new index in before
the health check passes — so traffic never sees a cold or unsearchable table.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import load_nad_postgres as base  # noqa: E402  (container, COLUMNS, COPY path)

DEFAULT_TABLE = "nad_addresses"

# Free space needed on the Docker data volume for the full national load:
# ~40 GB of table data + b-tree indexes + multi-GB GiST trigram index + WAL.
REQUIRED_FREE_GB = 60

# Must stay byte-identical to AddressRepository.FullExpr in the C# service —
# and to app/db/01_init_nad.sql — or the API's KNN search will not use it.
FULL_EXPR = (
    "lower(coalesce(addno_full, '') || ' ' || "
    "coalesce(stnam_full, '') || ' ' || "
    "coalesce(post_city,  '') || ' ' || "
    "coalesce(state,      '') || ' ' || "
    "coalesce(zip_code,   '') )"
)


TF_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "app", "terraform")
TFVARS_PATH = os.path.join(TF_DIR, "terraform.tfvars")
# Host port the api container publishes (terraform var api_port default).
API_HEALTH_URL = "http://localhost:8081/api/health"


def container_running():
    state = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", base.CONTAINER],
        capture_output=True, text=True)
    return state.returncode == 0 and state.stdout.strip() == "running"


def table_exists(database, table):
    out = base.psql(database, f"SELECT to_regclass('{table}') IS NOT NULL",
                    capture=True)
    return out == "t"


def trigram_index_exists(database, table):
    out = base.psql(database,
                    f"SELECT 1 FROM pg_indexes WHERE tablename = '{table}' "
                    f"AND indexname = 'idx_{table}_fullgist'",
                    capture=True)
    return out == "1"


def write_tfvars(table):
    """Persist nad_table in terraform.tfvars so every future
    `terraform apply` / start.py run keeps using it (a -var flag would be
    forgotten on the next plain apply and silently revert the app)."""
    lines = []
    if os.path.exists(TFVARS_PATH):
        with open(TFVARS_PATH) as fh:
            lines = [l for l in fh.read().splitlines()
                     if not l.strip().startswith("nad_table")]
    lines.append(f'nad_table = "{table}"')
    with open(TFVARS_PATH, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Wrote nad_table = \"{table}\" to {os.path.relpath(TFVARS_PATH)}")


def switch_app(database, table, timeout_seconds=600):
    """Point the running app at <table>: guards, tfvars, terraform apply,
    then wait for the API to come back healthy on the new table."""
    if not table_exists(database, table):
        sys.exit(f"Cannot switch the app: table '{table}' does not exist in "
                 f"database '{database}'. Run the load first.")
    rows = base.row_count(database, table)
    if rows == 0:
        sys.exit(f"Cannot switch the app: table '{table}' is empty.")
    if not trigram_index_exists(database, table):
        sys.exit(f"Cannot switch the app: '{table}' has no trigram GiST index "
                 f"(idx_{table}_fullgist) — every search would sequential-scan "
                 f"{rows:,} rows. Run: python3 {os.path.basename(__file__)} "
                 f"--index-only --table {table}")

    write_tfvars(table)
    print("Applying terraform (recreates the api container with "
          f"NAD_TABLE={table})...", flush=True)
    result = subprocess.run(
        ["terraform", f"-chdir={TF_DIR}", "apply",
         "-auto-approve", "-input=false"],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"terraform apply failed:\n{result.stderr.strip()}")

    # The api startup warmup pages the new trigram index in before the
    # health endpoint answers — generous timeout for a cold 74M-row index.
    print(f"Waiting for the API on {API_HEALTH_URL} (warmup can take a few "
          "minutes on a cold index)...", flush=True)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(API_HEALTH_URL, timeout=5) as resp:
                health = json.load(resp)
            if health.get("table") == table:
                print(f"API is up and serving from '{table}' "
                      f"({rows:,} rows).")
                return
            # API answered but with the old table — container still swapping.
        except (urllib.error.URLError, ConnectionError, OSError, ValueError):
            pass
        time.sleep(3)
    sys.exit(f"API did not come back on '{table}' within {timeout_seconds}s; "
             f"check: docker logs address-verification-api")


def free_gb_on_data_volume():
    result = subprocess.run(
        ["docker", "exec", base.CONTAINER,
         "df", "-BG", "--output=avail", "/var/lib/postgresql/data"],
        capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return int(result.stdout.strip().splitlines()[-1].strip().rstrip("G"))


def build_all_indexes(database, table, skip_trigram=False):
    t0 = time.monotonic()
    base.build_indexes(database, table, base.DEFAULT_INDEXES)
    # City + house-number btree backing the API's no-ZIP locality search path.
    # The expression MUST match AddressRepository.CityExpr in the C# service.
    print("Creating city + house-number index...", flush=True)
    base.psql(database,
              "SET maintenance_work_mem = '1GB'; "
              f"CREATE INDEX IF NOT EXISTS idx_{table}_city "
              f"ON {table} (upper(coalesce(nullif(nullif(post_city,''),"
              f"'Not stated'), inc_muni)), add_number)")
    if skip_trigram:
        print("Skipping trigram index (--no-trigram).")
    else:
        print("Creating pg_trgm GiST index (several hours on the full "
              "~74M-row load — safe to leave running)...", flush=True)
        base.psql(database, "CREATE EXTENSION IF NOT EXISTS pg_trgm")
        # One psql session so the memory setting applies to the index build.
        base.psql(database,
                  "SET maintenance_work_mem = '1GB'; "
                  f"CREATE INDEX IF NOT EXISTS idx_{table}_fullgist "
                  f"ON {table} USING gist (({FULL_EXPR}) gist_trgm_ops)")
    base.psql(database, f"ANALYZE {table}")
    print(f"Indexes ready in {(time.monotonic() - t0) / 60:.1f} min.")


def main():
    parser = argparse.ArgumentParser(
        description="Load all data/TXT address data, ready for the API.")
    parser.add_argument("--database", default=base.DEFAULT_DB)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--limit", type=int, metavar="N",
                        help="load only the first N rows (skips index build)")
    parser.add_argument("--recreate", action="store_true",
                        help="drop the table first, then load")
    parser.add_argument("--append", action="store_true",
                        help="allow loading into a table that already has rows")
    parser.add_argument("--no-trigram", action="store_true",
                        help="skip the pg_trgm GiST index")
    parser.add_argument("--no-switch", action="store_true",
                        help="after a full load, leave the app on its current table")
    parser.add_argument("--force", action="store_true",
                        help="proceed even if the disk-space check fails")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--index-only", action="store_true",
                       help="only (re)build indexes on the existing table")
    group.add_argument("--switch-only", action="store_true",
                       help="only point the app at --table (no load)")
    group.add_argument("--count", action="store_true",
                       help="print the table row count and exit")
    group.add_argument("--drop-table", action="store_true",
                       help="drop the table and exit")
    args = parser.parse_args()

    if not container_running():
        sys.exit(f"Container '{base.CONTAINER}' is not running. "
                 "Start it with: python3 app/db/start_db.py")

    if args.count:
        print(f"{base.row_count(args.database, args.table):,} rows "
              f"in {args.database}.{args.table}")
        return
    if args.drop_table:
        base.drop_table(args.database, args.table)
        return
    if args.index_only:
        build_all_indexes(args.database, args.table,
                          skip_trigram=args.no_trigram)
        return
    if args.switch_only:
        switch_app(args.database, args.table)
        return

    if not args.limit:
        free = free_gb_on_data_volume()
        if free is None:
            print("Warning: could not determine free space on the data volume.")
        elif free < REQUIRED_FREE_GB and not args.force:
            sys.exit(f"Only {free} GB free on the Docker data volume; the full "
                     f"load needs ~{REQUIRED_FREE_GB} GB (table + indexes + WAL).\n"
                     "Grow the disk (Docker Desktop > Settings > Resources) or "
                     "rerun with --force.")
        else:
            print(f"{free} GB free on the data volume "
                  f"(~{REQUIRED_FREE_GB} GB needed).")

    files = base.find_data_files()
    print(f"Found {len(files)} data file(s) under {base.DATA_DIR}:")
    for f in files:
        print(f"  {os.path.relpath(f, base.DATA_DIR)}")

    base.create_database(args.database)
    if args.recreate:
        base.drop_table(args.database, args.table)
    base.create_table(args.database, args.table)

    existing = base.row_count(args.database, args.table)
    if existing and not args.append:
        sys.exit(f"Table '{args.table}' already has {existing:,} rows.\n"
                 "Rerun with --recreate to replace the data, or --append to "
                 "add to it.")

    for path in files:
        base.copy_file(args.database, args.table, path, limit=args.limit)

    if args.limit:
        print("\nSample load done (indexes skipped with --limit; the app was "
              "not switched — use --switch-only deliberately for samples).")
        return

    build_all_indexes(args.database, args.table, skip_trigram=args.no_trigram)
    total = base.row_count(args.database, args.table)
    print(f"\nLoad complete: {total:,} rows in {args.database}.{args.table}")

    if args.no_switch or args.no_trigram:
        if args.no_trigram and not args.no_switch:
            print("App not switched: --no-trigram means the table is not "
                  "searchable by the API yet.")
        print("Switch the app later with: "
              f"python3 {os.path.basename(__file__)} --switch-only "
              f"--table {args.table}")
    else:
        switch_app(args.database, args.table)


if __name__ == "__main__":
    main()
