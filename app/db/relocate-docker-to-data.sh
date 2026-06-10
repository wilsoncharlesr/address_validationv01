#!/usr/bin/env bash
#
# Relocate Docker's data-root (images, containers, AND volumes — including the
# address-verification-pg Postgres volume) from the cramped /var partition onto
# the big /data disk on this RHEL host.
#
# Why: `df -h` shows /var (23G) at 100% while /data (500G) has ~413G free, and
# Docker stores everything under /var/lib/docker. Pointing Docker at
# /data/docker fixes "No space left on device" without changing any app config
# (container name and volume name are preserved).
#
# Safe by design:
#   - Aborts on any error; your original /var/lib/docker is left untouched until
#     you explicitly pass --delete-old.
#   - Backs up /etc/docker/daemon.json and MERGES the data-root key (other keys
#     are preserved).
#   - Handles SELinux labels (semanage equivalency + restorecon).
#   - Idempotent: re-running after a partial move just resyncs.
#
# USAGE (run as root on the VM):
#   sudo bash relocate-docker-to-data.sh                 # interactive, target /data/docker
#   sudo bash relocate-docker-to-data.sh --yes           # no prompt
#   sudo bash relocate-docker-to-data.sh /data/docker --yes --delete-old
#
set -euo pipefail

# ----------------------------------------------------------------- args / config
TARGET="/data/docker"
ASSUME_YES=0
DELETE_OLD=0
OLD_ROOT="/var/lib/docker"

for arg in "$@"; do
  case "$arg" in
    --yes|-y)       ASSUME_YES=1 ;;
    --delete-old)   DELETE_OLD=1 ;;
    -h|--help)      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --*)            echo "Unknown option: $arg" >&2; exit 2 ;;
    *)              TARGET="$arg" ;;
  esac
done

say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------- preflight
[[ $EUID -eq 0 ]] || die "Run as root (use sudo)."
command -v docker >/dev/null   || die "docker is not installed / not in PATH."
command -v systemctl >/dev/null|| die "systemctl not found (expected on RHEL 9)."
[[ "$TARGET" != "$OLD_ROOT" ]] || die "Target equals the current root ($OLD_ROOT)."

TARGET_PARENT="$(dirname "$TARGET")"
[[ -d "$TARGET_PARENT" ]] || die "Target parent '$TARGET_PARENT' does not exist (is /data mounted?)."

CURRENT_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo "$OLD_ROOT")"
if [[ "$CURRENT_ROOT" == "$TARGET" ]]; then
  say "Docker is already using $TARGET. Nothing to do."
  exit 0
fi
say "Docker data-root is currently: $CURRENT_ROOT"

# Space check: need at least the size of the existing data root (same FS only).
NEED_BYTES=$(du -sxb "$OLD_ROOT" 2>/dev/null | awk '{print $1}')
AVAIL_BYTES=$(df -B1 --output=avail "$TARGET_PARENT" | tail -1 | tr -d ' ')
say "Existing Docker data: $(numfmt --to=iec "$NEED_BYTES" 2>/dev/null || echo "${NEED_BYTES}B")  |  Free on $TARGET_PARENT: $(numfmt --to=iec "$AVAIL_BYTES" 2>/dev/null || echo "${AVAIL_BYTES}B")"
if (( AVAIL_BYTES < NEED_BYTES * 11 / 10 )); then
  die "Not enough free space on $TARGET_PARENT for the migration."
fi

# ----------------------------------------------------------------- confirm
cat <<EOF

This will:
  1. Stop Docker (and all running containers, incl. address-verification-pg).
  2. Set Docker's data-root to: $TARGET
  3. Copy $OLD_ROOT  ->  $TARGET  (preserving permissions, xattrs, SELinux).
  4. Start Docker and verify, then restart the Postgres container.
$( [[ $DELETE_OLD -eq 1 ]] && echo "  5. DELETE the old $OLD_ROOT to reclaim /var." )

Your original data stays at $OLD_ROOT $( [[ $DELETE_OLD -eq 1 ]] && echo "until step 5" || echo "(not deleted)" ).
EOF
if [[ $ASSUME_YES -ne 1 ]]; then
  read -rp $'\nContinue? [y/N] ' ans
  [[ "$ans" == [yY]* ]] || { echo "Aborted."; exit 0; }
