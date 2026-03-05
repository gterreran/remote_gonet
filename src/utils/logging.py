# /home/pi/Tools/Camera/utils/logging.py
from __future__ import annotations

"""
utils.logging
=============

- Status marker creation (wipe + touch)
- Python logging setup with rotation (file always, optional console)

Design notes
------------
- Console output is optional and controlled via setup_logger(console=...).

"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# -----------------------------------------------------------------------------
# Canonical paths
# -----------------------------------------------------------------------------

STATUS_DIR = Path("/home/pi/Tools/Status")
DEFAULT_LOG_PATH = Path("/home/pi/Tools/Camera/gonet.log")


def set_status(name: str) -> None:
    """
    Replace contents of /home/pi/Tools/Status with a single marker file.

    This preserves the legacy behavior used by existing monitoring workflows.

    Parameters
    ----------
    name
        Marker filename to create, e.g. "Imaging", "Post", "Ready".
    """
    STATUS_DIR.mkdir(parents=True, exist_ok=True)

    # Keep original behavior: async subshell to avoid blocking.
    os.system(f"(rm -rf {STATUS_DIR}/*; touch {STATUS_DIR}/{name}) &")


def setup_logger(
    *,
    name: str,
    level: int = logging.INFO,
    console: bool = True,
    max_bytes: int = 4_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """
    Configure and return a logger that writes to a rotating log file and optionally console.

    Parameters
    ----------
    name
        Logger name.
    level
        Logging level (e.g. logging.INFO).
    console
        If True, also log to stdout (useful for interactive runs).
        If False, suppress stdout/stderr noise (ideal for cron).
    max_bytes
        Rotate the log when it reaches this size.
    backup_count
        Keep this many rotated logs (log.1, log.2, ...).

    Returns
    -------
    logging.Logger
        Configured logger.
    """
    DEFAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers if main() is called twice or imported.
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    fh = RotatingFileHandler(
        filename=str(DEFAULT_LOG_PATH),
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if console:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    logger.propagate = False
    return logger