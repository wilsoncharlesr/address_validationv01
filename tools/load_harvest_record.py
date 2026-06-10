#!/usr/bin/env python3
"""
Bulk-load the data.gov harvest record into a fresh SQLite database.

Each time this script runs it:
  1. Creates a brand-new SQLite database file (timestamped).
  2. Creates a fresh table inside it.
  3. Downloads the JSON data from the data.gov harvest_record raw endpoint.
  4. Flattens each record and bulk-inserts it into the table.

The source endpoint returns a single DCAT dataset metadata record, but the
loader also handles a JSON array of records, so it works if the endpoint ever
returns multiple rows.
"""

import json
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime

SOURCE_URL = (
    "https://catalog.data.gov/harvest_record/"
    "a8e0eb0e-ae70-41cb-b732-903cd4050568/raw"
)
TABLE_NAME = "harvest_record"
HERE = os.path.dirname(os.path.abspath(__file__))


def fetch_data(url: str):
    """Download and parse the JSON payload from the source URL."""
    print(f"Fetching data from {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "harvest-loader/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    # Normalize to a list of record dicts.
    if isinstance(data, dict):
        # Some catalog payloads nest records under a "dataset" key.
        if "dataset" in data and isinstance(data["dataset"], list):
            records = data["dataset"]
        else:
            records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise ValueError(f"Unexpected JSON top-level type: {type(data).__name__}")

    print(f"Parsed {len(records)} record(s) from source")
    return records


def flatten(record: dict, parent_key: str = "", sep: str = "_") -> dict:
    """Flatten nested dicts into a single level; JSON-encode lists/leftovers."""
    flat = {}
    for key, value in record.items():
        key = key.lstrip("@").replace(":", "_")
        col = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            flat.update(flatten(value, col, sep))
        elif isinstance(value, (list, tuple)):
            flat[col] = json.dumps(value, ensure_ascii=False)
        else:
            flat[col] = value
    return flat


def create_database():
    """Create a brand-new timestamped SQLite database file."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_path = os.path.join(HERE, f"harvest_{stamp}.db")
    # Guarantee a fresh file even on a rare same-second rerun.
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    print(f"Created new database: {db_path}")
    return conn, db_path


def create_table(conn, columns):
    """Create a fresh table with one TEXT column per flattened field."""
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
    cur.execute(
        f'CREATE TABLE {TABLE_NAME} '
        f'(id INTEGER PRIMARY KEY AUTOINCREMENT, {col_defs})'
    )
    conn.commit()
    print(f"Created table '{TABLE_NAME}' with {len(columns)} data column(s)")


def load_records(conn, records, columns):
    """Bulk-insert all flattened records into the table."""
    cur = conn.cursor()
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(f'"{c}"' for c in columns)
    rows = [
        tuple(
            v if not isinstance(v := flat.get(c), (dict, list)) else json.dumps(v)
            for c in columns
        )
        for flat in (flatten(r) for r in records)
    ]
    cur.executemany(
        f'INSERT INTO {TABLE_NAME} ({col_list}) VALUES ({placeholders})', rows
    )
    conn.commit()
    print(f"Inserted {cur.rowcount if cur.rowcount != -1 else len(rows)} row(s)")


def main():
    try:
        records = fetch_data(SOURCE_URL)
    except Exception as exc:
        print(f"ERROR fetching data: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No records returned from source; nothing to load.", file=sys.stderr)
        return 1

    # Union of all keys across records, preserving first-seen order.
    columns = []
    seen = set()
    for rec in records:
        for col in flatten(rec):
            if col not in seen:
                seen.add(col)
                columns.append(col)

    conn, db_path = create_database()
    try:
        create_table(conn, columns)
        load_records(conn, records, columns)
        count = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        print(f"Done. {count} row(s) in '{TABLE_NAME}' at {db_path}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
