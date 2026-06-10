#!/usr/bin/env python3
"""
Show details of the address-verification PostgreSQL database and its tables,
and export a record sample from each table to CSV.

Reports server version, database size, and for every table: row count, table
and index sizes, column definitions, and indexes. Then writes a random sample
(default 1,000 records) per table to ``<table>_sample.csv`` in the current
directory and prints a short preview.

Requires the container from start_postgres.py; no Python packages needed.

USAGE
  python3 describe_database.py                      # all tables, 1000-row samples
  python3 describe_database.py --table il_addresses # one table only
  python3 describe_database.py --sample 50          # smaller sample
  python3 describe_database.py --first              # first N rows, not random
  python3 describe_database.py --no-sample          # details only, no CSV
"""

import argparse
import os
import subprocess
import sys

from load_nad_postgres import CONTAINER, DEFAULT_DB, SCRIPT_DIR, database_exists, psql

DEFAULT_SAMPLE = 1000


def psql_pretty(database, command):
    """Run a statement via psql and return its aligned, human-readable output."""
    result = subprocess.run(
        ["docker", "exec", CONTAINER,
         "psql", "-U", "postgres", "-d", database,
         "-v", "ON_ERROR_STOP=1", "-c", command],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"psql failed:\n{result.stderr.strip()}\nCommand: {command}")
    return result.stdout.rstrip()


def heading(text):
    print(f"\n{text}\n{'=' * len(text)}")


def list_tables(database):
    out = psql(database,
               "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
               "ORDER BY tablename", capture=True)
    return [line for line in out.splitlines() if line]


def show_database_details(database):
    heading(f"Database: {database}")
    print(psql_pretty(database, """
        SELECT current_database() AS database,
               pg_size_pretty(pg_database_size(current_database())) AS size,
               pg_encoding_to_char(encoding) AS encoding,
               current_setting('server_version') AS postgres_version
        FROM pg_database WHERE datname = current_database()
    """))


def show_table_overview(database, tables):
    heading("Tables")
    table_list = ", ".join(f"'{t}'" for t in tables)
    print(psql_pretty(database, f"""
        SELECT c.relname AS table,
               to_char(c.reltuples::bigint, 'FM999,999,999') AS est_rows,
               pg_size_pretty(pg_table_size(c.oid)) AS table_size,
               pg_size_pretty(pg_indexes_size(c.oid)) AS index_size,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname IN ({table_list})
        ORDER BY c.relname
    """))


def show_table_details(database, table):
    heading(f"Table: {table}")
    exact = int(psql(database, f"SELECT count(*) FROM {table}", capture=True))
    print(f"Exact row count: {exact:,}")
    print(psql_pretty(database, f"\\d {table}"))
    return exact


def export_sample(database, table, n, first, out_path):
    order = "" if first else " ORDER BY random()"
    sql = (f"COPY (SELECT * FROM {table}{order} LIMIT {n}) "
           "TO STDOUT WITH (FORMAT csv, HEADER true)")
    with open(out_path, "wb") as out:
        result = subprocess.run(
            ["docker", "exec", CONTAINER,
             "psql", "-U", "postgres", "-d", database,
             "-v", "ON_ERROR_STOP=1", "-q", "-c", sql],
            stdout=out, stderr=subprocess.PIPE,
        )
    if result.returncode != 0:
        sys.exit(f"Sample export failed:\n{result.stderr.decode().strip()}")
    with open(out_path) as f:
        lines = sum(1 for _ in f) - 1
    print(f"\nSample: {lines:,} {'first' if first else 'random'} records "
          f"-> {out_path}")
    with open(out_path) as f:
        for i, line in enumerate(f):
            if i > 3:
                break
            print(f"  {line.rstrip()[:160]}")


def main():
    parser = argparse.ArgumentParser(
        description="Describe the PostgreSQL database and sample its tables.")
    parser.add_argument("--database", default=DEFAULT_DB,
                        help=f"database to inspect (default: {DEFAULT_DB})")
    parser.add_argument("--table",
                        help="inspect only this table (default: all tables)")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        metavar="N",
                        help=f"records per sample (default: {DEFAULT_SAMPLE})")
    parser.add_argument("--first", action="store_true",
                        help="take the first N rows instead of a random sample")
    parser.add_argument("--no-sample", action="store_true",
                        help="show details only, skip the CSV export")
    parser.add_argument("--output-dir", default=".",
                        help="directory for sample CSV files (default: cwd)")
    args = parser.parse_args()

    state = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", CONTAINER],
        capture_output=True, text=True)
    if state.returncode != 0 or state.stdout.strip() != "running":
        sys.exit(f"Container '{CONTAINER}' is not running. "
                 f"Start it with: python3 {SCRIPT_DIR}/start_postgres.py")

    if not database_exists(args.database):
        sys.exit(f"Database '{args.database}' does not exist.")

    tables = list_tables(args.database)
    if args.table:
        if args.table not in tables:
            sys.exit(f"Table '{args.table}' not found in '{args.database}'. "
                     f"Available: {', '.join(tables) or '(none)'}")
        tables = [args.table]
    if not tables:
        sys.exit(f"No tables found in database '{args.database}'.")

    show_database_details(args.database)
    show_table_overview(args.database, tables)

    for table in tables:
        rows = show_table_details(args.database, table)
        if args.no_sample:
            continue
        n = min(args.sample, rows)
        if n == 0:
            print("\nTable is empty; no sample written.")
            continue
        out_path = os.path.join(args.output_dir, f"{table}_sample.csv")
        export_sample(args.database, table, n, args.first, out_path)


if __name__ == "__main__":
    main()
