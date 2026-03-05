#!/bin/bash
set -euo pipefail

# ----------------------------------------------------------------------
# remote_gonet installer (Pi-side)
# ----------------------------------------------------------------------
# What it does:
# - copies repo src/ -> /home/pi/Tools/Camera/
# - runs patch_usb_mount.sh
# - runs patch_remote_bootup.sh (if present)
# - replaces /home/pi/Tools/Web/camera/index.php with remote_camera_index.php
#   (backup saved alongside)
#
# Usage:
#   ./install_remote_gonet.sh
# ----------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SRC_DIR="${REPO_ROOT}/src"
CAMERA_DIR="/home/pi/Tools/Camera"

PATCH_USB="${REPO_ROOT}/patch_usb_mount.sh"
PATCH_BOOT="${REPO_ROOT}/patch_remote_bootup.sh"

WEB_CAMERA_DIR="/home/pi/Tools/Web/camera"
REMOTE_INDEX_SRC="${REPO_ROOT}/remote_camera_index.php"
REMOTE_INDEX_DST="${WEB_CAMERA_DIR}/index.php"

timestamp() { date -u +"%Y%m%dT%H%M%SZ"; }

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_file() {
  [[ -f "$1" ]] || die "Missing required file: $1"
}

need_dir() {
  [[ -d "$1" ]] || die "Missing required directory: $1"
}

echo "==> remote_gonet install starting"
echo "    repo_root: ${REPO_ROOT}"

# ----------------------------------------------------------------------
# Sanity checks
# ----------------------------------------------------------------------
need_dir "${SRC_DIR}"
need_file "${PATCH_USB}"
need_file "${REMOTE_INDEX_SRC}"

# patch_remote_bootup.sh may not exist yet (you said still to be created).
# We'll handle it later with a clear message.

# ----------------------------------------------------------------------
# 1) Copy src/ -> /home/pi/Tools/Camera/
# ----------------------------------------------------------------------
echo "==> Syncing ${SRC_DIR}/ -> ${CAMERA_DIR}/"
# Use rsync for correctness + speed + idempotency
sudo rsync -a --delete "${SRC_DIR}/" "${CAMERA_DIR}/"

# ----------------------------------------------------------------------
# 2) Run patch_usb_mount.sh
# ----------------------------------------------------------------------
echo "==> Running USB mount patch: ${PATCH_USB}"
sudo bash "${PATCH_USB}"

# ----------------------------------------------------------------------
# 3) Run patch_remote_bootup.sh (if present)
# ----------------------------------------------------------------------
if [[ -f "${PATCH_BOOT}" ]]; then
  echo "==> Running remote bootup patch: ${PATCH_BOOT}"
  sudo bash "${PATCH_BOOT}"
else
  echo "==> NOTE: ${PATCH_BOOT} not found (skipping). Create it when ready."
fi

# ----------------------------------------------------------------------
# 4) Replace web UI index.php with remote_camera_index.php (backup original)
# ----------------------------------------------------------------------
echo "==> Installing web camera index.php"

if [[ -f "${REMOTE_INDEX_DST}" ]]; then
  backup="${REMOTE_INDEX_DST}.bak.$(timestamp)"
  echo "    backing up existing index.php -> ${backup}"
  sudo cp -a "${REMOTE_INDEX_DST}" "${backup}"
fi

echo "    writing ${REMOTE_INDEX_SRC} -> ${REMOTE_INDEX_DST}"
sudo cp -a "${REMOTE_INDEX_SRC}" "${REMOTE_INDEX_DST}"
sudo chown pi:pi "${REMOTE_INDEX_DST}" || true

echo "==> Install complete."