#!/usr/bin/env python3
"""
utils.imaging_pipeline
======================

Encapsulate the post-processing pipeline for a single scratch capture produced by
PiCamera with ``bayer=True``.

The pipeline performs:

- Read scratch JPG and preserve its EXIF block
- Paste overlay banner onto the RGB pixels
- Save the final composed JPEG (with EXIF preserved)
- Append the *raw Bayer tail* from the scratch file to the final JPEG
- Create a thumbnail
- Delete the scratch file (optional)

Important note about the Bayer tail
-----------------------------------
On our current GONet camera deployment, PiCamera writes a JPEG stream followed by
a fixed-length Bayer tail appended to the end of the file.

For this setup we treat the tail size as a constant:

    TAIL_BYTES = 18_711_040

This keeps the post-processing fast (Pi Zero friendly) and matches the legacy
assumption used by downstream raw parsing utilities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


# =============================================================================
# Constants
# =============================================================================

# Fixed tail length for this hardware/software deployment.
TAIL_BYTES: int = 18_711_040


# =============================================================================
# Data containers
# =============================================================================

@dataclass(frozen=True)
class ProcessResult:
    """
    ProcessResult
    -------------

    Result container for post-processing a single image.

    Parameters
    ----------
    ok : bool
        True if the pipeline completed successfully.
    message : str
        Human-readable summary for logs.
    bayer_tail_bytes : int
        Size (bytes) of Bayer tail appended to the output file.
    """
    ok: bool
    message: str
    bayer_tail_bytes: int = 0


# =============================================================================
# Tail helpers
# =============================================================================

def _get_tail_start_offset_fixed(path: Path) -> tuple[int | None, int]:
    """
    Return (tail_start_offset, tail_len) using the fixed tail length.

    Parameters
    ----------
    path : Path
        Scratch JPEG path.

    Returns
    -------
    (int | None, int)
        (tail_start, TAIL_BYTES). If the file is too small, returns (None, 0).
    """
    try:
        file_size = path.stat().st_size
    except Exception:
        return (None, 0)

    if file_size <= TAIL_BYTES:
        return (None, 0)

    tail_start = file_size - TAIL_BYTES
    return (tail_start, TAIL_BYTES)


def _append_tail_streaming(
    *,
    scratch_path: Path,
    out_full: Path,
    tail_start: int,
    logger: logging.Logger,
    chunk_size: int = 1024 * 1024,
) -> None:
    """
    Append bytes [tail_start:EOF] from scratch_path into out_full using streaming IO.

    Parameters
    ----------
    scratch_path : Path
        Input scratch file containing JPEG stream + Bayer tail.
    out_full : Path
        Output full-size JPEG to append the tail to (opened in append mode).
    tail_start : int
        Byte offset in scratch_path at which the tail begins.
    logger : logging.Logger
        Logger for reporting.
    chunk_size : int
        Streaming chunk size in bytes.
    """
    with scratch_path.open("rb") as fin, out_full.open("ab") as fout:
        fin.seek(tail_start, 0)
        while True:
            buf = fin.read(chunk_size)
            if not buf:
                break
            fout.write(buf)

    logger.info("bayer tail: appended %d bytes from offset=%d", TAIL_BYTES, tail_start)


# =============================================================================
# Public API
# =============================================================================

def process_one_image(
    *,
    scratch_path: Path,
    overlay_path: Path,
    out_full: Path,
    out_thumb: Path,
    logger: logging.Logger,
    thumb_size: tuple[int, int] = (160, 120),
    delete_scratch: bool = True,
) -> ProcessResult:
    """
    Post-process one scratch capture into final products.

    Parameters
    ----------
    scratch_path : Path
        Input scratch JPG path produced by PiCamera (expected to contain Bayer tail).
    overlay_path : Path
        Overlay banner JPEG path (foreground image).
    out_full : Path
        Destination full-size JPEG path.
    out_thumb : Path
        Destination thumbnail JPEG path.
    logger : logging.Logger
        Logger for reporting.
    thumb_size : tuple[int, int]
        Thumbnail size (max width/height).
    delete_scratch : bool
        If True, delete the scratch file after processing (fail-open if deletion fails).

    Returns
    -------
    ProcessResult
        Outcome of processing (cron-safe: ok=False on failure, no raised exceptions).
    """
    try:
        # ---------------------------------------------------------------------
        # 1) Read scratch image and preserve EXIF
        # ---------------------------------------------------------------------
        # We preserve EXIF from the scratch file because PiCamera wrote it.
        background = Image.open(str(scratch_path)).convert("RGB")
        exif = background.info.get("exif", b"")

        # ---------------------------------------------------------------------
        # 2) Paste overlay banner
        # ---------------------------------------------------------------------
        overlay = Image.open(str(overlay_path))
        background.paste(overlay, (0, 0))

        # ---------------------------------------------------------------------
        # 3) Save composed JPEG with EXIF preserved
        # ---------------------------------------------------------------------
        out_full.parent.mkdir(parents=True, exist_ok=True)
        background.save(str(out_full), "JPEG", exif=exif)

        # ---------------------------------------------------------------------
        # 4) Append fixed-size Bayer tail (streaming, no big RAM)
        # ---------------------------------------------------------------------
        tail_start, tail_len = _get_tail_start_offset_fixed(scratch_path)
        if tail_start is None or tail_len == 0:
            logger.warning(
                "bayer tail: file too small for fixed tail. file=%s expected_tail_bytes=%d",
                scratch_path,
                TAIL_BYTES,
            )
            tail_len = 0
        else:
            _append_tail_streaming(
                scratch_path=scratch_path,
                out_full=out_full,
                tail_start=tail_start,
                logger=logger,
            )

        # ---------------------------------------------------------------------
        # 5) Thumbnail (use composited pixels already in memory)
        # ---------------------------------------------------------------------
        out_thumb.parent.mkdir(parents=True, exist_ok=True)
        thumb = background.copy()
        thumb.thumbnail(thumb_size)
        thumb.save(str(out_thumb), "JPEG")

        # ---------------------------------------------------------------------
        # 6) Optional scratch cleanup
        # ---------------------------------------------------------------------
        if delete_scratch:
            try:
                scratch_path.unlink()
            except Exception:
                logger.exception("cleanup: failed removing scratch file: %s", scratch_path)

        return ProcessResult(
            ok=True,
            message="ok",
            bayer_tail_bytes=tail_len,
        )

    except Exception as e:
        logger.exception("Post-processing failed for scratch=%s out_full=%s", scratch_path, out_full)
        return ProcessResult(ok=False, message=f"{e!r}")