#!/usr/bin/env python3
"""
gonet4.py
=========

Hardware
--------
Camera Module:
    Raspberry Pi 2018 HQ Camera v1.0

Image Sensor:
    Sony IMX477 (back-illuminated CMOS)

Key Sensor Characteristics:
    • Native ADC depth: 12 bits
    • Maximum ADC value: 4095
    • Native full resolution: 4056 x 3040 pixels
    • Pixel size: 1.55 µm
    • Rolling shutter
    • RAW Bayer output available (12-bit packed)

Software Stack
--------------
Operating system uses the legacy MMAL camera pipeline
(bcm2835-v4l2 + firmware-based ISP).

Images are captured using the legacy `picamera` library:

    from picamera import PiCamera
    camera = PiCamera(sensor_mode=3)

In this configuration:
    • JPEG outputs are 8-bit per channel (ISP processed).
    • RAW Bayer data appended via `bayer=True` is 12-bit packed.
    • RAW values span the physical ADC range [0, 4095].

Bit Depth Notes
---------------
The IMX477 operates in 12-bit ADC mode in this pipeline.
RAW Bayer values represent true 12-bit sensor data
(not 10-bit data upscaled to 12-bit).

Saturation in RAW data corresponds to values near 4095.
This is the physically meaningful saturation threshold.

Sensor Modes (IMX477, legacy stack)
------------------------------------

Mode 0:
    Resolution: 4056 x 3040
    Full field of view
    Low frame rate
    12-bit ADC
    No binning

Mode 1:
    Resolution: 2028 x 1520
    2x2 analog binning
    Full field of view
    Higher frame rate
    12-bit ADC

Mode 2:
    Resolution: 2028 x 1080
    Cropped vertically (reduced FOV)
    Higher frame rate
    12-bit ADC

Mode 3 (used in GONet):
    Resolution: 4056 x 3040
    Full field of view
    Optimized still mode
    12-bit ADC
    No binning
    Maximum dynamic range

Mode 4:
    Resolution: 1332 x 990
    Heavy binning / high-speed mode
    Reduced spatial resolution
    12-bit ADC

Mode 5:
    Resolution: 2028 x 1080
    Alternative video timing configuration
    12-bit ADC

GONet Configuration
-------------------
Current configuration uses:

    sensor_mode = 3

Therefore:
    • Full-resolution readout (4056 x 3040)
    • Full sensor field of view
    • True 12-bit raw Bayer acquisition
    • RAW saturation threshold ≈ 4095
    • JPEG output remains 8-bit ISP-processed

For physically meaningful saturation analysis,
RAW Bayer values should be used rather than JPEG values.
"""

from __future__ import annotations

import argparse
import logging
import socket
import time
import os
from fractions import Fraction
from pathlib import Path
from time import gmtime, sleep, strftime

from utils.config import AcquisitionConfig, resolve_config_from_cli
from utils.gps import acquire_gps_fix
from utils.imaging_meta import build_run_meta, write_overlay_banner
from utils.imaging_pipeline import process_one_image
from utils.logging import set_status, setup_logger
from utils.setup import ensure_dirs, recover_scratch_leftovers, version_check, cap_check, check_free_space
from utils.setup import SCRATCH_DIR, IMAGE_DIR, THUMBS_DIR

# =============================================================================
# Helpers
# =============================================================================

