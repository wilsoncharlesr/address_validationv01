#!/usr/bin/env python3
"""
Build and start a local PostgreSQL container for address-verification work.

Uses the Dockerfile in this directory (postgres:16 with
POSTGRES_HOST_AUTH_METHOD=trust, so no password is needed — local dev only).
Data persists in a named Docker volume across restarts.

USAGE
  python3 start_postgres.py                 # build image (if needed) and start
  python3 start_postgres.py --stop          # stop and remove the container
  python3 start_postgres.py --status        # show container status
  python3 start_postgres.py --destroy       # stop container and delete the data volume
  python3 start_postgres.py --reset-volume  # fresh data volume, verified big enough
                                            # for the full 74M-row NAD load

Connect with:
  psql -h localhost -p 5433 -U postgres -d nad
"""

import argparse
import os
import subprocess
import sys
import time

IMAGE_NAME = "address-verification-postgres"
CONTAINER_NAME = "address-verification-pg"
VOLUME_NAME = "address-verification-pgdata"
# 5433 because a native Postgres on this machine already owns 127.0.0.1:5432.
HOST_PORT = 5433
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Full 74M-row NAD load: ~40 GB of table data plus indexes and WAL headroom.
REQUIRED_FREE_GB = 60


def run(cmd, check=True, capture=False):
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def docker_available():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def container_state():
    """Return 'running', 'exited', etc., or None if the container doesn't exist."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def build_image():
    run(["docker", "build", "-t", IMAGE_NAME, SCRIPT_DIR])


def start():
    state = container_state()
    if state == "running":
        print(f"Container '{CONTAINER_NAME}' is already running.")
        return
    if state is not None:
        run(["docker", "rm", CONTAINER_NAME])

    build_image()
    run([
        "docker", "run",
        "--detach",
        "--name", CONTAINER_NAME,
        "--publish", f"{HOST_PORT}:5432",
        "--volume", f"{VOLUME_NAME}:/var/lib/postgresql/data",
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
        IMAGE_NAME,
    ])
    wait_until_ready()
    print(f"\nPostgreSQL is up. Connect with:")
    print(f"  psql -h localhost -p {HOST_PORT} -U postgres -d nad")


def wait_until_ready(timeout_seconds=60):
    print("Waiting for PostgreSQL to accept connections...", end="", flush=True)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "pg_isready", "-U", "postgres"],
            capture_output=True,
        )
        if result.returncode == 0:
            print(" ready.")
            return
        print(".", end="", flush=True)
        time.sleep(1)
    sys.exit(f"\nPostgreSQL did not become ready within {timeout_seconds}s; "
             f"check logs with: docker logs {CONTAINER_NAME}")


def stop():
    if container_state() is None:
        print(f"Container '{CONTAINER_NAME}' does not exist.")
        return
    run(["docker", "stop", CONTAINER_NAME])
    run(["docker", "rm", CONTAINER_NAME])
    print("Stopped and removed the container (data volume kept).")


def destroy():
    stop()
    result = subprocess.run(
        ["docker", "volume", "rm", VOLUME_NAME], capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"Deleted data volume '{VOLUME_NAME}'.")
    else:
        print(f"Volume '{VOLUME_NAME}' not removed: {result.stderr.strip()}")


def data_disk_free_gb():
    """Free space (GB) on the filesystem backing the data volume."""
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME,
         "df", "-BG", "--output=avail", "/var/lib/postgresql/data"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return int(result.stdout.strip().splitlines()[-1].strip().rstrip("G"))


def reset_volume():
    """Replace the data volume with a fresh one and verify it has room
    for the full 74M-row NAD load."""
    if container_state() is not None:
        stop()
    result = subprocess.run(
        ["docker", "volume", "rm", VOLUME_NAME], capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"Deleted data volume '{VOLUME_NAME}'.")
    elif "no such volume" not in result.stderr.lower():
        sys.exit(f"Could not remove volume '{VOLUME_NAME}': "
                 f"{result.stderr.strip()}")
    run(["docker", "volume", "create", VOLUME_NAME])
    print(f"Created fresh data volume '{VOLUME_NAME}'.")
    start()

    free_gb = data_disk_free_gb()
    if free_gb is None:
        print("Warning: could not determine free space on the data volume.")
    elif free_gb < REQUIRED_FREE_GB:
        print(f"\nWARNING: only {free_gb} GB free on the Docker disk; the full "
              f"74M-row load needs ~{REQUIRED_FREE_GB} GB.")
        print("Increase the disk size in Docker Desktop: "
              "Settings > Resources > Virtual disk limit, or free space with "
              "'docker system prune'.")
    else:
        print(f"\n{free_gb} GB free on the Docker disk — enough for the full "
              f"74M-row load (~{REQUIRED_FREE_GB} GB needed).")


def status():
    state = container_state()
    if state is None:
        print(f"Container '{CONTAINER_NAME}' does not exist.")
    else:
        print(f"Container '{CONTAINER_NAME}': {state}")
        if state == "running":
            print(f"  Port: localhost:{HOST_PORT}")
            print(f"  Connect: psql -h localhost -p {HOST_PORT} -U postgres -d nad")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stop", action="store_true", help="stop and remove the container")
    group.add_argument("--status", action="store_true", help="show container status")
    group.add_argument("--destroy", action="store_true",
                       help="stop the container and delete the data volume")
    group.add_argument("--reset-volume", action="store_true",
                       help="replace the data volume with a fresh one sized "
                            "for the full 74M-row NAD load")
    args = parser.parse_args()

    if not docker_available():
        sys.exit("Docker is not available. Start Docker Desktop and try again.")

    if args.stop:
        stop()
    elif args.status:
        status()
    elif args.destroy:
        destroy()
    elif args.reset_volume:
        reset_volume()
    else:
        start()


if __name__ == "__main__":
    main()
