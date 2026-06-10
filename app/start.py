#!/usr/bin/env python3
"""
One command to bring up the whole address-verification stack.

Pipeline:
  1. Make sure Docker is running.
  2. Make sure the PostgreSQL container is up (reuses tools/start_postgres.py,
     so the existing ~4.86M-row `il_addresses` data is never recreated).
  3. Initialize the databases (idempotent):
       - nad:     pg_trgm + the trigram search index  (first build takes a few minutes)
       - nad_sub: created if missing, plus the submissions table
  4. terraform init + apply  -> builds and runs the C# API and nginx web containers.
  5. Wait for the API and web to answer, then print the URLs.

USAGE
  python3 start.py            # bring everything up
  python3 start.py --open     # ... and open the web UI in a browser
  python3 start.py --status   # show container status and the URLs
  python3 start.py --down     # terraform destroy (stops API + web; keeps PostgreSQL)
  python3 start.py --skip-index   # skip the (slow, one-time) trigram index build
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)
TOOLS_DIR = os.path.join(REPO_DIR, "tools")
DB_DIR = os.path.join(APP_DIR, "db")
TF_DIR = os.path.join(APP_DIR, "terraform")

PG_CONTAINER = "address-verification-pg"
NAD_DB = "nad"
NADSUB_DB = "nad_sub"
NAD_TABLE = "il_addresses"

WEB_PORT = 8088
API_PORT = 8081


# ----------------------------------------------------------------------------- helpers
def run(cmd, cwd=None, check=True, capture=False, env=None):
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=capture,
                          text=True, env=env)


def docker_available():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def container_state(name):
    r = subprocess.run(["docker", "inspect", "--format", "{{.State.Status}}", name],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def psql_capture(database, sql):
    r = subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", database,
         "-t", "-A", "-c", sql],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"psql failed on {database}:\n{r.stderr.strip()}")
    return r.stdout.strip()


def psql_file(database, path):
    with open(path, "r", encoding="utf-8") as f:
        sql = f.read()
    r = subprocess.run(
        ["docker", "exec", "-i", PG_CONTAINER, "psql", "-U", "postgres",
         "-d", database, "-v", "ON_ERROR_STOP=1", "-q"],
        input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"Running {os.path.basename(path)} on {database} failed:\n{r.stderr.strip()}")


def http_ok(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, ConnectionError, OSError):
        return False


def wait_for(url, label, timeout=180):
    print(f"Waiting for {label} ({url}) ", end="", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_ok(url):
            print(" ready.")
            return True
        print(".", end="", flush=True)
        time.sleep(2)
    print(f"\n  {label} did not respond within {timeout}s.")
    return False


# ----------------------------------------------------------------------------- steps
def ensure_postgres():
    state = container_state(PG_CONTAINER)
    if state == "running":
        print(f"PostgreSQL container '{PG_CONTAINER}' is running.")
    else:
        print(f"PostgreSQL container not running ({state}); starting it...")
        run([sys.executable, os.path.join(TOOLS_DIR, "start_postgres.py")])

    # Sanity-check the reference data.
    try:
        count = int(psql_capture(NAD_DB, f"SELECT count(*) FROM {NAD_TABLE}"))
        print(f"  {NAD_TABLE}: {count:,} rows.")
        if count == 0:
            print(f"  WARNING: {NAD_TABLE} is empty. Load data with "
                  f"tools/load_illinois_postgres.py before verifying addresses.")
    except SystemExit:
        print(f"  WARNING: table {NAD_TABLE} not found in '{NAD_DB}'. Load it with "
              f"tools/load_illinois_postgres.py.")


def init_databases(skip_index=False):
    print("\nInitializing databases...")

    if skip_index:
        print("  Skipping trigram index build (--skip-index); creating pg_trgm only.")
        subprocess.run(
            ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres",
             "-d", NAD_DB, "-c", "CREATE EXTENSION IF NOT EXISTS pg_trgm"],
            check=True, capture_output=True, text=True)
    else:
        print(f"  {NAD_DB}: pg_trgm + trigram index "
              f"(first run on ~5M rows can take a few minutes)...")
        psql_file(NAD_DB, os.path.join(DB_DIR, "01_init_nad.sql"))

    # Create the submissions database if it does not exist, then its schema.
    exists = psql_capture("postgres",
                          f"SELECT 1 FROM pg_database WHERE datname='{NADSUB_DB}'")
    if exists != "1":
        print(f"  Creating database '{NADSUB_DB}'...")
        subprocess.run(["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres",
                        "-d", "postgres", "-c", f'CREATE DATABASE "{NADSUB_DB}"'],
                       check=True, capture_output=True, text=True)
    else:
        print(f"  Database '{NADSUB_DB}' already exists.")
    psql_file(NADSUB_DB, os.path.join(DB_DIR, "02_init_nad_sub.sql"))
    print("  Schema ready.")


def terraform_apply():
    print("\nApplying Terraform (builds the API + web images, starts containers)...")
    run(["terraform", "init", "-input=false", "-upgrade"], cwd=TF_DIR)
    run(["terraform", "apply", "-auto-approve", "-input=false"], cwd=TF_DIR)


def terraform_destroy():
    if not os.path.isdir(os.path.join(TF_DIR, ".terraform")):
        print("Terraform not initialized; nothing to destroy.")
        return
    run(["terraform", "destroy", "-auto-approve", "-input=false"], cwd=TF_DIR)
    print("API and web containers removed. PostgreSQL was left running.")


def print_status():
    for name in (PG_CONTAINER, "address-verification-api", "address-verification-web"):
        print(f"  {name}: {container_state(name) or 'not created'}")
    print(f"\n  Web UI:     http://localhost:{WEB_PORT}")
    print(f"  Statistics: http://localhost:{WEB_PORT}/stats.html")
    print(f"  API health: http://localhost:{API_PORT}/api/health")


# ----------------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--open", action="store_true",
                        help="open the web UI in a browser when ready")
    parser.add_argument("--status", action="store_true",
                        help="show container status and URLs, then exit")
    parser.add_argument("--down", action="store_true",
                        help="terraform destroy the API + web containers")
    parser.add_argument("--skip-index", action="store_true",
                        help="skip the slow one-time trigram index build")
    args = parser.parse_args()

    if not docker_available():
        sys.exit("Docker is not available. Start Docker Desktop and try again.")

    if args.status:
        print_status()
        return
    if args.down:
        terraform_destroy()
        return

    ensure_postgres()
    init_databases(skip_index=args.skip_index)
    terraform_apply()

    api_ok = wait_for(f"http://localhost:{API_PORT}/api/health", "API")
    web_ok = wait_for(f"http://localhost:{WEB_PORT}/", "web UI")

    print("\n" + "=" * 60)
    if api_ok and web_ok:
        print("Stack is up.")
    else:
        print("Stack started, but a health check did not pass — see above.")
    print("=" * 60)
    print(f"  Web UI:     http://localhost:{WEB_PORT}")
    print(f"  Statistics: http://localhost:{WEB_PORT}/stats.html")
    print(f"  API health: http://localhost:{API_PORT}/api/health")
    print(f"\nStop with:  python3 {os.path.relpath(__file__, os.getcwd())} --down")

    if args.open and web_ok:
        import webbrowser
        webbrowser.open(f"http://localhost:{WEB_PORT}")


if __name__ == "__main__":
    main()
