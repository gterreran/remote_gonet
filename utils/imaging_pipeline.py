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

Why this module exists
----------------------
Keeping these mechanics here lets ``gonet4.py`` remain a readable orchestration
layer (status markers, GPS/config, capture loop), while all file/JPEG/Bayer
details live in one place.

Important reliability change (vs legacy)
----------------------------------------
Historically, the pipeline used a hard-coded ``BAYER_TAIL_BYTES`` constant and
executed ``tail -c`` to extract the last N bytes.

That is brittle because the appended Bayer blob size can change with camera model,
sensor mode, resolution, firmware, or PiCamera version.

This refactor removes the magic number by using the JPEG structure itself:
we locate the final JPEG end-of-image marker (EOI, bytes ``FF D9``) and treat
*everything after that marker* as the Bayer tail.

This is robust as long as PiCamera continues the documented behavior of appending
Bayer data after the JPEG stream terminator.

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


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
        Total size (bytes) of data detected after JPEG EOI. If 0, no tail found.
    bayer_payload_bytes : int
        Size (bytes) of Bayer "payload" used for unpacking. This may be smaller
        than bayer_tail_bytes if a header is detected and stripped.
    """
    ok: bool
    message: str
    bayer_tail_bytes: int = 0
    bayer_payload_bytes: int = 0


# =============================================================================
# JPEG / tail extraction helpers
# =============================================================================

_JPEG_EOI: bytes = b"\xFF\xD9"
_BRCM_MAGIC: bytes = b"BRCM"
_BRCM_HEADER_LEN: int = 32_768


def _find_jpeg_eoi_offset(path: Path, *, chunk_size: int = 1_048_576) -> int | None:
    """
    Find the byte offset of the *last* JPEG EOI marker (0xFF, 0xD9).

    Parameters
    ----------
    path : Path
        Path to the scratch JPEG.
    chunk_size : int
        How many bytes to read per backward step. Default is 1 MiB.

    Returns
    -------
    int | None
        Offset of the last EOI marker start (the position of 0xFF in 0xFF 0xD9),
        or None if no marker is found.

    Notes
    -----
    We search backwards to avoid reading the whole file into memory.
    We search for the *last* EOI to reduce the chance of a false match.
    """
    with path.open("rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        if file_size < 2:
            return None

        overlap = 1
        window_end = file_size
        window_start = max(0, window_end - chunk_size)

        while True:
            f.seek(window_start, 0)
            buf = f.read(window_end - window_start)

            idx = buf.rfind(_JPEG_EOI)
            if idx != -1:
                return window_start + idx

            if window_start == 0:
                return None

            window_end = window_start + overlap
            window_start = max(0, window_end - chunk_size)


def _extract_tail_after_eoi(path: Path) -> bytes:
    """
    Extract all bytes after the final JPEG EOI marker.

    Parameters
    ----------
    path : Path
        Scratch JPG path produced by PiCamera.

    Returns
    -------
    bytes
        Tail bytes after EOI. If EOI not found, returns b"".
    """
    eoi_off = _find_jpeg_eoi_offset(path)
    if eoi_off is None:
        return b""

    tail_start = eoi_off + 2  # EOI is 2 bytes long
    with path.open("rb") as f:
        f.seek(tail_start, 0)
        return f.read()


def _extract_bayer_payload_from_tail(tail: bytes, *, logger: logging.Logger | None = None) -> bytes:
    """
    Attempt to extract the raw Bayer *payload* from the tail.

    PiCamera Bayer tails often include a header containing the ASCII magic "BRCM".
    The exact layout can vary, but in many deployments:

        tail = header (32k) + payload (packed 12-bit)

    However, some variants place the header elsewhere. We therefore implement a
    best-effort approach:

    - Search for "BRCM" inside the tail
    - If found and there are >= 32k bytes available from that position:
        - Consider bytes after that 32k block as payload (if non-empty)
    - Otherwise, treat the entire tail as payload

    Parameters
    ----------
    tail : bytes
        Tail bytes after JPEG EOI.
    logger : logging.Logger | None
        Optional logger for debug-level messages.

    Returns
    -------
    bytes
        Payload bytes to be interpreted as packed 12-bit samples.
    """
    if not tail:
        return b""

    idx = tail.find(_BRCM_MAGIC)
    if idx != -1:
        # If we can take a 32k header starting at idx, payload starts after it.
        hdr_end = idx + _BRCM_HEADER_LEN
        if hdr_end < len(tail):
            payload = tail[hdr_end:]
            if payload:
                if logger is not None:
                    logger.info(
                        "bayer tail: detected BRCM header at offset=%d, header_len=%d, payload_len=%d",
                        idx,
                        _BRCM_HEADER_LEN,
                        len(payload),
                    )
                return payload

    # Fall back: treat entire tail as payload
    if logger is not None:
        logger.info(
            "bayer tail: no usable BRCM header detected; using full tail as payload. tail_len=%d",
            len(tail),
        )
    return tail


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
        # 4) Extract Bayer tail (reliable) + append it to output
        # ---------------------------------------------------------------------
        tail = _extract_tail_after_eoi(scratch_path)
        tail_len = len(tail)

        if tail_len == 0:
            logger.warning("bayer tail: none detected after JPEG EOI. file=%s", scratch_path)
            payload = b""
            payload_len = 0
        else:
            payload = _extract_bayer_payload_from_tail(tail, logger=logger)
            payload_len = len(payload)

            # Append the *entire tail* (not payload) to preserve full legacy artifact.
            # This keeps compatibility with existing downstream tools that expect the
            # original appended blob, including any header.
            with out_full.open("ab") as fout:
                fout.write(tail)

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
            bayer_payload_bytes=payload_len,
        )

    except Exception as e:
        logger.exception("Post-processing failed for scratch=%s out_full=%s", scratch_path, out_full)
        return ProcessResult(ok=False, message=f"{e!r}")