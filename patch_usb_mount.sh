#!/bin/bash
set -euo pipefail

# ----------------------------------------------------------------------
# GONet USB auto-mount patch
# ----------------------------------------------------------------------

MOUNTPOINT="/media/pi/usb"
MARKER_FILE=".gonet_usb"

AUTOMOUNT_SCRIPT="/usr/local/bin/gonet_mount_usb.sh"
MOUNT_CMD="/usr/local/bin/mount-usb"
UMOUNT_CMD="/usr/local/bin/umount-usb"
SERVICE_FILE="/etc/systemd/system/gonet-mount-usb.service"

echo "==> Creating mount point: ${MOUNTPOINT}"
sudo mkdir -p "${MOUNTPOINT}"
sudo chown -R pi:pi "${MOUNTPOINT}"

echo "==> Installing auto-mount script: ${AUTOMOUNT_SCRIPT}"
sudo tee "${AUTOMOUNT_SCRIPT}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail

MOUNTPOINT="/media/pi/usb"
MARKER_FILE=".gonet_usb"

# If already mounted, ensure ownership + marker then exit.
if mountpoint -q "$MOUNTPOINT"; then
    chown -R pi:pi "$MOUNTPOINT" || true
    touch "$MOUNTPOINT/$MARKER_FILE" || true
    exit 0
fi

# Find the first removable USB partition (RM==1, TYPE==part).
# This will pick /dev/sda1 in the common case. If multiple USB drives are present,
# it picks the first one listed by lsblk.
DEV=$(lsblk -lnpo NAME,TYPE,RM | awk '$2=="part" && $3=="1" {print $1; exit}')

# If no removable partition is found, exit quietly.
if [ -z "${DEV:-}" ]; then
    exit 0
fi

mkdir -p "$MOUNTPOINT"

# Mount using the kernel's filesystem autodetection.
# We do not rely on labels/UUIDs; any compatible USB stick should work.
mount "$DEV" "$MOUNTPOINT"

# Make it writable by user pi and create a marker file for safety checks.
chown -R pi:pi "$MOUNTPOINT" || true
touch "$MOUNTPOINT/$MARKER_FILE" || true
EOF

sudo chmod +x "${AUTOMOUNT_SCRIPT}"

echo "==> Installing systemd unit: ${SERVICE_FILE}"
sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Mount first available removable USB drive for GONet
After=local-fs.target
Wants=local-fs.target

[Service]
Type=oneshot
ExecStart=${AUTOMOUNT_SCRIPT}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

echo "==> Installing convenience command: ${MOUNT_CMD}"
sudo tee "${MOUNT_CMD}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
sudo systemctl start gonet-mount-usb.service
mountpoint -q /media/pi/usb && echo "USB mounted at /media/pi/usb" || echo "USB not mounted (no removable drive found)"
EOF
sudo chmod +x "${MOUNT_CMD}"

echo "==> Installing convenience command: ${UMOUNT_CMD}"
sudo tee "${UMOUNT_CMD}" >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail

MP="/media/pi/usb"

# Flush buffers before unmounting (important on FAT).
sync

if mountpoint -q "$MP"; then
    # Try a normal unmount first.
    if sudo umount "$MP"; then
        echo "Unmounted $MP"
        exit 0
    fi

    # If busy, show who is using it and fail with a helpful message.
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

echo "==> Enabling service at boot"
sudo systemctl daemon-reload
sudo systemctl enable gonet-mount-usb.service

echo "==> Starting service now (if a USB is inserted, it will mount)"
sudo systemctl start gonet-mount-usb.service || true

echo
echo "Done."
echo "Commands installed:"
echo "  mount-usb   -> mounts first removable USB drive to /media/pi/usb"
echo "  umount-usb  -> safely unmounts /media/pi/usb"
echo
echo "Check status:"
echo "  systemctl status gonet-mount-usb.service"
echo "  lsblk"