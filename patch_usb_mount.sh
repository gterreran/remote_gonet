#!/bin/bash
set -euo pipefail

# ----------------------------------------------------------------------
# GONet USB auto-mount patch (exFAT default + writable + hot-swap)
# ----------------------------------------------------------------------

MOUNTPOINT="/media/pi/usb"
MARKER_FILE=".gonet_usb"

AUTOMOUNT_SCRIPT="/usr/local/bin/gonet_mount_usb.sh"
MOUNT_CMD="/usr/local/bin/mount-usb"
UMOUNT_CMD="/usr/local/bin/umount-usb"
FORMAT_CMD="/usr/local/bin/format-for-gonet"

SERVICE_FILE="/etc/systemd/system/gonet-mount-usb.service"
UDEV_RULE="/etc/udev/rules.d/99-gonet-usb.rules"

# Where gonet4.py expects to copy
DUMP_DIR="GONetDump"
IMAGES_DIR="${DUMP_DIR}/images"

echo "==> Creating mount point: ${MOUNTPOINT}"
sudo mkdir -p "${MOUNTPOINT}"
sudo chown pi:pi "${MOUNTPOINT}" || true

echo "==> Installing auto-mount script: ${AUTOMOUNT_SCRIPT}"
sudo tee "${AUTOMOUNT_SCRIPT}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail

MOUNTPOINT="/media/pi/usb"
MARKER_FILE=".gonet_usb"

DUMP_DIR="GONetDump"
IMAGES_DIR="${DUMP_DIR}/images"

# -----------------------------
# Helper: find first removable USB partition
# -----------------------------
find_usb_partition() {
    # Prefer true USB bus partitions
    local dev
    dev=$(lsblk -lnpo NAME,TYPE,RM,TRAN | awk '$2=="part" && $3=="1" && $4=="usb" {print $1; exit}')
    if [ -n "${dev:-}" ]; then
        echo "$dev"
        return 0
    fi

    # Fallback: any removable partition
    dev=$(lsblk -lnpo NAME,TYPE,RM | awk '$2=="part" && $3=="1" {print $1; exit}')
    echo "${dev:-}"
}

# -----------------------------
# If already mounted, ensure dirs and marker
# -----------------------------
if mountpoint -q "$MOUNTPOINT"; then
    mkdir -p "$MOUNTPOINT/$IMAGES_DIR" "$MOUNTPOINT/$THUMBS_DIR" || true
    touch "$MOUNTPOINT/$MARKER_FILE" || true
    exit 0
fi

DEV="$(find_usb_partition)"
if [ -z "${DEV:-}" ]; then
    exit 0
fi

mkdir -p "$MOUNTPOINT"

# Determine filesystem type
FSTYPE="$(lsblk -no FSTYPE "$DEV" 2>/dev/null || true)"

# If something is already mounted there, bail
if mountpoint -q "$MOUNTPOINT"; then
    exit 0
fi

# Try to mount.
# For exfat/vfat: must set uid/gid/umask for pi to write.
# For everything else: mount normally (best effort).
if [ "$FSTYPE" = "exfat" ]; then
    mount -t exfat -o rw,uid=pi,gid=pi,umask=0002 "$DEV" "$MOUNTPOINT"
elif [ "$FSTYPE" = "vfat" ] || [ "$FSTYPE" = "msdos" ]; then
    mount -t vfat -o rw,uid=pi,gid=pi,umask=0002,utf8=1,flush "$DEV" "$MOUNTPOINT"
else
    # Unknown fs: try auto
    mount "$DEV" "$MOUNTPOINT" || exit 0
fi

# Create expected destination folders for gonet4 transfers
mkdir -p "$MOUNTPOINT/$IMAGES_DIR" "$MOUNTPOINT/$THUMBS_DIR" || true
touch "$MOUNTPOINT/$MARKER_FILE" || true

exit 0
EOF
sudo chmod +x "${AUTOMOUNT_SCRIPT}"

echo "==> Installing systemd unit: ${SERVICE_FILE}"
sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Mount first available removable USB drive for GONet (exFAT writable for pi)
After=local-fs.target
Wants=local-fs.target

[Service]
Type=oneshot
ExecStart=${AUTOMOUNT_SCRIPT}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

echo "==> Installing udev rule for hot-swap auto-mount: ${UDEV_RULE}"
sudo tee "${UDEV_RULE}" >/dev/null <<'EOF'
# When a USB partition appears, trigger the systemd mount service
ACTION=="add", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", ENV{DEVTYPE}=="partition", TAG+="systemd", ENV{SYSTEMD_WANTS}="gonet-mount-usb.service"
EOF

