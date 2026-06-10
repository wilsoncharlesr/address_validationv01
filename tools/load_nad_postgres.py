#!/usr/bin/env python3
"""
Bulk-load the National Address Database (NAD) CSV files into PostgreSQL.

Finds every ``*.txt`` data file under ``data/TXT`` (currently the ~38 GB,
~74M-row ``NAD_r22.txt``), creates the target database and table if needed,
and streams the rows into PostgreSQL with native ``COPY`` — the fastest bulk
path. No Python packages are required: everything goes through ``docker exec``
into the container started by ``start_postgres.py``.

Column types come from the dataset's ``schema.ini`` (bigint ids, double
precision coordinates, timestamps for the date columns, text for the rest).

USAGE
  python3 load_nad_postgres.py --limit 100000   # quick sample load
  python3 load_nad_postgres.py                  # full load (takes a while)
  python3 load_nad_postgres.py --recreate       # drop table, then full load
  python3 load_nad_postgres.py --drop-table     # drop the table only
  python3 load_nad_postgres.py --drop-database  # drop the whole database
  python3 load_nad_postgres.py --count          # row count in the table

After a full (non --limit) load, indexes are created on State, Zip_Code and
County (skip with --no-index).
"""

import argparse
import glob
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "data", "TXT")

CONTAINER = "address-verification-pg"
DEFAULT_DB = "nad"
DEFAULT_TABLE = "nad_addresses"
DEFAULT_INDEXES = ["state", "zip_code", "county"]
CHUNK_BYTES = 8 * 1024 * 1024

# Column order matches the CSV header / schema.ini (60 columns).
COLUMNS = [
    ("oid_", "bigint"),
    ("addnum_pre", "text"),
    ("add_number", "bigint"),
    ("addnum_suf", "text"),
    ("addno_full", "text"),
    ("st_premod", "text"),
    ("st_predir", "text"),
    ("st_pretyp", "text"),
    ("st_presep", "text"),
    ("st_name", "text"),
    ("st_postyp", "text"),
    ("st_posdir", "text"),
    ("st_posmod", "text"),
    ("stnam_full", "text"),
    ("building", "text"),
    ("floor", "text"),
    ("unit", "text"),
    ("room", "text"),
    ("seat", "text"),
    ("addtl_loc", "text"),
    ("subaddress", "text"),
    ("landmkname", "text"),
    ("county", "text"),
    ("inc_muni", "text"),
    ("post_city", "text"),
    ("census_plc", "text"),
    ("uninc_comm", "text"),
    ("nbrhd_comm", "text"),
    ("natamarea", "text"),
    ("natamsub", "text"),
    ("urbnztn_pr", "text"),
    ("placeother", "text"),
    ("placenmtyp", "text"),
    ("state", "text"),
    ("zip_code", "text"),
    ("plus_4", "text"),
    ("uuid", "text"),
    ("addauth", "text"),
    ("addrrefsys", "text"),
    ("longitude", "double precision"),
    ("latitude", "double precision"),
    ("natgrid", "text"),
    ("elevation", "real"),
    ("placement", "text"),
    ("addrpoint", "text"),
    ("related_id", "text"),
    ("relatetype", "text"),
    ("parcelsrc", "text"),
    ("parcel_id", "text"),
    ("addrclass", "text"),
    ("lifecycle", "text"),
    ("effective", "timestamp"),
    ("expire", "timestamp"),
    ("dateupdate", "timestamp"),
    ("anomstatus", "text"),
    ("locatndesc", "text"),
    ("addr_type", "text"),
    ("delivertyp", "text"),
    ("nad_source", "text"),
    ("dataset_id", "text"),
]


def psql(database, sql, capture=False):
    """Run a SQL statement via psql inside the container."""
    cmd = [
        "docker", "exec", CONTAINER,
        "psql", "-U", "postgres", "-d", database,
        "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A",
        "-c", sql,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"psql failed:\n{result.stderr.strip()}\nSQL: {sql}")
    return result.stdout.strip() if capture else None


def database_exists(name):
    out = psql("postgres",
               f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
               capture=True)
    return out == "1"


def create_database(name):
    if database_exists(name):
        print(f"Database '{name}' already exists.")
    else:
        psql("postgres", f'CREATE DATABASE "{name}"')
        print(f"Created database '{name}'.")


def drop_database(name):
    if not database_exists(name):
        print(f"Database '{name}' does not exist.")
        return
    psql("postgres", f'DROP DATABASE "{name}" WITH (FORCE)')
    print(f"Dropped database '{name}'.")


def create_table(database, table):
    cols = ",\n  ".join(f"{name} {sqltype}" for name, sqltype in COLUMNS)
    psql(database, f"CREATE TABLE IF NOT EXISTS {table} (\n  {cols}\n)")
    print(f"Table '{table}' is ready ({len(COLUMNS)} columns).")


def drop_table(database, table):
    if not database_exists(database):
        print(f"Database '{database}' does not exist; nothing to drop.")
        return
    psql(database, f"DROP TABLE IF EXISTS {table}")
    print(f"Dropped table '{table}' from database '{database}'.")


def find_data_files():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "**", "*.txt"),
                             recursive=True))
    if not files:
        sys.exit(f"No .txt data files found under {DATA_DIR}")
    return files


