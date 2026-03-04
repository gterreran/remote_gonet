from __future__ import annotations

import logging
import os
from pathlib import Path

SCRATCH_DIR = Path("/home/pi/Tools/Camera/scratch")
IMAGE_DIR = Path("/home/pi/images")
THUMBS_DIR = Path("/home/pi/_sfpg_data/thumb")

VERSION_DIR = Path("/home/pi/Tools/Version")

LENS_STATUS_DIR = Path("/home/pi/Tools/LensStatus/Status")

DISK_FREE_THRESHOLD = 10.0

def ensure_dirs(
    *,
    logger: logging.Logger,
) -> None:
    """
    Ensure required directories exist.

    Notes
    -----
    This isolates the directory-creation side effects from the main flow, and
    reports what it did to the rotating log.
    """
    for d in (SCRATCH_DIR, IMAGE_DIR, THUMBS_DIR):
        if d.exists():
            if d.is_dir():
                logger.info("dir exists: %s", d)
            else:
                # Rare but important: a file exists where we need a directory.
                # We do not attempt to fix automatically (fail-open, but noisy).
                logger.error("path exists but is not a directory: %s", d)
        else:
            d.mkdir(parents=True, exist_ok=True)
            logger.info("created dir: %s", d)


def recover_scratch_leftovers(
    *,
    logger: logging.Logger,
) -> None:
    """
    Crash-recovery step: clean scratch before a new run.

    What it does
    ------------
    - Deletes zero-length files (likely incomplete/corrupt writes).
    - Moves leftover .jpg files from scratch -> IMAGE_DIR.

    Why it exists
    -------------
    If the previous run crashed after capture but before post-processing, scratch
    may contain valid images. We fail-open and move them so data is not lost.
    These moved leftovers will *not* have the overlay/thumbs, consistent with
    the legacy behavior you preserved.

    Returns
    -------
    None
    """
    zero_length_deleted: list[str] = []
    leftovers_moved: list[str] = []

    if not SCRATCH_DIR.exists():
        logger.warning("scratch dir does not exist yet (will be created later): %s", SCRATCH_DIR)

    # 1) Remove zero-length files
    for p in SCRATCH_DIR.iterdir():
        if not p.is_file():
            continue
        try:
            if p.stat().st_size == 0:
                zero_length_deleted.append(p.name)
                logger.warning("scratch recovery: deleting zero-length file: %s", p)
                try:
                    p.unlink()
                except Exception:
                    logger.exception("scratch recovery: failed deleting: %s", p)
        except Exception:
            logger.exception("scratch recovery: failed stat(): %s", p)

    # 2) Move leftover jpgs
    for p in SCRATCH_DIR.iterdir():
        if not (p.is_file() and p.suffix.lower() == ".jpg"):
            continue

        dst = IMAGE_DIR / p.name
        leftovers_moved.append(p.name)
        logger.warning("scratch recovery: moving leftover jpg: %s -> %s", p, dst)
        try:
            p.rename(dst)
        except Exception:
            logger.exception("scratch recovery: failed moving: %s -> %s", p, dst)

    if zero_length_deleted or leftovers_moved:
        logger.warning(
            "scratch recovery summary: deleted_zero_length=%d moved_leftovers=%d",
            len(zero_length_deleted),
            len(leftovers_moved),
        )
    else:
        logger.info("scratch recovery: scratch clean (no leftovers)")


def version_check() -> str:
    """
    Check for version file and log it.

    Returns
    -------
    str        Version string from the version file, or "UNK" if unknown.
    
    """
    version = "UNK"
    try:
        version_files = list(VERSION_DIR.glob("*"))
        if version_files:
            version = version_files[0].name
    except Exception:
        pass

    return version


def cap_check() -> str:
    """
    Check for lens cap status and log it.

    Returns
    -------
    str        Lens cap status, e.g. "On" or "Off". "UNK" if unknown.
    
    """
    lenscap = "UNK"
    try:
        cap = list(LENS_STATUS_DIR.glob("*"))
        if cap:
            lenscap = cap[0].name
    except Exception:
        pass

    return lenscap
    

def check_free_space(path: Path, logger: logging.Logger) -> bool:
    """
    Return 'percent free' as computed by the legacy code.

    Parameters
    ----------
    path
        Path to filesystem to query.

    Returns
    -------
    bool
        True if sufficient free space, False if low disk space.
    logger
        Logger for reporting disk space status.
    """
    disk = os.statvfs(str(path))
    pct_free = (disk.f_bavail * 100.0) / disk.f_blocks
    logger.info("disk pct_free=%.2f threshold=%.2f path=%s", pct_free, DISK_FREE_THRESHOLD, path)
    return pct_free >= DISK_FREE_THRESHOLD