echo "==> Installing convenience command: ${MOUNT_CMD}"
sudo tee "${MOUNT_CMD}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
sudo systemctl start gonet-mount-usb.service
if mountpoint -q /media/pi/usb; then
  echo "USB mounted at /media/pi/usb"
  ls -ld /media/pi/usb
else
  echo "USB not mounted (no removable drive found)"
fi
EOF
sudo chmod +x "${MOUNT_CMD}"

echo "==> Installing convenience command: ${UMOUNT_CMD}"
sudo tee "${UMOUNT_CMD}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail

MP="/media/pi/usb"
sync

if mountpoint -q "$MP"; then
    if sudo umount "$MP"; then
        echo "Unmounted $MP"
        exit 0
    fi

    echo "Unmount failed: $MP is busy."
    echo "Processes using $MP:"
    sudo lsof +f -- "$MP" || true
    echo "You may need to stop transfer scripts or close shells in that directory."
    exit 1
else
    echo "$MP is not mounted."
    exit 0
fi
EOF
sudo chmod +x "${UMOUNT_CMD}"

echo "==> Installing format command: ${FORMAT_CMD}"
sudo tee "${FORMAT_CMD}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail

MOUNTPOINT="/media/pi/usb"
LABEL="GONET_USB"

DUMP_DIR="GONetDump"
IMAGES_DIR="${DUMP_DIR}/images"

echo "==> This will ERASE the USB drive currently inserted."
echo "==> Continue? Type YES to proceed:"
read -r ans
if [ "${ans:-}" != "YES" ]; then
  echo "Aborted."
  exit 1
fi

# Find first removable USB partition
DEV=$(lsblk -lnpo NAME,TYPE,RM,TRAN | awk '$2=="part" && $3=="1" && $4=="usb" {print $1; exit}')
if [ -z "${DEV:-}" ]; then
  DEV=$(lsblk -lnpo NAME,TYPE,RM | awk '$2=="part" && $3=="1" {print $1; exit}')
fi

if [ -z "${DEV:-}" ]; then
  echo "No removable USB partition found."
  exit 1
fi

# Extra safety: refuse to format root disk-ish devices
# We only allow /dev/sdXn, /dev/mmcblkXpY, /dev/nvme... partitions.
if ! echo "$DEV" | grep -Eq '^/dev/(sd[a-z][0-9]+|mmcblk[0-9]+p[0-9]+|nvme[0-9]+n[0-9]+p[0-9]+)$'; then
  echo "Refusing to format unexpected device: $DEV"
  exit 1
fi

echo "==> Target partition: $DEV"
echo "==> Unmounting $MOUNTPOINT if mounted..."
if mountpoint -q "$MOUNTPOINT"; then
  sudo umount "$MOUNTPOINT"
fi

echo "==> Formatting as exFAT (label=${LABEL})..."
# Requires exfatprogs on modern Raspberry Pi OS
sudo mkfs.exfat -n "$LABEL" "$DEV"

echo "==> Mounting..."
sudo mkdir -p "$MOUNTPOINT"
sudo mount -t exfat -o rw,uid=pi,gid=pi,umask=0002 "$DEV" "$MOUNTPOINT"

echo "==> Creating expected folders..."
mkdir -p "$MOUNTPOINT/$IMAGES_DIR" "$MOUNTPOINT/$THUMBS_DIR"
touch "$MOUNTPOINT/.gonet_usb" || true

echo "Done."
echo "Mounted at $MOUNTPOINT"
df -Th "$MOUNTPOINT" || true
EOF
sudo chmod +x "${FORMAT_CMD}"

echo "==> Enabling service at boot"
sudo systemctl daemon-reload
sudo systemctl enable gonet-mount-usb.service

echo "==> Reloading udev rules"
sudo udevadm control --reload-rules
sudo udevadm trigger || true

echo "==> Starting service now (if a USB is inserted, it will mount)"
sudo systemctl start gonet-mount-usb.service || true

echo
echo "Done."
echo "Commands installed:"
echo "  mount-usb         -> mounts first removable USB drive to /media/pi/usb"
echo "  umount-usb        -> safely unmounts /media/pi/usb"
echo "  format-for-gonet  -> ERASES and formats inserted USB as exFAT + creates folders"
echo
echo "Hot-swap behavior:"
echo "  Replugging a USB stick should auto-mount via udev."
echo "  On boot, systemd will mount if a USB is inserted."
echo
echo "Check status:"
echo "  systemctl status gonet-mount-usb.service"
echo "  mount | grep /media/pi/usb"
echo "  ls -ld /media/pi/usb /media/pi/usb/GONetDump /media/pi/usb/GONetDump/images"
echo "  lsblk -f"