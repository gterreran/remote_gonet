#!/usr/bin/env python3
"""
utils.transfer
==============

Copy/migrate images from SD to a mounted USB drive with robust verification.

Design
------
- Fail-open: if USB isn't available, do nothing and return ok=False.
- Safe copy: write to ".part", verify, then atomic rename to final.
- Verification: size + chunk hashes (default) or full sha256.

"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


USB_MOUNTPOINT = Path("/media/pi/usb")
USB_MARKER = USB_MOUNTPOINT / ".gonet_usb"

# Default destination roots on USB
USB_IMAGE_ROOT = USB_MOUNTPOINT / "GONetDump/images"

# Chunk hashing defaults (fast but robust)
_HASH_BLOCK = 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class TransferResult:
    ok: bool
    message: str
    copied: int = 0
    deleted: int = 0
    failed: int = 0


def _is_mountpoint(path: Path) -> bool:
    """Return True if path is a mountpoint (no subprocess dependency)."""
    try:
        return path.is_dir() and (path.stat().st_dev != path.parent.stat().st_dev)
    except Exception:
        return False


def usb_available(*, logger: logging.Logger) -> bool:
    if not USB_MOUNTPOINT.exists():
        logger.info("usb: mountpoint missing: %s", USB_MOUNTPOINT)
        return False
    if not _is_mountpoint(USB_MOUNTPOINT):
        logger.info("usb: not mounted at: %s", USB_MOUNTPOINT)
        return False
    if not USB_MARKER.exists():
        logger.info("usb: marker missing: %s", USB_MARKER)
        return False
    return True


def _hash_full(path: Path, *, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _hash_sampled(path: Path) -> str:
    """
    Hash 3 chunks: start, middle, end. Stronger than size+mtime, much cheaper than full hash.
    """
    size = path.stat().st_size
    if size == 0:
        return "EMPTY"

    offsets: list[int] = [0]

    mid = max(0, (size // 2) - (_HASH_BLOCK // 2))
    offsets.append(mid)

    end = max(0, size - _HASH_BLOCK)
    offsets.append(end)

    h = hashlib.blake2b(digest_size=32)
    with path.open("rb") as f:
        for off in offsets:
            f.seek(off, 0)
            chunk = f.read(_HASH_BLOCK)
            h.update(off.to_bytes(8, "little", signed=False))
            h.update(len(chunk).to_bytes(8, "little", signed=False))
            h.update(chunk)
    # Include total size so same sampled bytes at different size won't collide easily
    h.update(size.to_bytes(8, "little", signed=False))
    return h.hexdigest()


def _verify(
    src: Path,
    dst: Path,
    *,
    mode: str,
) -> bool:
    if src.stat().st_size != dst.stat().st_size:
        return False

    if mode == "none":
        return True
    if mode == "sampled":
        return _hash_sampled(src) == _hash_sampled(dst)
    if mode == "sha256":
        return _hash_full(src, algo="sha256") == _hash_full(dst, algo="sha256")

    raise ValueError(f"Unknown verify mode: {mode!r}")


def copy_verify_delete(
    *,
    src: Path,
    dst: Path,
    logger: logging.Logger,
    verify: str = "sampled",  # "sampled" | "sha256" | "none"
    delete_src: bool = True,
) -> tuple[bool, str]:
    """
    Copy src -> dst safely:
      dst.part is written first,
      verify src vs dst.part,
      atomic rename to dst,
      delete src if requested.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")

    try:
        # 1) copy to .part
        shutil.copyfile(src, tmp)

        # 2) verify .part
        if not _verify(src, tmp, mode=verify):
            try:
                tmp.unlink()
            except Exception:
                pass
            return (False, f"verify failed ({verify})")

        # 3) atomic finalize
        tmp.replace(dst)

        # 4) delete src
        if delete_src:
            src.unlink()

        return (True, "ok")

    except Exception as e:
        logger.exception("transfer failed src=%s dst=%s", src, dst)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return (False, repr(e))


def migrate_many(
    *,
    sources: Iterable[Path],
    logger: logging.Logger,
    verify: str = "sampled",
    delete_src: bool = True,
) -> TransferResult:
    if not usb_available(logger=logger):
        return TransferResult(ok=False, message="usb not available", copied=0, deleted=0, failed=0)

    copied = 0
    deleted = 0
    failed = 0

    for src in sources:
        if not src.exists() or not src.is_file():
            continue

        dst = USB_IMAGE_ROOT / src.name
        ok, msg = copy_verify_delete(src=src, dst=dst, logger=logger, verify=verify, delete_src=delete_src)

        if ok:
            copied += 1
            if delete_src:
                deleted += 1
            logger.info("migrate ok %s -> %s", src, dst)
        else:
            failed += 1
            logger.error("migrate FAIL %s -> %s (%s)", src, dst, msg)

    return TransferResult(
        ok=(failed == 0),
        message="ok" if failed == 0 else "some transfers failed",
        copied=copied,
        deleted=deleted,
        failed=failed,
    )