fi

# Roll-back hint if anything fails past this point.
trap 'echo;
warn "Migration failed. Your original data is intact at '"$OLD_ROOT"'.";
warn "To roll back: restore /etc/docker/daemon.json from its .bak file and run: systemctl start docker";' ERR

# ----------------------------------------------------------------- deps + target dir
command -v rsync >/dev/null || { say "Installing rsync..."; dnf install -y rsync; }
mkdir -p "$TARGET"

# ----------------------------------------------------------------- SELinux equivalency
if command -v getenforce >/dev/null && [[ "$(getenforce)" != "Disabled" ]]; then
  say "SELinux is $(getenforce): mapping $TARGET to Docker's labels."
  command -v semanage >/dev/null || { say "Installing policycoreutils-python-utils..."; dnf install -y policycoreutils-python-utils; }
  semanage fcontext -a -e "$OLD_ROOT" "$TARGET" 2>/dev/null \
    || semanage fcontext -m -e "$OLD_ROOT" "$TARGET" 2>/dev/null \
    || warn "Could not set SELinux equivalency; continuing."
fi

# ----------------------------------------------------------------- stop docker
say "Stopping Docker..."
systemctl stop docker.socket docker.service 2>/dev/null || systemctl stop docker || true

# ----------------------------------------------------------------- daemon.json (merge)
mkdir -p /etc/docker
if [[ -f /etc/docker/daemon.json ]]; then
  cp -a /etc/docker/daemon.json "/etc/docker/daemon.json.bak.$(date +%Y%m%d-%H%M%S)"
fi
say "Setting data-root in /etc/docker/daemon.json"
python3 - "$TARGET" <<'PY'
import json, os, sys
path, target = "/etc/docker/daemon.json", sys.argv[1]
data = {}
if os.path.exists(path):
    with open(path) as f:
        txt = f.read().strip()
        if txt:
            data = json.loads(txt)
data["data-root"] = target
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("  ->", json.dumps(data))
PY

# ----------------------------------------------------------------- copy data
say "Copying data (this can take a while)..."
rsync -aHAX --info=progress2 "$OLD_ROOT"/ "$TARGET"/

# ----------------------------------------------------------------- SELinux relabel
if command -v restorecon >/dev/null && [[ "$(getenforce 2>/dev/null)" != "Disabled" ]]; then
  say "Relabeling $TARGET for SELinux..."
  restorecon -R "$TARGET"
fi

# ----------------------------------------------------------------- start + verify
say "Starting Docker..."
systemctl start docker
for i in $(seq 1 15); do docker info >/dev/null 2>&1 && break; sleep 1; done

NEW_ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo '?')"
[[ "$NEW_ROOT" == "$TARGET" ]] || die "Docker root is '$NEW_ROOT', expected '$TARGET'. Check: journalctl -u docker"
say "Docker is now running with data-root: $NEW_ROOT"
trap - ERR

# Bring the Postgres container back (it has no auto-restart policy).
if docker ps -a --format '{{.Names}}' | grep -qx address-verification-pg; then
  say "Starting the Postgres container..."
  docker start address-verification-pg || warn "Could not auto-start; run: python3 app/db/start_db.py"
fi

# ----------------------------------------------------------------- optional cleanup
if [[ $DELETE_OLD -eq 1 ]]; then
  say "Deleting old data root $OLD_ROOT to reclaim /var..."
  rm -rf "$OLD_ROOT"
  say "Reclaimed. /var now:"; df -h /var | tail -1
else
  warn "Old data left at $OLD_ROOT (still using /var). After you've confirmed"
  warn "everything works, reclaim that space with:  rm -rf $OLD_ROOT"
fi

# ----------------------------------------------------------------- summary
cat <<EOF

$(printf '\033[1;32mDone.\033[0m')  Docker data now lives on $TARGET.
  Verify:    docker info | grep 'Docker Root Dir'
  Volumes:   docker volume ls          (address-verification-pgdata should be listed)
  Postgres:  python3 app/db/start_db.py --status
  Free /data:$(df -h "$TARGET_PARENT" | awk 'NR==2{print "  "$4" available"}')
EOF
