#!/bin/bash
set -euo pipefail

# ----------------------------------------------------------------------
# patch_remote_bootup.sh
# ----------------------------------------------------------------------
# Purpose:
#   Patch the stock GONet /etc/rc.local so it loads the *remote* crontab
#   backup and sets the appropriate status marker.
#
# Changes:
#   1) crontab /home/pi/Tools/Crontab/CronBackup.txt
#        -> crontab /home/pi/Tools/Crontab/CronRemoteBackup.txt
#
#   2) touch /home/pi/Tools/Crontab/status/Default
#        -> touch /home/pi/Tools/Crontab/status/CronDefault
#
# Notes:
# - Idempotent: safe to run multiple times.
# - Makes a timestamped backup of rc.local before editing.
# ----------------------------------------------------------------------

RC_LOCAL="/etc/rc.local"

timestamp() { date -u +"%Y%m%dT%H%M%SZ"; }

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "This patch must be run as root (use sudo)."
  fi
}

need_file() {
  [[ -f "$1" ]] || die "Missing required file: $1"
}

replace_line() {
  # replace_line <file> <from> <to>
  local file="$1"
  local from="$2"
  local to="$3"

  if grep -Fq "$to" "$file"; then
    echo "    OK: already patched: $to"
    return 0
  fi

  if ! grep -Fq "$from" "$file"; then
    echo "    WARN: pattern not found (skipping): $from"
    return 0
  fi

  # Use sed with a safe delimiter
  sed -i "s|$from|$to|g" "$file"
  echo "    PATCHED: $from -> $to"
}

echo "==> Applying remote bootup patch"

need_root
need_file "$RC_LOCAL"

backup="${RC_LOCAL}.bak.$(timestamp)"
echo "==> Backing up ${RC_LOCAL} -> ${backup}"
cp -a "$RC_LOCAL" "$backup"

# 1) Swap which crontab backup is loaded at boot
replace_line \
  "$RC_LOCAL" \
  "su pi -c 'crontab /home/pi/Tools/Crontab/CronBackup.txt'" \
  "su pi -c 'crontab /home/pi/Tools/Crontab/CronRemoteBackup.txt'"

# 2) Swap cron status marker
replace_line \
  "$RC_LOCAL" \
  "su pi -c 'touch /home/pi/Tools/Crontab/status/Default'" \
  "su pi -c 'touch /home/pi/Tools/Crontab/status/RemoteDefault'"

echo "==> Done. (backup: ${backup})"