#!/bin/bash
set -euo pipefail

# ----------------------------------------------------------------------
# remote_gonet installer (Pi-side, curl-only bootstrap)
# ----------------------------------------------------------------------
# Intended usage (no repo clone needed):
#   curl -L -o setup_remote_gonet.sh \
#     https://raw.githubusercontent.com/gterreran/remote_gonet/main/setup_remote_gonet.sh
#   chmod +x setup_remote_gonet.sh
#   sudo ./setup_remote_gonet.sh
#
# What it does:
# - downloads repo files directly from GitHub (raw) into the correct GONet paths
# - installs /home/pi/Tools/Camera/{gonet4.py, utils/*}
# - installs cron/CronRemoteBackup.txt -> /home/pi/Tools/Crontab/CronRemoteBackup.txt
# - runs patches/patch_usb_mount.sh
# - runs patches/patch_remote_bootup.sh
# - replaces /home/pi/Tools/Web/camera/index.php with webpages/remote_camera_index.php
#   (backup saved alongside)
# ----------------------------------------------------------------------

# -----------------------------
# Config (edit if needed)
# -----------------------------

RAW_BASE="https://raw.githubusercontent.com/gterreran/remote_gonet/main"

CAMERA_DIR="/home/pi/Tools/Camera"
CRONTAB_DIR="/home/pi/Tools/Crontab"
WEB_CAMERA_DIR="/home/pi/Tools/Web/camera"

REMOTE_INDEX_DST="${WEB_CAMERA_DIR}/index.php"

# Work dir for downloaded patch scripts
WORKDIR="$(mktemp -d /tmp/remote_gonet.XXXXXX)"

timestamp() { date -u +"%Y%m%dT%H%M%SZ"; }

die() {
  echo "ERROR: $*" >&2
  exit 1
}

cleanup() {
  rm -rf "${WORKDIR}" || true
}
trap cleanup EXIT

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

fetch() {
  # fetch <remote_path> <local_path>
  local remote_path="$1"
  local local_path="$2"

  local url="${RAW_BASE}/${remote_path}"
  sudo mkdir -p "$(dirname "${local_path}")"

  echo "    GET ${remote_path} -> ${local_path}"
  # -f: fail on HTTP errors; -S: show errors; -L: follow redirects
  curl -fSL "${url}" -o /tmp/.remote_gonet_dl
  sudo mv /tmp/.remote_gonet_dl "${local_path}"
}

echo "==> remote_gonet install starting (curl-only)"
echo "    raw_base: ${RAW_BASE}"
echo "    workdir : ${WORKDIR}"

need_cmd curl

# ----------------------------------------------------------------------
# 1) Install Camera code (src/ -> /home/pi/Tools/Camera/)
# ----------------------------------------------------------------------
echo "==> Installing camera code into ${CAMERA_DIR}"

sudo mkdir -p "${CAMERA_DIR}/utils"

fetch "src/gonet4.py" "${CAMERA_DIR}/gonet4.py"

fetch "src/utils/__init__.py"        "${CAMERA_DIR}/utils/__init__.py"
fetch "src/utils/config.py"          "${CAMERA_DIR}/utils/config.py"
fetch "src/utils/gps.py"             "${CAMERA_DIR}/utils/gps.py"
fetch "src/utils/imaging_meta.py"    "${CAMERA_DIR}/utils/imaging_meta.py"
fetch "src/utils/imaging_pipeline.py""${CAMERA_DIR}/utils/imaging_pipeline.py"
fetch "src/utils/logging.py"         "${CAMERA_DIR}/utils/logging.py"
fetch "src/utils/setup.py"           "${CAMERA_DIR}/utils/setup.py"
fetch "src/utils/sun_gate.py"        "${CAMERA_DIR}/utils/sun_gate.py"
fetch "src/utils/transfer.py"        "${CAMERA_DIR}/utils/transfer.py"

# Make sure pi owns the deployed python files (helps editing/debugging)
sudo chown -R pi:pi "${CAMERA_DIR}" || true

# ----------------------------------------------------------------------
# 2) Install CronRemoteBackup.txt
# ----------------------------------------------------------------------
echo "==> Installing remote crontab backup into ${CRONTAB_DIR}"

fetch "cron/CronRemoteBackup.txt" "${CRONTAB_DIR}/CronRemoteBackup.txt"
sudo chown pi:pi "${CRONTAB_DIR}/CronRemoteBackup.txt" || true

# ----------------------------------------------------------------------
# 3) Download + run patches
# ----------------------------------------------------------------------
echo "==> Downloading patches"
PATCH_USB_LOCAL="${WORKDIR}/patch_usb_mount.sh"
PATCH_BOOT_LOCAL="${WORKDIR}/patch_remote_bootup.sh"

fetch "patches/patch_usb_mount.sh" "${PATCH_USB_LOCAL}"
fetch "patches/patch_remote_bootup.sh" "${PATCH_BOOT_LOCAL}"

sudo chmod +x "${PATCH_USB_LOCAL}" "${PATCH_BOOT_LOCAL}"

echo "==> Running USB mount patch"
sudo bash "${PATCH_USB_LOCAL}"

echo "==> Running remote bootup patch"
sudo bash "${PATCH_BOOT_LOCAL}"

# ----------------------------------------------------------------------
# 4) Replace web UI index.php with remote page (backup original)
# ----------------------------------------------------------------------
echo "==> Installing web camera index.php"

REMOTE_INDEX_LOCAL="${WORKDIR}/remote_camera_index.php"
fetch "webpages/remote_camera_index.php" "${REMOTE_INDEX_LOCAL}"

if [[ -f "${REMOTE_INDEX_DST}" ]]; then
  backup="${REMOTE_INDEX_DST}.bak.$(timestamp)"
  echo "    backing up existing index.php -> ${backup}"
  sudo cp -a "${REMOTE_INDEX_DST}" "${backup}"
fi

echo "    writing ${REMOTE_INDEX_LOCAL} -> ${REMOTE_INDEX_DST}"
sudo cp -a "${REMOTE_INDEX_LOCAL}" "${REMOTE_INDEX_DST}"
sudo chown pi:pi "${REMOTE_INDEX_DST}" || true

echo "==> Install complete."