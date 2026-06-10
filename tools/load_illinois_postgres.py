#!/usr/bin/env python3
"""
Load only the Illinois (State = 'IL') rows from the NAD data into PostgreSQL.

Scans the NAD CSV files under ``data/TXT``, keeps rows whose State column is
``IL``, and bulk-loads them into their own table (default ``il_addresses``,
same 60-column schema as the full loader). The NAD file is sorted by state, so
by default the scan stops shortly after the Illinois block ends instead of
reading the whole 40 GB file (disable with --no-early-stop).

Requires the container from start_postgres.py; no Python packages needed.

USAGE
  python3 load_illinois_postgres.py               # load all IL rows
  python3 load_illinois_postgres.py --limit 5000  # quick sample
  python3 load_illinois_postgres.py --recreate    # drop table, then load
  python3 load_illinois_postgres.py --drop-table  # drop the IL table
  python3 load_illinois_postgres.py --count       # row count
"""

import argparse
import csv
import io
import os
import subprocess
import sys
import time

from load_nad_postgres import (
    COLUMNS,
    CONTAINER,
    DATA_DIR,
    DEFAULT_DB,
    SCRIPT_DIR,
    build_indexes,
    create_database,
    create_table,
    drop_table,
    find_data_files,
    row_count,
)

DEFAULT_TABLE = "il_addresses"
IL_INDEXES = ["zip_code", "county", "post_city"]
STATE = "IL"
STATE_COL = [name for name, _ in COLUMNS].index("state")  # column 34
PREFILTER = f",{STATE},".encode()
# Rows in the file are grouped by state; after this many consecutive
# non-matching lines following the IL block, assume the block is over.
EARLY_STOP_LINES = 200_000


def copy_illinois(database, table, path, limit=None, early_stop=True):
    size = os.path.getsize(path)
    print(f"\nScanning {os.path.basename(path)} ({size / 1e9:.1f} GB) "
          f"for {STATE} rows{f', first {limit:,}' if limit else ''}")

    columns = ", ".join(name for name, _ in COLUMNS)
    proc = subprocess.Popen(
        ["docker", "exec", "-i", CONTAINER,
         "psql", "-U", "postgres", "-d", database,
         "-v", "ON_ERROR_STOP=1", "-q",
         "-c", "SET datestyle TO 'ISO, MDY'",
         "-c", f"COPY {table} ({columns}) FROM STDIN "
               "WITH (FORMAT csv, NULL '')"],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out = io.TextIOWrapper(proc.stdin, encoding="utf-8", newline="")
    writer = csv.writer(out)

    scanned_bytes = 0
    il_rows = 0
    misses_since_il = 0
    start = time.monotonic()
    last_report = start
    stopped_early = False
    try:
        with open(path, "rb") as f:
            f.readline()  # header
            for raw in f:
                scanned_bytes += len(raw)
                matched = False
                # Cheap reject: an unquoted IL state always appears as ",IL,".
                if PREFILTER in raw:
                    row = next(csv.reader([raw.decode("utf-8")]))
                    if len(row) == len(COLUMNS) and row[STATE_COL] == STATE:
                        writer.writerow(row)
                        il_rows += 1
                        matched = True
                        if limit and il_rows >= limit:
                            break
                if matched:
                    misses_since_il = 0
                elif il_rows:
                    misses_since_il += 1
                    if early_stop and misses_since_il >= EARLY_STOP_LINES:
                        stopped_early = True
                        break
                now = time.monotonic()
                if now - last_report >= 5:
                    pct = 100 * scanned_bytes / size
                    print(f"  {scanned_bytes / 1e9:6.1f} GB scanned "
                          f"({pct:5.1f}%), {il_rows:,} {STATE} rows",
                          flush=True)
                    last_report = now
        out.close()
    except BrokenPipeError:
        pass  # psql died; the returncode check below reports the error
    stderr = proc.stderr.read().decode()
    proc.wait()
    if proc.returncode != 0:
        sys.exit(f"COPY failed (nothing from this file was committed):\n"
                 f"{stderr.strip()}")
    elapsed = time.monotonic() - start
    why = (" (stopped after the IL block)" if stopped_early
           else f" (reached row limit)" if limit and il_rows >= limit else "")
    print(f"  Done: {il_rows:,} {STATE} rows from "
          f"{scanned_bytes / 1e9:.1f} GB in {elapsed / 60:.1f} min{why}.")
    return il_rows


def main():
    parser = argparse.ArgumentParser(
        description="Load only Illinois NAD address rows into PostgreSQL.")
    parser.add_argument("--database", default=DEFAULT_DB,
                        help=f"target database (default: {DEFAULT_DB})")
    parser.add_argument("--table", default=DEFAULT_TABLE,
                        help=f"target table (default: {DEFAULT_TABLE})")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="load only the first N Illinois rows")
    parser.add_argument("--recreate", action="store_true",
                        help="drop the table first, then load")
    parser.add_argument("--append", action="store_true",
                        help="allow loading into a table that already has rows")
    parser.add_argument("--no-index", action="store_true",
                        help="skip index creation after the load")
    parser.add_argument("--no-early-stop", action="store_true",
                        help="scan every file to the end instead of stopping "
                             "after the Illinois block")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--drop-table", action="store_true",
                       help="drop the Illinois table and exit")
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
        copy_illinois(args.database, args.table, path,
                      limit=args.limit, early_stop=not args.no_early_stop)

    if not args.limit and not args.no_index:
        build_indexes(args.database, args.table, IL_INDEXES)

    total = row_count(args.database, args.table)
    print(f"\nLoad complete: {total:,} {STATE} rows "
          f"in {args.database}.{args.table}")
    print(f"Connect with: psql -h localhost -p 5433 -U postgres "
          f"-d {args.database}")


if __name__ == "__main__":
    main()
