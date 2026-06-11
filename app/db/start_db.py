#!/usr/bin/env python3
"""
Build and start the PostgreSQL container for the address-verification stack.

Builds the image from the Dockerfile in this folder (postgres:16, trust auth,
database `nad`) and runs it as the container the rest of the stack expects:
name `address-verification-pg`, host port 5433, data in a named Docker volume
that persists across restarts. On a fresh volume the image bootstraps the
`nad_sub` database and submissions schema automatically; on an existing volume
the pre-loaded `il_addresses` data is reused untouched.

USAGE
  python3 start_db.py                 # build (if needed) and start the container
  python3 start_db.py --stop          # stop and remove the container (keep data)
  python3 start_db.py --status        # show container status and how to connect
  python3 start_db.py --destroy       # stop the container and delete the data volume
  python3 start_db.py --reset-volume  # fresh data volume, sized for the full NAD load
  python3 start_db.py --rebuild       # force an image rebuild, then start

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
# 5433 because a native PostgreSQL on this machine already owns 127.0.0.1:5432.
HOST_PORT = 5433
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Full ~74M-row NAD load: ~40 GB of table data plus indexes and WAL headroom.
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
        capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def image_exists():
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME],
        capture_output=True, text=True)
    return result.returncode == 0


def build_image():
    run(["docker", "build", "-t", IMAGE_NAME, SCRIPT_DIR])


def start(rebuild=False):
    state = container_state()
    if state == "running":
        print(f"Container '{CONTAINER_NAME}' is already running.")
        status()
        return
    if state is not None:
        run(["docker", "rm", CONTAINER_NAME])

    if rebuild or not image_exists():
        build_image()

    run([
        "docker", "run",
        "--detach",
        "--name", CONTAINER_NAME,
        "--publish", f"{HOST_PORT}:5432",
        "--volume", f"{VOLUME_NAME}:/var/lib/postgresql/data",
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
        IMAGE_NAME,
        # The API runs two Npgsql pools of up to 200 connections each; default
        # max_connections=100 would exhaust under load.
        "-c", "max_connections=500",
    ])
    wait_until_ready()
    status()


def wait_until_ready(timeout_seconds=60):
    print("Waiting for PostgreSQL to accept connections...", end="", flush=True)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "pg_isready", "-U", "postgres"],
            capture_output=True)
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
        ["docker", "volume", "rm", VOLUME_NAME], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Deleted data volume '{VOLUME_NAME}'.")
    else:
        print(f"Volume '{VOLUME_NAME}' not removed: {result.stderr.strip()}")


def data_disk_free_gb():
    """Free space (GB) on the filesystem backing the data volume."""
    result = subprocess.run(
        ["docker", "exec", CONTAINER_NAME,
         "df", "-BG", "--output=avail", "/var/lib/postgresql/data"],
        capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return int(result.stdout.strip().splitlines()[-1].strip().rstrip("G"))


def reset_volume():
    """Replace the data volume with a fresh one and verify it has room for the
    full NAD load. The fresh volume triggers the image's first-init bootstrap."""
    if container_state() is not None:
        stop()
    result = subprocess.run(
        ["docker", "volume", "rm", VOLUME_NAME], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Deleted data volume '{VOLUME_NAME}'.")
    elif "no such volume" not in result.stderr.lower():
        sys.exit(f"Could not remove volume '{VOLUME_NAME}': {result.stderr.strip()}")
    run(["docker", "volume", "create", VOLUME_NAME])
    print(f"Created fresh data volume '{VOLUME_NAME}'.")
    start(rebuild=True)

    free_gb = data_disk_free_gb()
    if free_gb is None:
        print("Warning: could not determine free space on the data volume.")
    elif free_gb < REQUIRED_FREE_GB:
        print(f"\nWARNING: only {free_gb} GB free on the Docker disk; the full "
              f"~74M-row load needs ~{REQUIRED_FREE_GB} GB.")
        print("Increase the disk size in Docker Desktop: "
              "Settings > Resources > Virtual disk limit, or free space with "
              "'docker system prune'.")
    else:
        print(f"\n{free_gb} GB free on the Docker disk — enough for the full "
              f"~74M-row load (~{REQUIRED_FREE_GB} GB needed).")


def status():
    state = container_state()
    if state is None:
        print(f"Container '{CONTAINER_NAME}' does not exist. Start it with: "
              f"python3 {os.path.basename(__file__)}")
        return
    print(f"Container '{CONTAINER_NAME}': {state}")
    if state == "running":
        print(f"  Port:    localhost:{HOST_PORT}")
        print(f"  Connect: psql -h localhost -p {HOST_PORT} -U postgres -d nad")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stop", action="store_true",
                       help="stop and remove the container (data volume kept)")
    group.add_argument("--status", action="store_true",
                       help="show container status and how to connect")
    group.add_argument("--destroy", action="store_true",
                       help="stop the container and delete the data volume")
    group.add_argument("--reset-volume", action="store_true",
                       help="replace the data volume with a fresh one sized for "
                            "the full NAD load")
    parser.add_argument("--rebuild", action="store_true",
                        help="force an image rebuild before starting")
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
        start(rebuild=args.rebuild)


if __name__ == "__main__":
    main()