def copy_file(database, table, path, limit=None):
    """Stream one CSV file into the table with COPY FROM STDIN."""
    size = os.path.getsize(path)
    print(f"\nLoading {os.path.basename(path)} "
          f"({size / 1e9:.1f} GB){f', first {limit:,} rows' if limit else ''}")

    # With -c, COPY FROM STDIN reads psql's stdin as pure CSV until EOF,
    # so the pipe carries only data — no end-of-data marker needed.
    columns = ", ".join(name for name, _ in COLUMNS)
    proc = subprocess.Popen(
        ["docker", "exec", "-i", CONTAINER,
         "psql", "-U", "postgres", "-d", database,
         "-v", "ON_ERROR_STOP=1", "-q",
         "-c", "SET datestyle TO 'ISO, MDY'",
         "-c", f"COPY {table} ({columns}) FROM STDIN "
               "WITH (FORMAT csv, HEADER true, NULL '')"],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    sent_bytes = 0
    rows = 0
    start = time.monotonic()
    last_report = start
    try:
        with open(path, "rb") as f:
            if limit is not None:
                # Header + N data rows. (Assumes no newlines inside quoted
                # fields, which holds for this dataset.)
                for i, line in enumerate(f):
                    if i > limit:
                        break
                    proc.stdin.write(line)
                    sent_bytes += len(line)
                    rows = i  # header excluded
            else:
                while True:
                    chunk = f.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    proc.stdin.write(chunk)
                    sent_bytes += len(chunk)
                    rows += chunk.count(b"\n")
                    now = time.monotonic()
                    if now - last_report >= 5:
                        pct = 100 * sent_bytes / size
                        rate = sent_bytes / 1e6 / (now - start)
                        print(f"  {sent_bytes / 1e9:6.1f} GB sent "
                              f"({pct:5.1f}%), ~{rows:,} rows, "
                              f"{rate:.0f} MB/s", flush=True)
                        last_report = now
                rows -= 1  # header line
        proc.stdin.close()
    except BrokenPipeError:
        pass  # psql died; the returncode check below reports the error
    stderr = proc.stderr.read().decode()
    proc.wait()
    if proc.returncode != 0:
        sys.exit(f"COPY failed (nothing from this file was committed):\n"
                 f"{stderr.strip()}")
    elapsed = time.monotonic() - start
    print(f"  Done: ~{rows:,} rows in {elapsed / 60:.1f} min.")


def build_indexes(database, table, columns):
    for col in columns:
        name = f"idx_{table}_{col}"
        print(f"Creating index on {col}...", flush=True)
        psql(database, f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})")
    psql(database, f"ANALYZE {table}")


def row_count(database, table):
    return int(psql(database, f"SELECT count(*) FROM {table}", capture=True))


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-load NAD address data into PostgreSQL.")
    parser.add_argument("--database", default=DEFAULT_DB,
                        help=f"target database (default: {DEFAULT_DB})")
    parser.add_argument("--table", default=DEFAULT_TABLE,
                        help=f"target table (default: {DEFAULT_TABLE})")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="load only the first N rows of each file")
    parser.add_argument("--recreate", action="store_true",
                        help="drop the table first, then load")
    parser.add_argument("--append", action="store_true",
                        help="allow loading into a table that already has rows")
    parser.add_argument("--no-index", action="store_true",
                        help="skip index creation after a full load")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--drop-table", action="store_true",
                       help="drop the table and exit")
    group.add_argument("--drop-database", action="store_true",
                       help="drop the entire database and exit")
    group.add_argument("--count", action="store_true",
                       help="print the table row count and exit")
    args = parser.parse_args()

    state = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", CONTAINER],
        capture_output=True, text=True)
    if state.returncode != 0 or state.stdout.strip() != "running":
        sys.exit(f"Container '{CONTAINER}' is not running. "
                 f"Start it with: python3 {SCRIPT_DIR}/start_postgres.py")

    if args.drop_table:
        drop_table(args.database, args.table)
        return
    if args.drop_database:
        drop_database(args.database)
        return
    if args.count:
        print(f"{row_count(args.database, args.table):,} rows "
              f"in {args.database}.{args.table}")
        return

    files = find_data_files()
    print(f"Found {len(files)} data file(s) under {DATA_DIR}:")
    for f in files:
        print(f"  {os.path.relpath(f, DATA_DIR)}")

    create_database(args.database)
    if args.recreate:
        drop_table(args.database, args.table)
    create_table(args.database, args.table)

    existing = row_count(args.database, args.table)
    if existing and not args.append:
        sys.exit(f"Table '{args.table}' already has {existing:,} rows; loading "
                 f"again would duplicate them.\nRerun with --recreate to "
                 f"replace the data, or --append to add to it.")

    for path in files:
        copy_file(args.database, args.table, path, limit=args.limit)

    if not args.limit and not args.no_index:
        build_indexes(args.database, args.table, DEFAULT_INDEXES)

    total = row_count(args.database, args.table)
    print(f"\nLoad complete: {total:,} rows in {args.database}.{args.table}")
    print(f"Connect with: psql -h localhost -p 5433 -U postgres "
          f"-d {args.database}")


if __name__ == "__main__":
    main()
