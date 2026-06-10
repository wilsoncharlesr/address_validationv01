#!/usr/bin/env python3
"""
Load the actual National Address Database (NAD) address points into SQLite,
with a resumable/checkpointed download for the full run.

The data.gov harvest record points to an ~8.45 GB ZIP whose main entry,
``TXT/NAD_r22.txt``, is a ~40.7 GB comma-delimited CSV of address points
(60 columns, header row, UTF-8 BOM, ~74M rows).

Two modes
---------
Default (full run):
    1. Resumably download the ZIP to a local cache (HTTP range requests; an
       interrupted download continues from where it stopped on the next run).
    2. Stream the CSV out of the local ZIP (constant memory).
    3. Bulk-insert into a `nad_addresses` table, checkpointing row progress so a
       killed *load* can resume without re-inserting rows already committed.
    4. Build useful indexes (State, Zip_Code, County by default) after loading.

Streaming (no disk, great for testing):
    --stream reads the CSV directly over HTTP without saving the 8.45 GB ZIP.
    Pair with --limit for a fast sample.

USAGE
  python3 load_nad_data.py --stream --limit 5000     # quick sample, no download
  python3 load_nad_data.py                           # full resumable run
  python3 load_nad_data.py --resume                  # continue an interrupted run
  python3 load_nad_data.py --index "State,Zip_Code,County,Inc_Muni"
"""

import argparse
import codecs
import csv
import io
import os
import re
import sqlite3
import struct
import sys
import urllib.request
import zipfile
import zlib
from datetime import datetime

SOURCE_URL = (
    "https://data.transportation.gov/download/fc2s-wawr/"
    "application/x-zip-compressed"
)
ENTRY_PATTERN = r"NAD.*\.txt$"          # main address CSV inside the zip
TABLE_NAME = "nad_addresses"
DEFAULT_INDEXES = ["State", "Zip_Code", "County"]
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "nad_cache")
HTTP_CHUNK = 1 << 20                     # 1 MiB network reads
FLUSH_EVERY = 64 << 20                   # flush download to disk every 64 MiB

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


# --------------------------------------------------------------------------- #
# HTTP range helpers
# --------------------------------------------------------------------------- #
def _open_range(url, start, end=None):
    """Open an HTTP response for byte range [start, end] (end inclusive)."""
    rng = f"bytes={start}-" + ("" if end is None else str(end))
    req = urllib.request.Request(
        url, headers={"Range": rng, "User-Agent": "nad-loader/1.0"}
    )
    return urllib.request.urlopen(req, timeout=120)


def fetch_range(url, start, length):
    with _open_range(url, start, start + length - 1) as resp:
        return resp.read()


def total_size(url):
    with _open_range(url, 0, 0) as resp:
        cr = resp.headers.get("Content-Range", "")
        if "/" in cr:
            return int(cr.split("/")[-1])
        cl = resp.headers.get("Content-Length")
        if cl:
            return int(cl)
    raise RuntimeError("Server did not report file size / range support")


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