def parse_args() -> argparse.Namespace:
    """
    Parse gonet4.py-specific arguments.

    We keep this separate from the acquisition config system. The acquisition
    config is still resolved via resolve_config_from_cli().

    Returns
    -------
    argparse.Namespace
        Parsed args with attribute `quiet`.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output (still writes rotating log + status files).",
    )
    p.add_argument(
        "--flashdrive-copy",
        action="store_true",
        help="Copy images to flashdrive after capture.",
    )
    p.add_argument(
        "--sun-gate",
        action="store_true",
        help="Enable sun gate feature to skip imaging during daytime.",
    )
    args, _ = p.parse_known_args()
    return args


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    args = parse_args()

    logger = setup_logger(
        name="gonet4",
        level=logging.INFO,
        console=(not args.quiet),
    )

    t_start = time.perf_counter()

    # Resolve acquisition config (defaults + config file + CLI overrides)
    cfg: AcquisitionConfig = resolve_config_from_cli()

    logger.info(
    "config source=%s shutter_speeds_us=%s ISO=%d number_of_images=%d use_gps=%s total_images=%d",
    cfg.source,
    ",".join(str(x) for x in cfg.shutter_speed),
    cfg.iso,
    cfg.number_of_images,
    cfg.use_gps,
    len(cfg.shutter_speed) * cfg.number_of_images,
)

    set_status("Param")

    # Monkey patch PiCamera CAPTURE_TIMEOUT (legacy behavior)
    from picamera import PiCamera
    logger.info("PiCamera.CAPTURE_TIMEOUT before=%s", getattr(PiCamera, "CAPTURE_TIMEOUT", "UNK"))
    PiCamera.CAPTURE_TIMEOUT = 600
    logger.info("PiCamera.CAPTURE_TIMEOUT after=%s", getattr(PiCamera, "CAPTURE_TIMEOUT", "UNK"))

    if not check_free_space(Path("/"), logger=logger):
        set_status("Disk_Full")
        os.system("(crontab -r) &")
        return 1

    # -------------------------------------------------------------------------
    # GPS acquisition (fail-open)
    # -------------------------------------------------------------------------
    fix = acquire_gps_fix(use_gps=cfg.use_gps, set_status=set_status)
    gps_acquire_time = fix.acquire_seconds

    if fix.ok:
        gps_ok = True
        gps_mode = fix.gps_mode
        latitude = fix.latitude
        longitude = fix.longitude
        altitude = fix.altitude
        logger.info("GPS ok mode=%d lat=%.6f lon=%.6f alt=%.2f acquire=%.3fs", gps_mode, latitude, longitude, altitude, gps_acquire_time)
    else:
        gps_ok = False
        gps_mode = fix.gps_mode
        latitude = 0.0
        longitude = 0.0
        altitude = 0.0
        cfg.use_gps = False  # ensures overlay says GPS BYPASSED
        logger.warning("GPS not ok. proceed fail-open. mode=%d msg=%s acquire=%.3fs", gps_mode, fix.message, gps_acquire_time)


    # --------------------------------------------------------------------
    # SUN GATE (skip imaging in daytime; fail-open = image if anything breaks)
    # --------------------------------------------------------------------
    if fix.ok and args.sun_gate:
        try:
            from utils.sun_gate import should_image_now

            if not should_image_now(fix=fix, logger=logger):
                logger.info("Sun gate: skip imaging (daytime)")
                set_status("SunUp")
                return 0


        except Exception as e:
            # Philosophy: better to take images than to miss them.
            logger.exception("Sun gate check failed, proceeding with imaging. error=%s", e)
    # --------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Version + lenscap status
    # -------------------------------------------------------------------------

    version = version_check()
    lenscap = cap_check()

    # Ensure directories exist
    set_status("CreateDirs")
    ensure_dirs(logger=logger)

    # Cleanup scratch: remove zero-length and move leftover JPGs (legacy behavior)
    recover_scratch_leftovers(logger=logger)

    # Run timestamps (legacy naming)
    log_start_of_run_time = strftime("%Y-%m-%d %H:%M:%S", gmtime())
    start_of_run_time = strftime("%H%M%S", gmtime())
    logger.info("Start_of_run_time=%s", log_start_of_run_time)

    hostname = socket.gethostname()

    # -------------------------------------------------------------------------
    # Imaging (capture)
    # -------------------------------------------------------------------------

    set_status("Imaging")
    t_imaging0 = time.perf_counter()

    try:
        camera = PiCamera(sensor_mode=3)
        sleep(1)
        camera.framerate_range = (Fraction(1, 100), Fraction(1, 2))
        camera.iso = cfg.iso
        camera.drc_strength = cfg.drc
        camera.awb_gains = cfg.white_balance_gains
        camera.brightness = cfg.brightness
        camera.still_stats = True
        camera.resolution = (4056, 3040)
        camera.exposure_mode = "off"
        camera.stop_preview()
        camera.awb_mode = "off"
    except Exception:
        logger.exception("Camera init failed.")
        set_status("Camera_Error")
        return 1

    captured_files: list[tuple[Path, Path]] = []  # (scratch_path, overlay_path)

    for shutter_speed in cfg.shutter_speed:
        camera.shutter_speed = shutter_speed

        for i in range(cfg.number_of_images):
            filename = (
                hostname[-3:]
                + "_"
                + strftime("%y%m%d_", gmtime())
                + start_of_run_time
                + strftime("_%s", gmtime())
                + ".jpg"
            )
            out_path = SCRATCH_DIR / filename

            # -----------------------------------------------------------------
            # Build per-image metadata + per-image overlay banner
            # -----------------------------------------------------------------
            meta = build_run_meta(
                hostname=hostname,
                version=version,
                shutter_speed=shutter_speed,
                iso=cfg.iso,
                white_balance_gains=cfg.white_balance_gains,
                gps_ok=gps_ok,
                gps_mode=gps_mode,
                latitude=latitude,
                longitude=longitude,
                altitude=altitude,
                lenscap=lenscap,
            )

            # Unique overlay per IMAGE (not just per exposure)
            # This prevents reuse and ensures the timestamp in the overlay updates.
            foreground_path = SCRATCH_DIR / f"foreground_{out_path.stem}.jpeg"
            write_overlay_banner(text=meta.overlay_text, out_path=foreground_path)

            # Apply camera EXIF tags from meta (centralized)
            for k, v in meta.camera_exif_tags.items():
                camera.exif_tags[k] = v

            logger.info(
                "capture exp_us=%d (%d/%d) -> %s overlay=%s",
                shutter_speed,
                i + 1,
                cfg.number_of_images,
                out_path,
                foreground_path,
            )

            camera.capture(str(out_path), bayer=True)

            captured_files.append((out_path, foreground_path))

    camera.close()

    imaging_time = time.perf_counter() - t_imaging0
    logger.info("imaging_time=%.3fs", imaging_time)

    # -------------------------------------------------------------------------
    # Post-processing (ONLY what we captured this run)
    # -------------------------------------------------------------------------
    set_status("Post")
    t_post0 = time.perf_counter()

    processed_files: list[str] = []
    ok_count = 0

    for p, overlay_path in captured_files:
        out_full = IMAGE_DIR / p.name
        out_thumb = THUMBS_DIR / p.name

        logger.info("postprocess scratch=%s out_full=%s out_thumb=%s overlay=%s", p, out_full, out_thumb, overlay_path)

        res = process_one_image(
            scratch_path=p,
            overlay_path=overlay_path,
            out_full=out_full,
            out_thumb=out_thumb,
            logger=logger,
            delete_scratch=True,
        )

        if res.ok:
            ok_count += 1
            processed_files.append(p.name)
            # remove per-image overlay banner
            try:
                overlay_path.unlink()
            except Exception:
                logger.exception("cleanup: failed removing overlay banner: %s", overlay_path)
        else:
            logger.error("postprocess failed file=%s msg=%s", p, res.message)

    post_time = time.perf_counter() - t_post0

    logger.info("post_time=%.3fs processed_ok=%d/%d", post_time, ok_count, len(captured_files))

    for fn in processed_files:
        logger.info("processed_file %s", fn)

    mig_time = 0.0
    if args.flashdrive_copy:
        from utils.transfer import migrate_many
        set_status("Copying")

        # -------------------------------------------------------------------------
        # Optional USB migration
        # -------------------------------------------------------------------------
        t_mig0 = time.perf_counter()

        # Only migrate files successfully processed this run
        img_paths = [IMAGE_DIR / fn for fn in processed_files]

        res_img = migrate_many(
            sources=img_paths,
            logger=logger,
            verify="sampled",     # or "sha256"
            delete_src=True,
        )

        mig_time = time.perf_counter() - t_mig0
        logger.info(
            "usb_migration time=%.3fs images: ok=%s copied=%d deleted=%d failed=%d",
            mig_time,
            res_img.ok, res_img.copied, res_img.deleted, res_img.failed,
        )

    total_run_time = time.perf_counter() - t_start
    logger.info(
        "summary total_run_time=%.3fs gps_acquire_time=%.3fs imaging_time=%.3fs post_time=%.3fs usb_migration_time=%.3fs",
        total_run_time,
        gps_acquire_time,
        imaging_time,
        post_time,
        mig_time,
    )

    set_status("Ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())