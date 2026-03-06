#!/usr/bin/env python3
"""
utils.setup
===========

Small setup + safety utilities used by gonet4.py:

- Ensure required directories exist
- Recover leftover scratch files (crash-safe)
- Read "version" and "lens cap" status markers
- Check filesystem free space before imaging

Free-space policy
-----------------
We use a **minimum free-bytes threshold** (not percent) to avoid surprises on
small/large filesystems.

Default policy:
    MIN_FREE_BYTES = 200 MiB

`gonet4.py` should check:
- the SD card ("/") always
- the USB mount too **when --flashdrive-copy is enabled**
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


# =============================================================================
# Paths
# =============================================================================

SCRATCH_DIR = Path("/home/pi/Tools/Camera/scratch")
IMAGE_DIR = Path("/home/pi/images")
THUMBS_DIR = Path("/home/pi/_sfpg_data/thumb")

VERSION_DIR = Path("/home/pi/Tools/Version")
LENS_STATUS_DIR = Path("/home/pi/Tools/LensStatus/Status")

MIN_FREE_BYTES: int = 200 * 1024 * 1024  # 200 MiB


# =============================================================================
# Directory setup
# =============================================================================

def ensure_dirs(*, logger: logging.Logger) -> None:
    """
    Ensure required directories exist.
    """
    for d in (SCRATCH_DIR, IMAGE_DIR, THUMBS_DIR):
        if d.exists():
            if d.is_dir():
                logger.info("dir exists: %s", d)
            else:
                logger.error("path exists but is not a directory: %s", d)
        else:
            d.mkdir(parents=True, exist_ok=True)
            logger.info("created dir: %s", d)


def recover_scratch_leftovers(*, logger: logging.Logger) -> None:
    """
    Crash-recovery step: clean scratch before a new run.

    What it does
    ------------
    - Deletes zero-length files (likely incomplete/corrupt writes).
    - Moves leftover .jpg files from scratch -> IMAGE_DIR.
    """
    zero_length_deleted = 0
    leftovers_moved = 0

    if not SCRATCH_DIR.exists():
        logger.warning("scratch dir does not exist yet (will be created later): %s", SCRATCH_DIR)
        return

    # 1) Remove zero-length files
    for p in SCRATCH_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            if p.stat().st_size == 0:
                logger.warning("scratch recovery: deleting zero-length file: %s", p)
                try:
                    p.unlink()
                    zero_length_deleted += 1
                except Exception:
                    logger.exception("scratch recovery: failed deleting: %s", p)
        except Exception:
            logger.exception("scratch recovery: failed stat(): %s", p)

    # 2) Move leftover jpgs
    for p in SCRATCH_DIR.iterdir():
        if not (p.is_file() and p.suffix.lower() == ".jpg"):
            continue

        dst = IMAGE_DIR / p.name
        logger.warning("scratch recovery: moving leftover jpg: %s -> %s", p, dst)
        try:
            p.rename(dst)
            leftovers_moved += 1
        except Exception:
            logger.exception("scratch recovery: failed moving: %s -> %s", p, dst)

    if zero_length_deleted or leftovers_moved:
        logger.warning(
            "scratch recovery summary: deleted_zero_length=%d moved_leftovers=%d",
            zero_length_deleted,
            leftovers_moved,
        )
    else:
        logger.info("scratch recovery: scratch clean (no leftovers)")


# =============================================================================
# Status markers
# =============================================================================

def version_check() -> str:
    """
    Return version string from VERSION_DIR, or "UNK" if unknown.
    """
    try:
        version_files = list(VERSION_DIR.glob("*"))
        if version_files:
            return version_files[0].name
    except Exception:
        pass
    return "UNK"


def cap_check() -> str:
    """
    Return lens cap status from LENS_STATUS_DIR, or "UNK" if unknown.
    """
    try:
        caps = list(LENS_STATUS_DIR.glob("*"))
        if caps:
            return caps[0].name
    except Exception:
        pass
    return "UNK"


# =============================================================================
# Disk space checks
# =============================================================================

def _format_bytes(n: int) -> str:
    """
    Human-readable bytes (MiB/GiB) for logs.
    """
    if n >= 1024**3:
        return f"{n / (1024**3):.2f} GiB"
    return f"{n / (1024**2):.1f} MiB"


def check_free_space(
    path: Path,
    *,
    logger: logging.Logger,
) -> bool:
    """
    Check that the filesystem containing `path` has at least `min_free_bytes` available.

    Parameters
    ----------
    path
        Any path on the filesystem you want to check (e.g. Path("/") or Path("/media/pi/usb")).
    logger
        Logger for reporting.

    Returns
    -------
    bool
        True if sufficient space, False otherwise.
    """
    try:
        st = os.statvfs(str(path))
        free_bytes = int(st.f_bavail) * int(st.f_frsize)
        total_bytes = int(st.f_blocks) * int(st.f_frsize)
        pct_free = (free_bytes * 100.0 / total_bytes) if total_bytes > 0 else 0.0

        logger.info(
            "disk free path=%s free=%s (%.2f%%) required>=%s",
            path,
            _format_bytes(free_bytes),
            pct_free,
            _format_bytes(MIN_FREE_BYTES),
        )

        return free_bytes >= int(MIN_FREE_BYTES)

    except Exception as e:
        logger.exception("disk free check failed path=%s error=%r", path, e)
        # Fail-open: do not block imaging because statvfs failed
        return True