# --------------------------------------------------------------------------- #
# Resumable download
# --------------------------------------------------------------------------- #
def download_archive(url, path, size):
    """Download `url` to `path` resumably. Returns path once fully present."""
    if os.path.exists(path) and os.path.getsize(path) == size:
        print(f"Archive already downloaded: {path} ({_fmt_bytes(size)})")
        return path

    part = path + ".part"
    existing = os.path.getsize(part) if os.path.exists(part) else 0
    if existing > size:                 # corrupt/oversized -> start over
        existing = 0
    if existing == size:                # complete under .part name
        os.replace(part, path)
        return path

    if existing:
        print(f"Resuming download at {_fmt_bytes(existing)} / {_fmt_bytes(size)}")
    else:
        print(f"Downloading {_fmt_bytes(size)} -> {path}")

    resp = _open_range(url, existing)
    # If the server ignored Range (200 instead of 206), restart from scratch.
    if existing and getattr(resp, "status", 206) != 206:
        print("  server ignored Range; restarting download from 0")
        existing = 0
        resp.close()
        resp = _open_range(url, 0)

    downloaded = existing
    since_flush = 0
    next_pct = 0
    mode = "ab" if existing else "wb"
    try:
        with open(part, mode) as f:
            while True:
                chunk = resp.read(HTTP_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                since_flush += len(chunk)
                if since_flush >= FLUSH_EVERY:
                    f.flush()
                    os.fsync(f.fileno())
                    since_flush = 0
                pct = downloaded * 100 // size
                if pct >= next_pct:
                    print(f"  {pct:3d}%  {_fmt_bytes(downloaded)} / {_fmt_bytes(size)}")
                    next_pct = pct + 5
    except Exception as exc:
        print(f"  download interrupted at {_fmt_bytes(downloaded)} "
              f"({exc}); rerun to resume.", file=sys.stderr)
        raise
    finally:
        resp.close()

    actual = os.path.getsize(part)
    if actual != size:
        raise RuntimeError(
            f"Incomplete download ({_fmt_bytes(actual)} of {_fmt_bytes(size)}); "
            f"rerun to resume."
        )
    os.replace(part, path)
    print(f"Download complete: {path}")
    return path


# --------------------------------------------------------------------------- #
# ZIP central directory parsing (ZIP64-aware) for the --stream path
# --------------------------------------------------------------------------- #
def locate_central_directory(url, size):
    tail_len = min(65557, size)
    tail = fetch_range(url, size - tail_len, tail_len)
    p = tail.rfind(b"PK\x05\x06")
    if p < 0:
        raise RuntimeError("End-of-central-directory record not found")
    cd_size, cd_off = struct.unpack("<II", tail[p + 12 : p + 20])
    if cd_off == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        l = tail.rfind(b"PK\x06\x07")
        if l < 0:
            raise RuntimeError("ZIP64 EOCD locator not found")
        z64_off = struct.unpack("<Q", tail[l + 8 : l + 16])[0]
        z64 = fetch_range(url, z64_off, 56)
        if z64[:4] != b"PK\x06\x06":
            raise RuntimeError("ZIP64 EOCD record signature mismatch")
        cd_size = struct.unpack("<Q", z64[40:48])[0]
        cd_off = struct.unpack("<Q", z64[48:56])[0]
    return cd_off, cd_size


def parse_central_directory(cd_bytes):
    i = 0
    while True:
        j = cd_bytes.find(b"PK\x01\x02", i)
        if j < 0:
            break
        flag, method = struct.unpack("<HH", cd_bytes[j + 8 : j + 12])
        csize, usize = struct.unpack("<II", cd_bytes[j + 20 : j + 28])
        n, m, k = struct.unpack("<HHH", cd_bytes[j + 28 : j + 34])
        lho = struct.unpack("<I", cd_bytes[j + 42 : j + 46])[0]
        name = cd_bytes[j + 46 : j + 46 + n].decode("utf-8", "replace")
        extra = cd_bytes[j + 46 + n : j + 46 + n + m]
        e = 0
        while e + 4 <= len(extra):
            hid, hsz = struct.unpack("<HH", extra[e : e + 4])
            body = extra[e + 4 : e + 4 + hsz]
            if hid == 0x0001:
                b = 0
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack("<Q", body[b : b + 8])[0]; b += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack("<Q", body[b : b + 8])[0]; b += 8
                if lho == 0xFFFFFFFF:
                    lho = struct.unpack("<Q", body[b : b + 8])[0]; b += 8
            e += 4 + hsz
        yield {"name": name, "method": method, "flag": flag,
               "csize": csize, "usize": usize, "local_offset": lho}
        i = j + 4


def _data_offset(url, local_offset):
    hdr = fetch_range(url, local_offset, 30)
    if hdr[:4] != b"PK\x03\x04":
        raise RuntimeError("Local file header signature mismatch")
    n, m = struct.unpack("<HH", hdr[26:30])
    return local_offset + 30 + n + m


def http_stream_lines(url, entry):
    """Yield decoded text lines from a zip entry, streamed + inflated over HTTP."""
    off = _data_offset(url, entry["local_offset"])
    decomp = zlib.decompressobj(-15)
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    remaining = entry["csize"]
    buf = ""
    with _open_range(url, off, off + entry["csize"] - 1) as resp:
        while remaining > 0:
            chunk = resp.read(min(HTTP_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            data = decomp.decompress(chunk)
            if not data:
                continue
            buf += decoder.decode(data)
            start = 0
            nl = buf.find("\n", start)
            while nl != -1:
                yield buf[start : nl + 1]
                start = nl + 1
                nl = buf.find("\n", start)
            buf = buf[start:]
    tail = decomp.flush()
    if tail:
        buf += decoder.decode(tail, final=True)
    if buf:
        yield buf


# --------------------------------------------------------------------------- #
# schema.ini -> SQLite column types
# --------------------------------------------------------------------------- #
def parse_schema_ini(text):
    type_map = {}
    for line in text.splitlines():
        mt = re.match(r"\s*Col\d+\s*=\s*(.+)", line, re.I)
        if not mt:
            continue
        spec = mt.group(1).strip()
        name = spec.split()[0].strip('"')
        rest = spec[len(spec.split()[0]):].strip().lower()
        if rest.startswith(("long", "short", "integer", "byte")):
            type_map[name] = "INTEGER"
        elif rest.startswith(("double", "single", "float")):
            type_map[name] = "REAL"
        else:
            type_map[name] = "TEXT"
    return type_map


def safe_col(name):
    c = re.sub(r"[^0-9A-Za-z_]", "_", name).strip("_")
    if not c:
        c = "col"
    if c[0].isdigit():
        c = "_" + c
    return c


# --------------------------------------------------------------------------- #
# Database setup, checkpointing, loading, indexing
# --------------------------------------------------------------------------- #
def connect(db_path, tuned=True):
    conn = sqlite3.connect(db_path)
    if tuned:
        conn.execute("PRAGMA journal_mode=WAL")     # durable + resumable
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")   # ~200 MB page cache
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM _load_meta WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row else default


def meta_set(conn, key, value):
    conn.execute(
        "INSERT INTO _load_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def create_schema(conn, headers, type_map):
    cols = [safe_col(h) for h in headers]
    defs = ", ".join(f'"{c}" {type_map.get(orig, "TEXT")}'
                     for c, orig in zip(cols, headers))
    conn.execute("DROP TABLE IF EXISTS _load_meta")
    conn.execute("CREATE TABLE _load_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
    conn.execute(
        f"CREATE TABLE {TABLE_NAME} "
        f"(row_id INTEGER PRIMARY KEY AUTOINCREMENT, {defs})"
    )
    meta_set(conn, "rows_loaded", 0)
    meta_set(conn, "complete", 0)
    conn.commit()
    print(f"Created table '{TABLE_NAME}' with {len(cols)} data column(s)")
    return cols


def existing_columns(conn):
    info = conn.execute(f"PRAGMA table_info({TABLE_NAME})").fetchall()
    return [r[1] for r in info if r[1] != "row_id"]


def load(conn, cols, reader, batch_size, progress, limit, start_row):
    """Insert rows, skipping `start_row` already-committed rows; checkpoint."""
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(f'"{c}"' for c in cols)
    sql = f"INSERT INTO {TABLE_NAME} ({col_list}) VALUES ({placeholders})"
    ncols = len(cols)
    cur = conn.cursor()

    if start_row:
        print(f"Resuming: skipping {start_row:,} already-loaded rows...")
    skipped = 0
    for _ in range(start_row):           # fast-forward past committed rows
        if next(reader, None) is None:
            break
        skipped += 1

    batch = []
    loaded = 0
    for row in reader:
        if not row:
            continue
        if len(row) < ncols:
            row = row + [""] * (ncols - len(row))
        elif len(row) > ncols:
            row = row[:ncols]
        batch.append(tuple(v if v != "" else None for v in row))
        loaded += 1
        if len(batch) >= batch_size:
            cur.executemany(sql, batch)
            meta_set(conn, "rows_loaded", start_row + loaded)
            conn.commit()
            batch.clear()
        if progress and loaded % progress == 0:
            print(f"  ... {start_row + loaded:,} rows loaded")
        if limit and (start_row + loaded) >= limit:
            break
    if batch:
        cur.executemany(sql, batch)
        meta_set(conn, "rows_loaded", start_row + loaded)
        conn.commit()
    return start_row + loaded


def build_indexes(conn, cols, index_cols):
    valid = [c for c in index_cols if c in cols]
    missing = [c for c in index_cols if c not in cols]
    for c in missing:
        print(f"  (skipping index on unknown column '{c}')")
    for c in valid:
        name = f"idx_{TABLE_NAME}_{c.lower()}"
        print(f"  building index {name} ...")
        conn.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {TABLE_NAME} ("{c}")')
    conn.commit()
    if valid:
        print(f"Built {len(valid)} index(es): {', '.join(valid)}")


# --------------------------------------------------------------------------- #
# CSV sources
# --------------------------------------------------------------------------- #
def open_local_csv(zip_path, entry_pattern):
    """Open the CSV + schema from a local zip; return (reader, headers, types)."""
    zf = zipfile.ZipFile(zip_path)
    rx = re.compile(entry_pattern, re.I)
    name = next((n for n in zf.namelist() if rx.search(n)), None)
    if name is None:
        raise RuntimeError(f"No entry matched /{entry_pattern}/ in {zip_path}")
    print(f"Loading entry: {name}")
    type_map = {}
    schema_name = next((n for n in zf.namelist()
                        if n.lower().endswith("schema.ini")), None)
    if schema_name:
        type_map = parse_schema_ini(zf.read(schema_name).decode("latin1"))
        print(f"Applied column types from schema.ini ({len(type_map)} columns)")
    text = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    reader = csv.reader(text)
    headers = next(reader)
    return reader, headers, type_map


def open_http_csv(url, entry_pattern):
    """Open the CSV + schema by streaming over HTTP; return (reader, headers, types)."""
    size = total_size(url)
    print(f"Archive size: {size:,} bytes")
    cd_off, cd_size = locate_central_directory(url, size)
    entries = list(parse_central_directory(fetch_range(url, cd_off, cd_size)))
    rx = re.compile(entry_pattern, re.I)
    data_entry = next((e for e in entries if rx.search(e["name"])), None)
    if data_entry is None:
        raise RuntimeError(f"No entry matched /{entry_pattern}/")
    if data_entry["method"] not in (0, 8):
        raise RuntimeError(f"Unsupported compression method {data_entry['method']}")
    print(f"Loading entry: {data_entry['name']}")
    type_map = {}
    schema_entry = next((e for e in entries
                         if e["name"].lower().endswith("schema.ini")), None)
    if schema_entry:
        off = _data_offset(url, schema_entry["local_offset"])
        raw = fetch_range(url, off, schema_entry["csize"])
        body = raw if schema_entry["method"] == 0 else zlib.decompress(raw, -15)
        type_map = parse_schema_ini(body.decode("latin1"))
        print(f"Applied column types from schema.ini ({len(type_map)} columns)")
    reader = csv.reader(http_stream_lines(url, data_entry))
    headers = next(reader)
    return reader, headers, type_map


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="Load NAD address data into SQLite")
    ap.add_argument("--url", default=SOURCE_URL)
    ap.add_argument("--db", default=os.path.join(HERE, "nad.db"),
                    help="output SQLite path (default: tools/nad.db)")
    ap.add_argument("--zip", default=os.path.join(CACHE_DIR, "nad.zip"),
                    help="local cache path for the downloaded archive")
    ap.add_argument("--stream", action="store_true",
                    help="stream over HTTP without saving the 8.45 GB zip "
                         "(no resume; best with --limit)")
    ap.add_argument("--resume", action="store_true",
                    help="continue a previously interrupted load into --db")
    ap.add_argument("--limit", type=int, default=0, help="stop after N rows")
    ap.add_argument("--batch", type=int, default=20000, help="rows per transaction")
    ap.add_argument("--progress", type=int, default=250000)
    ap.add_argument("--entry", default=ENTRY_PATTERN, help="regex for CSV entry")
    ap.add_argument("--index", default=",".join(DEFAULT_INDEXES),
                    help="comma-separated columns to index (empty to skip)")
    ap.add_argument("--no-index", action="store_true", help="skip index creation")
    args = ap.parse_args(argv)

    print(f"Source: {args.url}")

    # --- obtain a CSV reader from the chosen source ---
    try:
        if args.stream:
            reader, headers, type_map = open_http_csv(args.url, args.entry)
        else:
            os.makedirs(CACHE_DIR, exist_ok=True)
            size = total_size(args.url)
            zip_path = download_archive(args.url, args.zip, size)
            reader, headers, type_map = open_local_csv(zip_path, args.entry)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # --- set up / open the database ---
    resuming = args.resume and os.path.exists(args.db)
    if resuming:
        conn = connect(args.db)
        cols = existing_columns(conn)
        if len(cols) != len(headers):
            print("ERROR: --resume target schema differs from source; "
                  "start a fresh run instead.", file=sys.stderr)
            return 1
        start_row = int(meta_get(conn, "rows_loaded", 0) or 0)
        if int(meta_get(conn, "complete", 0) or 0):
            print(f"Load already marked complete ({start_row:,} rows). Nothing to do.")
            conn.close()
            return 0
        print(f"Resuming load into {args.db} from row {start_row:,}")
    else:
        if os.path.exists(args.db):
            os.remove(args.db)
        for ext in ("-wal", "-shm"):
            if os.path.exists(args.db + ext):
                os.remove(args.db + ext)
        conn = connect(args.db)
        print(f"Created new database: {args.db}")
        cols = create_schema(conn, headers, type_map)
        start_row = 0

    # --- load ---
    print("Streaming rows..." + (f" (limit {args.limit:,})" if args.limit else ""))
    try:
        total = load(conn, cols, reader, args.batch, args.progress,
                     args.limit, start_row)
    except KeyboardInterrupt:
        committed = int(meta_get(conn, "rows_loaded", 0) or 0)
        conn.commit()
        conn.close()
        print(f"\nInterrupted. {committed:,} rows committed. "
              f"Rerun with --resume to continue.", file=sys.stderr)
        return 130

    meta_set(conn, "complete", 1)
    conn.commit()

    # --- indexes ---
    index_cols = [c.strip() for c in args.index.split(",") if c.strip()]
    if not args.no_index and index_cols:
        print("Building indexes...")
        build_indexes(conn, cols, index_cols)

    count = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    print(f"Done. {total:,} rows processed; {count:,} present in '{TABLE_NAME}'.")
    print(f"Database: {args.db}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
