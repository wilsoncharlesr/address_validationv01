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

USAGE
  python3 load_all_addresses.py --limit 100000    # quick sample, no indexes
  python3 load_all_addresses.py                   # full load (COPY ~1h, GiST index several h)
  python3 load_all_addresses.py --recreate        # drop table, then full load
  python3 load_all_addresses.py --index-only      # (re)build indexes on existing rows
  python3 load_all_addresses.py --count           # row count and exit
  python3 load_all_addresses.py --drop-table      # drop the table and exit

The DB container must be running (python3 app/db/start_db.py). After a full
load, point the API at the new table:

  terraform: -var nad_table=nad_addresses   (or env NAD_TABLE=nad_addresses)
  then restart the api container — its startup warmup will page the new
  trigram index in before serving traffic.
"""

import argparse
import os
import subprocess
import sys
import time

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


def container_running():
    state = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", base.CONTAINER],
        capture_output=True, text=True)
    return state.returncode == 0 and state.stdout.strip() == "running"


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
    parser.add_argument("--force", action="store_true",
                        help="proceed even if the disk-space check fails")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--index-only", action="store_true",
                       help="only (re)build indexes on the existing table")
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
        print("\nSample load done (indexes skipped with --limit).")
    else:
        build_all_indexes(args.database, args.table,
                          skip_trigram=args.no_trigram)

    total = base.row_count(args.database, args.table)
    print(f"\nLoad complete: {total:,} rows in {args.database}.{args.table}")
    print("\nPoint the API at this table and restart it:")
    print(f"  terraform -chdir=app/terraform apply -var nad_table={args.table}")
    print(f"  (or set NAD_TABLE={args.table} and restart the api container)")


if __name__ == "__main__":
    main()
