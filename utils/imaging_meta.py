#!/usr/bin/env python3
"""
utils.imaging_meta
==================

Purpose
-------
Centralize "run metadata" creation for gonet4.py:

- Overlay banner text
- EXIF formatting helpers for GPS tags
- Camera EXIF tag dictionary assembly
- Foreground overlay banner JPEG creation

This isolates the formatting rules from the main imaging script so that gonet4.py
can remain a readable orchestration layer.

Notes
-----
- We keep the legacy EXIF GPS formatting convention: degrees/minutes/seconds as
  "deg/1,mnt/1,sec/1" strings, and altitude as "millimeters/1000".
- If GPS is bypassed / not OK, overlay text explicitly shows "GPS BYPASSED".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import gmtime, strftime
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path("/home/pi/Tools/Camera/dejavu/DejaVuSans-Bold.ttf")

BANNER_WIDTH: int = 3040
BANNER_HEIGHT: int = 60
BANNER_FONT_SIZE: int = 40

@dataclass(frozen=True)
class RunMeta:
    """
    RunMeta
    ------

    Container for all "run metadata" needed by gonet4.py and the imaging pipeline.

    Parameters
    ----------
    hostname : str
        Device hostname.
    version : str
        Version identifier (from /home/pi/Tools/Version).
    utc_stamp : str
        Human-friendly UTC timestamp shown in overlay.
    exp_s : str
        Exposure in seconds (string) for overlay, e.g. "6.0".
    iso : int
        ISO for overlay.
    gps_ok : bool
        True if GPS fix is OK (mode==3).
    gps_mode : int
        GPS mode from FetchGPS (0..3).
    latitude : float
        Latitude in degrees.
    longitude : float
        Longitude in degrees.
    altitude : float
        Altitude in meters.
    lenscap : str
        Lens cap status string.
    overlay_text : str
        Full text printed on the overlay banner.
    camera_exif_tags : dict[str, str]
        Dict of EXIF tags to apply to camera.exif_tags before capture.
        Keys are PiCamera EXIF keys (e.g. "GPS.GPSLatitude", "IFD0.Artist").
    """
    hostname: str
    version: str
    utc_stamp: str
    exp_s: str
    iso: int
    gps_ok: bool
    gps_mode: int
    latitude: float
    longitude: float
    altitude: float
    lenscap: str
    overlay_text: str
    camera_exif_tags: dict[str, str]


# -----------------------------------------------------------------------------
# EXIF formatting helpers
# -----------------------------------------------------------------------------

def convert_gps_lat_to_exif_lat(latitude: float) -> str:
    latitude = abs(latitude)
    mnt, sec = divmod(latitude * 3600, 60)
    deg, mnt = divmod(mnt, 60)
    deg = int(round(deg, 0))
    mnt = int(round(mnt, 0))
    sec = int(round(sec, 0))
    return f"{deg}/1,{mnt}/1,{sec}/1"


def convert_gps_long_to_exif_long(longitude: float) -> str:
    longitude = abs(longitude)
    mnt, sec = divmod(longitude * 3600, 60)
    deg, mnt = divmod(mnt, 60)
    deg = int(round(deg, 0))
    mnt = int(round(mnt, 0))
    sec = int(round(sec, 0))
    return f"{deg}/1,{mnt}/1,{sec}/1"


def get_exif_lat_dir(latitude: float) -> str:
    return "N" if latitude >= 0 else "S"


def get_exif_long_dir(longitude: float) -> str:
    return "E" if longitude > 0 else "W"


def convert_gps_alt_to_exif_alt(altitude: float) -> str:
    return f"{int(altitude * 1000)}/1000"

def utc_now_exif_datetime() -> str:
    """
    Return current UTC time in EXIF DateTime format.

    EXIF uses the format "YYYY:MM:DD HH:MM:SS".
    """
    return strftime("%Y:%m:%d %H:%M:%S", gmtime())

# -----------------------------------------------------------------------------
# Public builders
# -----------------------------------------------------------------------------

def build_run_meta(
    *,
    hostname: str,
    version: str,
    shutter_speed: int,
    iso: int,
    white_balance_gains: Any,
    gps_ok: bool,
    gps_mode: int,
    latitude: float,
    longitude: float,
    altitude: float,
    lenscap: str,
) -> RunMeta:
    """
    Build a RunMeta object (overlay + camera EXIF tags).

    Parameters
    ----------
    hostname
        Device hostname.
    version
        Version string.
    shutter_speed
        Exposure time in microseconds.
    iso
        ISO value.
    white_balance_gains
        WB gains tuple (kept in EXIF Software/Artist strings).
    gps_ok
        True if GPS fix is OK.
    gps_mode
        GPS mode integer.
    latitude
        Latitude degrees.
    longitude
        Longitude degrees.
    altitude
        Altitude meters.
    lenscap
        Lens cap status string.

    Returns
    -------
    RunMeta
        Fully populated metadata container.
    """
    utc_stamp = strftime("%y%m%d %H:%M:%S", gmtime())

    exif_utc = utc_now_exif_datetime()

    exp_s = str(round(shutter_speed / 1_000_000, 2))

    if gps_ok:
        gps_text = f"{abs(latitude)} {get_exif_lat_dir(latitude)} {abs(longitude)} {get_exif_long_dir(longitude)} {altitude} M"
    else:
        gps_text = "GPS BYPASSED"

    overlay_text = (
        "Adler / Far Horizons  "
        + hostname
        + " "
        + version
        + " Exp: "
        + exp_s
        + "s"
        + " ISO: "
        + str(iso)
        + " "
        + utc_stamp
        + " UTC "
        + gps_text
    )

    # GPS EXIF strings (if GPS is bypassed we keep zeros, consistent with legacy behavior)
    exif_latitude = convert_gps_lat_to_exif_lat(latitude)
    exif_longitude = convert_gps_long_to_exif_long(longitude)
    exif_altitude = convert_gps_alt_to_exif_alt(altitude)

    # Keep the legacy "Software" and "Artist" blobs (but assembled centrally)
    software = hostname + " " + version + " WB: " + str(white_balance_gains)
    artist = (
        f"Hostname: {hostname}, "
        f"Version: {version}, "
        f"WB: {white_balance_gains}, "
        f"Lat: {latitude}, "
        f"Long: {longitude}, "
        f"Alt: {altitude}, "
        f"Lenscap: {lenscap}"
    )

    camera_exif_tags = {
        "GPS.GPSLongitude": exif_longitude,
        "GPS.GPSLongitudeRef": get_exif_long_dir(longitude),
        "GPS.GPSLatitude": exif_latitude,
        "GPS.GPSLatitudeRef": get_exif_lat_dir(latitude),
        "GPS.GPSAltitude": exif_altitude,

        "EXIF.DateTimeOriginal": exif_utc,
        "EXIF.DateTimeDigitized": exif_utc,
        "IFD0.DateTime": exif_utc,

        "IFD0.Software": software,
        "IFD0.Artist": artist,
    }

    return RunMeta(
        hostname=hostname,
        version=version,
        utc_stamp=utc_stamp,
        exp_s=exp_s,
        iso=iso,
        gps_ok=gps_ok,
        gps_mode=gps_mode,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        lenscap=lenscap,
        overlay_text=overlay_text,
        camera_exif_tags=camera_exif_tags,
    )


def write_overlay_banner(
    *,
    text: str,
    out_path: Path,
) -> None:
    """
    Create the overlay banner JPEG at out_path.

    Parameters
    ----------
    text
        Banner text to render.
    out_path
        Output file path for the banner JPEG.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (BANNER_WIDTH, BANNER_HEIGHT), color=(0, 0, 0))
    font = ImageFont.truetype(str(FONT_PATH), BANNER_FONT_SIZE)
    d = ImageDraw.Draw(img)
    d.text((20, 10), text, font=font, fill=(255, 255, 255))

    # Legacy behavior: rotate 90 degrees and save as JPEG
    img.rotate(90, expand=True).save(str(out_path), "JPEG")